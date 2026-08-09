"""Leave-one-device-out (LODO) sensitivity analysis (2026-08-09 addition --
did not exist before this pass). Reuses the same per-example prediction
records and accuracy definition every other confirmatory metric in this
package uses (see evaluator.py's balanced_accuracy/macro_f1) -- no new
model, no retraining: this recomputes the SAME already-scored predictions,
just excluding one device's examples from the comparison each time, to show
whether the reported result depends heavily on any single enrolled device.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from .metrics import balanced_accuracy


@dataclass(frozen=True)
class LeaveOneDeviceOutResult:
    excluded_device_id: str
    n_comparable: int
    accuracy: float | None
    balanced_accuracy_value: float | None


def leave_one_device_out_sensitivity(
    predictions: list[dict[str, Any]], device_id_by_example_id: dict[str, str], known_classes: Sequence[str],
) -> list[LeaveOneDeviceOutResult]:
    """`predictions` are already-scored records (`example_id`, `true_label`,
    `predicted_label`) from a real, frozen model -- exactly the same shape
    Evaluator.evaluate_split consumes. One result per device that appears in
    `device_id_by_example_id`, excluding that device's own examples from the
    comparison it measures. Returns [] (never a fabricated result) when no
    prediction maps to a known device."""
    device_ids = sorted({device_id_by_example_id[p["example_id"]] for p in predictions if p["example_id"] in device_id_by_example_id})
    results: list[LeaveOneDeviceOutResult] = []
    for excluded_device in device_ids:
        remaining = [
            p for p in predictions
            if device_id_by_example_id.get(p["example_id"], excluded_device) != excluded_device
        ]
        comparable = [p for p in remaining if p["true_label"] in known_classes]
        if not comparable:
            results.append(LeaveOneDeviceOutResult(excluded_device_id=excluded_device, n_comparable=0, accuracy=None, balanced_accuracy_value=None))
            continue
        accuracy = sum(1 for p in comparable if p["predicted_label"] == p["true_label"]) / len(comparable)
        try:
            ba = balanced_accuracy([p["true_label"] for p in comparable], [p["predicted_label"] for p in comparable], labels=list(known_classes))
        except ValueError:
            ba = None
        results.append(LeaveOneDeviceOutResult(excluded_device_id=excluded_device, n_comparable=len(comparable), accuracy=accuracy, balanced_accuracy_value=ba))
    return results
