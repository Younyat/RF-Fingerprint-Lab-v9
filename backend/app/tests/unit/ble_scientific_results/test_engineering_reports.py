"""Paper progress dashboard, point 4 (2026-08-11): S1/S2 engineering report
aggregators -- pure functions over explicitly-synthetic fixtures, never
touching real repository storage. Both reuse only existing metric
primitives (balanced_accuracy/coverage); neither is a new statistical test.
"""
from __future__ import annotations

import pytest

from app.modules.ble_scientific_results.engineering_reports import (
    compute_channel_transport_report,
    compute_offline_nearlive_report,
)

CHANNEL_TRANSPORT_SYNTHETIC_FIXTURE = {
    37: [
        {"example_id": "e1", "true_label": "A", "predicted_label": "A", "final_decision": "IDENTIFIED"},
        {"example_id": "e2", "true_label": "B", "predicted_label": "B", "final_decision": "IDENTIFIED"},
    ],
    38: [
        {"example_id": "e3", "true_label": "A", "predicted_label": "A", "final_decision": "IDENTIFIED"},
        {"example_id": "e4", "true_label": "B", "predicted_label": "A", "final_decision": "IDENTIFIED"},
    ],
}
OFFLINE_NEARLIVE_SYNTHETIC_FIXTURE = [
    ({"predicted_class": "A", "final_decision": "IDENTIFIED", "class_probability": 0.9}, {"predicted_class": "A", "final_decision": "IDENTIFIED", "class_probability": 0.85}),
    ({"predicted_class": "B", "final_decision": "IDENTIFIED", "class_probability": 0.7}, {"predicted_class": "A", "final_decision": "IDENTIFIED", "class_probability": 0.6}),
]


def test_channel_transport_report_computes_real_metrics_per_channel():
    report = compute_channel_transport_report(
        frozen_bundle_id="BUNDLE-CH37-DEV", predictions_by_channel=CHANNEL_TRANSPORT_SYNTHETIC_FIXTURE,
        known_classes=["A", "B"], center_frequency_hz_by_channel={37: 2_402_000_000, 38: 2_426_000_000},
    )
    by_channel = {row["channel"]: row for row in report.per_channel}
    assert by_channel[37]["balanced_accuracy"] == 1.0
    assert by_channel[38]["balanced_accuracy"] == 0.5
    assert by_channel[38]["confusion_matrix"]["B"]["A"] == 1
    assert report.interpretation_note == "bounded channel transport -- never channel invariance"


def test_channel_transport_report_rejects_empty_input():
    with pytest.raises(ValueError):
        compute_channel_transport_report(frozen_bundle_id="B", predictions_by_channel={}, known_classes=["A"], center_frequency_hz_by_channel={})


def test_channel_transport_uses_only_the_one_named_frozen_bundle():
    report = compute_channel_transport_report(
        frozen_bundle_id="BUNDLE-X", predictions_by_channel=CHANNEL_TRANSPORT_SYNTHETIC_FIXTURE,
        known_classes=["A", "B"], center_frequency_hz_by_channel={37: 1, 38: 2},
    )
    assert all(row["frozen_bundle_id"] == "BUNDLE-X" for row in report.per_channel)


def test_offline_nearlive_report_with_no_pairs_is_no_data():
    report = compute_offline_nearlive_report(matched_pairs=None)
    assert report.pairing_status == "NO_DATA"
    assert report.analytical_agreement is None
    assert all(v == "NOT_MEASURED" for v in report.computational_behavior.values())


def test_offline_nearlive_report_computes_real_agreement_from_supplied_pairs():
    report = compute_offline_nearlive_report(matched_pairs=OFFLINE_NEARLIVE_SYNTHETIC_FIXTURE)
    assert report.pairing_status == "COMPUTED_FROM_CALLER_SUPPLIED_PAIRS"
    assert report.analytical_agreement["decision_count"] == 2
    assert report.analytical_agreement["class_prediction_agreement"] == 0.5
    assert report.analytical_agreement["abstention_agreement"] == 1.0


def test_offline_nearlive_report_never_fabricates_unmeasured_computational_fields():
    report = compute_offline_nearlive_report(matched_pairs=OFFLINE_NEARLIVE_SYNTHETIC_FIXTURE, computational_metrics={"median_latency_ms": 42.0})
    assert report.computational_behavior["median_latency_ms"] == 42.0
    assert report.computational_behavior["p95_latency_ms"] == "NOT_MEASURED"
    assert report.computational_behavior["drop_rate"] == "NOT_MEASURED"


def test_offline_nearlive_report_documents_the_methodological_gap():
    report = compute_offline_nearlive_report()
    assert "matching key" in report.pairing_note
    assert report.pairing_status != "COMPUTED_FROM_CALLER_SUPPLIED_PAIRS"
