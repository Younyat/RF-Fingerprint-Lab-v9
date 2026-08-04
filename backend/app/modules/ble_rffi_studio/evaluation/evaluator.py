"""Fase 5: comparable metrics across models, plus UNKNOWN-rejection threshold
calibration. Design correction #16: the acceptance threshold is selected
using VALIDATION ONLY, and must be evaluated against both known-class
predictions and true "unknown" examples (an example whose true label never
appeared among TRAIN's classes) -- never picked to just look good on the
known classes alone.

This implementation calibrates on max-class-probability rather than
embedding distance to a centroid; the design explicitly allows either
approach and warns against treating either as an automatically-accepted
solution -- so `distance` is left None here and documented as N/A for this
probability-based calibration, not silently omitted.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

FinalDecision = Literal["IDENTIFIED", "UNKNOWN", "INSUFFICIENT_EVIDENCE"]


@dataclass
class SplitEvaluationReport:
    split: str
    n_examples: int
    n_comparable_to_known_classes: int
    accuracy: float | None
    precision_per_class: dict[str, float]
    recall_per_class: dict[str, float]
    f1_per_class: dict[str, float]
    confusion_matrix: dict[str, dict[str, int]]
    # "VALID" unless known_classes itself has fewer than 2 entries -- a
    # classifier can never be validated against a single class (a confusion
    # matrix with one row/column proves nothing about discrimination, e.g.
    # TARGET_DEVICE vs BACKGROUND_ENVIRONMENT with only TARGET_DEVICE
    # present). training_service.py's own TRAIN-class gate should make this
    # unreachable in practice -- this is defense in depth, not the primary
    # guard, so a report can never be presented as a real result if it is
    # ever reached anyway.
    evaluation_validity: str = "VALID"
    # Plain accuracy alone can look excellent on an imbalanced or
    # session-confounded split while hiding that one class is essentially
    # never recalled -- macro_f1/balanced_accuracy average PER-CLASS
    # performance equally, so a model that only ever predicts the majority
    # class cannot hide behind a high raw accuracy number. Both are derived
    # from precision_per_class/recall_per_class/f1_per_class above (never
    # recomputed independently), so they can never disagree with the
    # per-class numbers already in this same report. None only when there
    # was nothing comparable to evaluate (mirrors accuracy's own None case).
    macro_f1: float | None = None
    balanced_accuracy: float | None = None


class Evaluator:
    def evaluate_split(self, split: str, predictions: list[dict[str, Any]], known_classes: list[str]) -> SplitEvaluationReport:
        if len(known_classes) < 2:
            return SplitEvaluationReport(
                split=split, n_examples=len(predictions), n_comparable_to_known_classes=0, accuracy=None,
                precision_per_class={}, recall_per_class={}, f1_per_class={}, confusion_matrix={},
                evaluation_validity="INVALID_SINGLE_CLASS_EVALUATION",
            )
        comparable = [p for p in predictions if p["true_label"] in known_classes]
        if not comparable:
            return SplitEvaluationReport(
                split=split, n_examples=len(predictions), n_comparable_to_known_classes=0, accuracy=None,
                precision_per_class={}, recall_per_class={}, f1_per_class={}, confusion_matrix={},
            )
        true_labels = [p["true_label"] for p in comparable]
        predicted_labels = [p["predicted_label"] for p in comparable]
        accuracy = float(np.mean([t == pr for t, pr in zip(true_labels, predicted_labels)]))

        precision, recall, f1, _ = precision_recall_fscore_support(true_labels, predicted_labels, labels=known_classes, zero_division=0)
        cm = confusion_matrix(true_labels, predicted_labels, labels=known_classes)
        confusion = {known_classes[i]: {known_classes[j]: int(cm[i][j]) for j in range(len(known_classes))} for i in range(len(known_classes))}

        return SplitEvaluationReport(
            split=split, n_examples=len(predictions), n_comparable_to_known_classes=len(comparable), accuracy=accuracy,
            precision_per_class=dict(zip(known_classes, precision.tolist())),
            recall_per_class=dict(zip(known_classes, recall.tolist())),
            f1_per_class=dict(zip(known_classes, f1.tolist())),
            confusion_matrix=confusion,
            macro_f1=float(np.mean(f1)), balanced_accuracy=float(np.mean(recall)),
        )

    def calibrate_unknown_threshold(self, validation_predictions: list[dict[str, Any]], known_classes: list[str], min_identified_precision: float = 0.9) -> float:
        """VALIDATION-only. A candidate threshold's precision is measured
        over every VALIDATION example whose top confidence clears it
        (known AND unknown examples alike) -- an unknown example that clears
        the threshold and gets identified as some known class always counts
        against precision, exactly like a known example being misclassified."""
        records = []
        for prediction in validation_predictions:
            probabilities = prediction.get("probabilities") or {}
            if not probabilities:
                continue
            confidence = max(probabilities.values())
            is_known = prediction["true_label"] in known_classes
            correct_if_identified = is_known and prediction["predicted_label"] == prediction["true_label"]
            records.append((confidence, correct_if_identified))

        if not records:
            return 1.0 + 1e-9  # no evidence to calibrate on -- reject everything

        candidate_thresholds = sorted({r[0] for r in records}, reverse=True)
        best_threshold = 1.0 + 1e-9
        for threshold in candidate_thresholds:
            identified = [correct for confidence, correct in records if confidence >= threshold]
            if not identified:
                continue
            precision = sum(identified) / len(identified)
            if precision >= min_identified_precision:
                best_threshold = threshold  # keep trying lower thresholds -- maximize recall subject to the precision floor
        return best_threshold

    def classify_with_threshold(self, prediction: dict[str, Any], acceptance_threshold: float) -> dict[str, Any]:
        probabilities = prediction.get("probabilities") or {}
        if not probabilities:
            return {
                "example_id": prediction.get("example_id"), "distance": None, "class_probability": None,
                "acceptance_threshold": acceptance_threshold, "predicted_class": None, "final_decision": "INSUFFICIENT_EVIDENCE",
            }
        predicted_class = max(probabilities, key=probabilities.get)
        confidence = probabilities[predicted_class]
        final_decision: FinalDecision = "IDENTIFIED" if confidence >= acceptance_threshold else "UNKNOWN"
        return {
            "example_id": prediction.get("example_id"), "distance": None, "class_probability": confidence,
            "acceptance_threshold": acceptance_threshold, "predicted_class": predicted_class, "final_decision": final_decision,
        }
