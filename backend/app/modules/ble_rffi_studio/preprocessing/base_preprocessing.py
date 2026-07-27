"""Shared (base) preprocessing: the one step every model family agrees on --
loading the exact evidence window an ExampleRecord points to -- plus a set of
OPT-IN, signal-altering steps that are OFF by default (design correction
#11). Enabling any of them requires a technique_id that scientific_basis/
preprocessing_evidence.json actually justifies; this is checked in code, not
just documented.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

_STEP_NAMES = ("cfo_correction", "phase_normalization", "amplitude_normalization", "temporal_alignment", "transient_removal")


def load_iq_window(iq_path: Path, iq_start_sample: int, iq_end_sample: int) -> np.ndarray:
    data = np.memmap(iq_path, dtype=np.complex64, mode="r")
    return np.asarray(data[iq_start_sample:iq_end_sample])


@dataclass(frozen=True)
class BasePreprocessingProfile:
    profile_id: str
    cfo_correction: bool = False
    phase_normalization: bool = False
    amplitude_normalization: bool = False
    temporal_alignment: bool = False
    transient_removal: bool = False
    # step_name -> technique_id from scientific_basis/technique_registry.json
    justification_technique_ids: dict[str, str] = field(default_factory=dict)

    def enabled_steps(self) -> list[str]:
        return [name for name in _STEP_NAMES if getattr(self, name)]

    def validate_justifications(self, preprocessing_evidence_path: Path) -> None:
        """Raises if any enabled step lacks a justification that
        preprocessing_evidence.json actually records for it. Never silently
        allows a signal-altering step to run unjustified."""
        evidence = json.loads(preprocessing_evidence_path.read_text(encoding="utf-8"))
        evidence_by_step = {item["step_id"]: item for item in evidence.get("steps", [])}
        for step in self.enabled_steps():
            technique_id = self.justification_technique_ids.get(step)
            if not technique_id:
                raise ValueError(f"PREPROCESSING_STEP_ENABLED_WITHOUT_JUSTIFICATION:{step}")
            record = evidence_by_step.get(step)
            if record is None or record.get("justified_by_technique_id") != technique_id:
                raise ValueError(f"PREPROCESSING_STEP_JUSTIFICATION_MISMATCH:{step}:{technique_id}")


# The only profile shipped so far: everything opt-in stays off. Any profile
# that turns a step on must be a NEW, separately versioned profile_id.
DEFAULT_BASE_PROFILE = BasePreprocessingProfile(profile_id="base-v1")


def estimate_cfo_hz(window: np.ndarray, sample_rate_sps: float) -> float:
    if len(window) < 2:
        return 0.0
    phase = np.unwrap(np.angle(window))
    mean_phase_step = np.mean(np.diff(phase))
    return float(mean_phase_step * sample_rate_sps / (2 * np.pi))


def apply_base_preprocessing(window: np.ndarray, profile: BasePreprocessingProfile, sample_rate_sps: float) -> np.ndarray:
    result = window
    if profile.cfo_correction:
        cfo_hz = estimate_cfo_hz(result, sample_rate_sps)
        n = np.arange(len(result))
        result = result * np.exp(-1j * 2 * np.pi * cfo_hz * n / sample_rate_sps)
    if profile.phase_normalization:
        if len(result) and result[0] != 0:
            result = result * np.exp(-1j * np.angle(result[0]))
    if profile.amplitude_normalization:
        rms = float(np.sqrt(np.mean(np.abs(result) ** 2))) if len(result) else 0.0
        if rms > 0:
            result = result / rms
    if profile.temporal_alignment:
        raise NotImplementedError("temporal_alignment has no validated implementation yet -- do not enable this step in any profile until one exists.")
    if profile.transient_removal:
        raise NotImplementedError("transient_removal has no validated implementation yet -- do not enable this step in any profile until one exists.")
    return result
