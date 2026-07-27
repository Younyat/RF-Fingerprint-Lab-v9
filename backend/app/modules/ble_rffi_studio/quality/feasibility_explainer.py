"""Human-readable "do we have enough evidence yet" explanation, separate
from SplitBuilder's machine-readable infeasibility_reason string. Reuses the
exact same per-task thresholds SplitBuilder enforces (imported, not
duplicated) so the two can never silently drift apart.

Deliberately goes further than a bare have/need dump: an operator with no
RF-fingerprinting background cannot be expected to infer "add 3 more target
sessions" from {"target_sessions": 0, "target_sessions_minimum": 3} on their
own, and has no way to know which of the three scientific tasks even fits
their current data without checking each one by hand. next_steps spells out
the concrete action; recommend_scientific_task() picks (and explains) the
best-fitting task given what has actually been captured so far.
"""
from __future__ import annotations

from typing import Any

from ..contracts import ExampleRecord
from .split_builder import _MIN_BACKGROUND_SESSIONS, _MIN_SESSIONS_PER_UNIT, _MIN_TARGET_SESSIONS, _MIN_UNKNOWN_SESSIONS

TASK_DISPLAY_NAMES = {
    "SAME_MODEL_UNIT_IDENTIFICATION": "Identificar unidades del mismo modelo",
    "MULTI_DEVICE_CLASSIFICATION": "Clasificar entre varios dispositivos",
    "TARGET_VS_BACKGROUND": "Detectar el objetivo frente al entorno",
    "UNKNOWN_DEVICE_REJECTION": "Rechazar dispositivos desconocidos",
}

_REAL_TASKS = ("TARGET_VS_BACKGROUND", "SAME_MODEL_UNIT_IDENTIFICATION", "UNKNOWN_DEVICE_REJECTION")


