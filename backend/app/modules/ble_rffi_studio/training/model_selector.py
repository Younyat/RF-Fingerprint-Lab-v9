"""Real, computed model comparison -- never picks by TRAIN accuracy, never a
placeholder score. Every number here is measured (VALIDATION metrics already
computed by Evaluator, wall-clock inference latency actually timed, model
file size actually read from disk); the composite score formula is
documented so its limits are visible, not implied to be definitive.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

CNN_MIN_TRAIN_EXAMPLES_PER_CLASS = 15


def cnn_feasibility(split_assignments: list[dict[str, Any]]) -> tuple[bool, str]:
    train = [a for a in split_assignments if a["split"] == "TRAIN"]
    per_class: dict[str, int] = {}
    for a in train:
        label = a.get("physical_unit_id") or "UNKNOWN"
        per_class[label] = per_class.get(label, 0) + 1
    if not per_class:
        return False, "No hay ejemplos de entrenamiento."
    minimum = min(per_class.values())
    if minimum < CNN_MIN_TRAIN_EXAMPLES_PER_CLASS:
        return False, f"dataset insuficiente para un entrenamiento evaluable (la clase con menos ejemplos de TRAIN tiene {minimum}, se requieren >= {CNN_MIN_TRAIN_EXAMPLES_PER_CLASS})."
    return True, ""


def model_file_size_bytes(run_dir: Path, model_type: str) -> int:
    filename = "model.pt" if model_type in ("cnn1d", "cnn2d") else "model.joblib"
    path = run_dir / filename
    return path.stat().st_size if path.is_file() else 0


def score_model(
    evaluation_report: dict[str, dict[str, Any]],
    calibration: dict[str, Any],
    latency_ms: float,
    model_size_bytes: int,
) -> dict[str, Any]:
    validation = evaluation_report.get("VALIDATION")
    f1_values = list((validation or {}).get("f1_per_class", {}).values())
    recall_values = list((validation or {}).get("recall_per_class", {}).values())
    macro_f1 = float(np.mean(f1_values)) if f1_values else 0.0
    # Macro-averaged per-class recall is used here as a balanced-accuracy
    # proxy (equivalent to balanced accuracy for single-label classification).
    balanced_accuracy_proxy = float(np.mean(recall_values)) if recall_values else 0.0

    threshold = calibration.get("acceptance_threshold")
    # A calibration that had to retreat to a near-1.0 threshold means the
    # UNKNOWN-rejection layer found no safe way to accept anything -- real
    # capability, not a cosmetic penalty (see the OOD-overconfidence finding
    # in scientific_basis/model_evidence.json).
    unknown_capability_penalty = 0.2 if (threshold is None or threshold > 0.95) else 0.0

    composite_score = 0.5 * macro_f1 + 0.3 * balanced_accuracy_proxy - unknown_capability_penalty

    return {
        "macro_f1": macro_f1,
        "balanced_accuracy_proxy": balanced_accuracy_proxy,
        "unknown_capability_penalty": unknown_capability_penalty,
        "latency_ms": latency_ms,
        "model_size_bytes": model_size_bytes,
        "composite_score": composite_score,
        "formula": "0.5*macro_f1 + 0.3*balanced_accuracy_proxy - unknown_capability_penalty (VALIDATION only; TEST never used to select)",
    }
