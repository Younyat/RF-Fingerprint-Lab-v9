"""Paper progress dashboard, point 4 (2026-08-11): S1 (CH37->CH38/39
channel transport) and S2 (offline vs near-live) engineering-analysis
report schemas + pure aggregation functions. Explicitly separate from
RQ1-RQ4 -- these interpret as "bounded channel transport" (never "channel
invariance") and offline/near-live equivalence, never a paper RQ.

Both aggregation functions reuse ONLY already-established, dependency-light
primitives (`statistics.metrics.balanced_accuracy`/`coverage`) -- no new
statistical test, no retraining, no model change. Neither function computes
anything from raw I/Q or re-runs a model; both take already-scored
per-example predictions the caller supplies (exactly like
`statistics.sensitivity.leave_one_device_out_sensitivity` already does for
RQ2/RQ3/RQ4).

S1's method (frozen model trained on CH37 development data, no retraining,
same decision rule applied to CH38/39 examples) is fully specified by the
shape of `compute_channel_transport_report`'s input -- the caller is
structurally required to supply already-scored predictions from ONE frozen
model, never a per-channel retrained one.

S2 has one real, unresolved methodological gap, deliberately NOT invented
here: there is no established mechanism today to match a near-live decision
to "the same retained sample interval" as an offline one (near-live
inference does not go through the dataset/example pipeline that would give
both sides a shared join key). `compute_offline_nearlive_report` therefore
requires the CALLER to supply already-paired (offline, near-live) records;
if no such pairing exists, this is reported as
`pairing_status="METHODOLOGICAL_DECISION_REQUIRED"` rather than guessed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from .statistics.metrics import balanced_accuracy, coverage

CHANNEL_TRANSPORT_SCHEMA_VERSION = "ble-scientific-results-channel-transport-v1"
OFFLINE_NEARLIVE_SCHEMA_VERSION = "ble-scientific-results-offline-nearlive-v1"


def _macro_f1(true_labels: Sequence[str], predicted_labels: Sequence[str], labels: Sequence[str]) -> float:
    """Same macro-F1 definition Evaluator.evaluate_split already uses
    (precision/recall per class, averaged) -- reimplemented here in a
    dependency-light way (no sklearn/Evaluator import) purely to avoid a
    circular import (ble_rffi_studio.evaluation.evaluator already imports
    FROM this package's statistics module)."""
    f1_scores = []
    for label in labels:
        tp = sum(1 for t, p in zip(true_labels, predicted_labels) if t == label and p == label)
        fp = sum(1 for t, p in zip(true_labels, predicted_labels) if t != label and p == label)
        fn = sum(1 for t, p in zip(true_labels, predicted_labels) if t == label and p != label)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        f1_scores.append(f1)
    return sum(f1_scores) / len(f1_scores) if f1_scores else 0.0


def _confusion_matrix(true_labels: Sequence[str], predicted_labels: Sequence[str], labels: Sequence[str]) -> dict[str, dict[str, int]]:
    matrix = {t: {p: 0 for p in labels} for t in labels}
    for t, p in zip(true_labels, predicted_labels):
        if t in matrix and p in matrix[t]:
            matrix[t][p] += 1
    return matrix


@dataclass
class ChannelTransportReport:
    schema_version: str = CHANNEL_TRANSPORT_SCHEMA_VERSION
    per_channel: list[dict[str, Any]] = field(default_factory=list)
    interpretation_note: str = "bounded channel transport -- never channel invariance"


def compute_channel_transport_report(
    *, frozen_bundle_id: str, predictions_by_channel: dict[int, list[dict[str, Any]]], known_classes: Sequence[str],
    center_frequency_hz_by_channel: dict[int, int],
) -> ChannelTransportReport:
    """`predictions_by_channel`: {channel: [{"example_id","true_label",
    "predicted_label","final_decision"}, ...]} -- already-scored predictions
    from the ONE frozen model named by `frozen_bundle_id` (no retraining per
    channel, structurally enforced by there being only one bundle id for
    the whole call). Raises ValueError on an empty input -- never returns a
    fabricated zero-channel report."""
    if not predictions_by_channel:
        raise ValueError("NEED_AT_LEAST_ONE_CHANNEL_OF_PREDICTIONS")
    per_channel: list[dict[str, Any]] = []
    for channel, predictions in sorted(predictions_by_channel.items()):
        comparable = [p for p in predictions if p["true_label"] in known_classes]
        decided = [p for p in comparable if p.get("final_decision", "IDENTIFIED") != "INSUFFICIENT_EVIDENCE"]
        true_labels = [p["true_label"] for p in decided]
        predicted_labels = [p["predicted_label"] for p in decided]
        entry: dict[str, Any] = {
            "channel": channel, "center_frequency_hz": center_frequency_hz_by_channel.get(channel),
            "frozen_bundle_id": frozen_bundle_id, "windows": len(predictions),
        }
        if decided:
            entry["balanced_accuracy"] = balanced_accuracy(true_labels, predicted_labels, labels=list(known_classes))
            entry["macro_f1"] = _macro_f1(true_labels, predicted_labels, known_classes)
            entry["coverage"] = coverage(len(comparable), len(comparable) - len(decided)) if comparable else None
            entry["confusion_matrix"] = _confusion_matrix(true_labels, predicted_labels, known_classes)
        else:
            entry["balanced_accuracy"] = None
            entry["macro_f1"] = None
            entry["coverage"] = None
            entry["confusion_matrix"] = None
        per_channel.append(entry)
    return ChannelTransportReport(per_channel=per_channel)


@dataclass
class OfflineNearliveReport:
    schema_version: str = OFFLINE_NEARLIVE_SCHEMA_VERSION
    pairing_status: str = "METHODOLOGICAL_DECISION_REQUIRED"
    pairing_note: str = (
        "No established mechanism exists today to match a near-live decision to the same retained sample interval "
        "as an offline decision -- near-live inference does not go through the dataset/example pipeline. This "
        "function computes real agreement/computational statistics ONLY over pairs the caller already matched by "
        "some external means; it never invents a matching key."
    )
    analytical_agreement: dict[str, Any] | None = None
    computational_behavior: dict[str, Any] | None = None


_COMPUTATIONAL_FIELDS = ("median_latency_ms", "p95_latency_ms", "throughput_per_s", "drop_count", "drop_rate", "backlog", "declared_hardware", "declared_software_path")


def compute_offline_nearlive_report(
    *, matched_pairs: list[tuple[dict[str, Any], dict[str, Any]]] | None = None, computational_metrics: dict[str, Any] | None = None,
) -> OfflineNearliveReport:
    """`matched_pairs`: [(offline_decision, nearlive_decision), ...], each a
    dict with at least `predicted_class`/`final_decision` and optionally
    `class_probability`. `computational_metrics`: a dict with whichever of
    _COMPUTATIONAL_FIELDS were actually measured -- any field absent stays
    `NOT_MEASURED`, never 0. Returns pairing_status=NO_DATA when no pairs
    are supplied (nothing to compute), METHODOLOGICAL_DECISION_REQUIRED
    only applies to the join-key question itself, documented above -- once
    pairs ARE supplied by the caller, agreement is computed for real."""
    report = OfflineNearliveReport()
    if matched_pairs:
        n = len(matched_pairs)
        decision_count = n
        class_agree = sum(1 for offline, nearlive in matched_pairs if offline.get("predicted_class") == nearlive.get("predicted_class"))
        abstention_agree = sum(1 for offline, nearlive in matched_pairs if offline.get("final_decision") == nearlive.get("final_decision"))
        score_pairs = [(o.get("class_probability"), nl.get("class_probability")) for o, nl in matched_pairs if o.get("class_probability") is not None and nl.get("class_probability") is not None]
        report.analytical_agreement = {
            "decision_count": decision_count,
            "class_prediction_agreement": class_agree / n,
            "abstention_agreement": abstention_agree / n,
            "score_agreement_mean_abs_diff": (sum(abs(o - nl) for o, nl in score_pairs) / len(score_pairs)) if score_pairs else None,
            "score_agreement_n_comparable": len(score_pairs),
        }
        report.pairing_status = "COMPUTED_FROM_CALLER_SUPPLIED_PAIRS"
    else:
        report.pairing_status = "NO_DATA"

    computational_metrics = computational_metrics or {}
    report.computational_behavior = {field_name: computational_metrics.get(field_name, "NOT_MEASURED") for field_name in _COMPUTATIONAL_FIELDS}
    return report