def _sessions_by_unit(examples: list[ExampleRecord]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for example in examples:
        if example.physical_unit_id:
            result.setdefault(example.physical_unit_id, set()).add(example.session_id)
    return result


def explain_feasibility(examples: list[ExampleRecord], scientific_task: str) -> dict[str, Any]:
    sessions_by_unit = _sessions_by_unit(examples)
    units_total = len(sessions_by_unit)
    units_ready = sum(1 for sessions in sessions_by_unit.values() if len(sessions) >= _MIN_SESSIONS_PER_UNIT)
    target_sessions = len({e.session_id for e in examples if e.physical_unit_id})
    background_sessions = len({e.session_id for e in examples if not e.physical_unit_id})
    next_steps: list[str] = []

    if scientific_task in ("SAME_MODEL_UNIT_IDENTIFICATION", "MULTI_DEVICE_CLASSIFICATION"):
        feasible = units_ready >= 2
        have = {"physical_units_total": units_total, "physical_units_with_enough_sessions": units_ready}
        need = {"physical_units_minimum": 2, "independent_sessions_per_unit_minimum": _MIN_SESSIONS_PER_UNIT}
        human_summary = (
            f"Tienes {units_total} unidad(es) fisica(s) registrada(s); {units_ready} con suficientes sesiones independientes.\n"
            f"Esta tarea necesita al menos 2 unidades fisicas del mismo modelo, cada una con al menos "
            f"{_MIN_SESSIONS_PER_UNIT} sesiones independientes (una para entrenamiento, una para validacion, una para prueba)."
        )
        if units_total < 2:
            next_steps.append(f"Registra {2 - units_total} unidad(es) fisica(s) mas del mismo modelo (necesitas 2 en total).")
        under_ready = [(unit_id, len(sessions)) for unit_id, sessions in sessions_by_unit.items() if len(sessions) < _MIN_SESSIONS_PER_UNIT]
        for unit_id, have_sessions in under_ready:
            next_steps.append(f"Anade {_MIN_SESSIONS_PER_UNIT - have_sessions} sesion(es) independiente(s) mas de {unit_id} (tiene {have_sessions}, necesita {_MIN_SESSIONS_PER_UNIT}).")
        unit_count_score = min(units_total, 2) / 2
        readiness_score = min(units_ready, 2) / 2
        progress = (unit_count_score + readiness_score) / 2
    elif scientific_task == "TARGET_VS_BACKGROUND":
        feasible = target_sessions >= _MIN_TARGET_SESSIONS and background_sessions >= _MIN_BACKGROUND_SESSIONS
        have = {"target_sessions": target_sessions, "background_sessions": background_sessions}
        need = {"target_sessions_minimum": _MIN_TARGET_SESSIONS, "background_sessions_minimum": _MIN_BACKGROUND_SESSIONS}
        human_summary = (
            f"Tienes {target_sessions} sesion(es) independiente(s) del objetivo y {background_sessions} sesion(es) ambiental(es).\n"
            f"Esta tarea necesita al menos {_MIN_TARGET_SESSIONS} sesiones independientes del objetivo (una por particion) y "
            f"al menos {_MIN_BACKGROUND_SESSIONS} sesion ambiental reservada fuera de entrenamiento."
        )
        if target_sessions < _MIN_TARGET_SESSIONS:
            next_steps.append(f"Anade {_MIN_TARGET_SESSIONS - target_sessions} sesion(es) mas del dispositivo objetivo (aislado o con direccion confirmada).")
        if background_sessions < _MIN_BACKGROUND_SESSIONS:
            next_steps.append(f"Anade {_MIN_BACKGROUND_SESSIONS - background_sessions} sesion(es) mas de entorno/ambiente (sin el objetivo presente).")
        target_score = min(target_sessions / _MIN_TARGET_SESSIONS, 1.0) if _MIN_TARGET_SESSIONS else 1.0
        background_score = min(background_sessions / _MIN_BACKGROUND_SESSIONS, 1.0) if _MIN_BACKGROUND_SESSIONS else 1.0
        progress = (target_score + background_score) / 2
    elif scientific_task == "UNKNOWN_DEVICE_REJECTION":
        feasible = units_ready >= 1 and background_sessions >= _MIN_UNKNOWN_SESSIONS
        have = {"known_physical_units_with_enough_sessions": units_ready, "unknown_device_sessions": background_sessions}
        need = {"known_physical_units_minimum": 1, "independent_sessions_per_known_unit_minimum": _MIN_SESSIONS_PER_UNIT, "unknown_device_sessions_minimum": _MIN_UNKNOWN_SESSIONS}
        human_summary = (
            f"Tienes {units_ready} unidad(es) conocida(s) con suficientes sesiones, y {background_sessions} sesion(es) de dispositivo desconocido.\n"
            f"Esta tarea necesita al menos 1 unidad conocida con {_MIN_SESSIONS_PER_UNIT} sesiones independientes, y al menos "
            f"{_MIN_UNKNOWN_SESSIONS} sesiones de dispositivos desconocidos (reservadas para validacion y prueba, nunca entrenamiento)."
        )
        if units_ready < 1:
            next_steps.append(f"Consigue al menos 1 unidad conocida con {_MIN_SESSIONS_PER_UNIT} sesiones independientes.")
        if background_sessions < _MIN_UNKNOWN_SESSIONS:
            next_steps.append(f"Anade {_MIN_UNKNOWN_SESSIONS - background_sessions} sesion(es) mas de dispositivo(s) desconocido(s)/no registrado(s).")
        known_score = min(units_ready, 1) / 1
        unknown_score = min(background_sessions / _MIN_UNKNOWN_SESSIONS, 1.0) if _MIN_UNKNOWN_SESSIONS else 1.0
        progress = (known_score + unknown_score) / 2
    else:
        raise ValueError(f"UNKNOWN_SCIENTIFIC_TASK:{scientific_task}")

    if feasible:
        next_steps = []  # nothing left to add -- ready to build the split now

    return {
        "scientific_task": scientific_task,
        "scientific_task_display": TASK_DISPLAY_NAMES.get(scientific_task, scientific_task),
        "feasible": feasible,
        "have": have,
        "need": need,
        "human_summary": human_summary,
        "next_steps": next_steps,
        "progress": round(progress, 3),
    }


def recommend_scientific_task(examples: list[ExampleRecord]) -> dict[str, Any]:
    """Which of the three real scientific tasks best fits what has actually
    been captured so far -- an operator with no RF-fingerprinting background
    has no way to know, e.g., that owning exactly one physical unit rules out
    SAME_MODEL_UNIT_IDENTIFICATION (it needs two of the same model) but is
    exactly what TARGET_VS_BACKGROUND is for. Prefers a task that is already
    feasible; if none is, prefers whichever is closest (highest `progress`),
    so the recommendation always points at the least additional work."""
    candidates = [explain_feasibility(examples, task) for task in _REAL_TASKS]
    feasible = [c for c in candidates if c["feasible"]]
    pool = feasible or candidates
    best = max(pool, key=lambda c: c["progress"])
    return {
        "recommended_task": best["scientific_task"],
        "recommended_task_display": best["scientific_task_display"],
        "reason": (
            f"Ya tienes suficientes datos para esta tarea ({best['human_summary'].splitlines()[0]})."
            if best["feasible"] else
            f"Es la tarea mas cercana a estar lista con lo que tienes ahora ({best['human_summary'].splitlines()[0]})."
        ),
        "candidates": candidates,
    }
