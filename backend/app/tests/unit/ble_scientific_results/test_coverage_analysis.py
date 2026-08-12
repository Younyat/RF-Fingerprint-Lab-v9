"""Coverage canonical producer (2026-08-12, Scientific Closure pass). Pure
aggregation over already-real CoverageRow entries -- never a second
abstention/coverage definition, never a fabricated bucket."""
from __future__ import annotations

import pytest

from app.modules.ble_scientific_results.coverage_analysis import (
    CoverageRow,
    coverage_row_from_decision_window,
    compute_coverage_summary,
)


def test_coverage_row_from_decision_window_marks_correct_only_with_real_ground_truth():
    identified = {"final_decision": "IDENTIFIED", "predicted_class": "UNIT-A", "physical_unit_id": "UNIT-A", "abstention_reason": None}
    row = coverage_row_from_decision_window(identified)
    assert row.decided is True
    assert row.correct is True

    misidentified = {"final_decision": "IDENTIFIED", "predicted_class": "UNIT-B", "physical_unit_id": "UNIT-A", "abstention_reason": None}
    row = coverage_row_from_decision_window(misidentified)
    assert row.correct is False

    unknown_ground_truth = {"final_decision": "IDENTIFIED", "predicted_class": "UNIT-A", "physical_unit_id": None, "abstention_reason": None}
    row = coverage_row_from_decision_window(unknown_ground_truth)
    assert row.correct is None  # never inferred without real ground truth


def test_coverage_row_from_decision_window_insufficient_evidence_is_abstained_not_unknown():
    row = coverage_row_from_decision_window({
        "final_decision": "INSUFFICIENT_EVIDENCE", "predicted_class": None, "physical_unit_id": "UNIT-A",
        "abstention_reason": "BELOW_MINIMUM_ELIGIBLE_BURSTS:1<2",
    })
    assert row.decided is False
    assert row.correct is None
    assert row.abstention_reason == "BELOW_MINIMUM_ELIGIBLE_BURSTS:1<2"


def test_coverage_row_from_decision_window_unknown_decision_counts_as_decided():
    """UNKNOWN is a real classification decision (below acceptance
    threshold), never treated as abstention -- matches the existing
    coverage() convention in run_confirmatory_statistical_plan."""
    row = coverage_row_from_decision_window({"final_decision": "UNKNOWN", "predicted_class": None, "physical_unit_id": "UNIT-A", "abstention_reason": None})
    assert row.decided is True
    assert row.correct is False  # UNKNOWN never matches a real target unit


def test_compute_coverage_summary_overall_and_by_dimension():
    rows = [
        CoverageRow(decided=True, correct=True, evaluation_domain="VALIDATION", branch="raw_iq", physical_unit_id="UNIT-A"),
        CoverageRow(decided=True, correct=False, evaluation_domain="VALIDATION", branch="raw_iq", physical_unit_id="UNIT-A"),
        CoverageRow(decided=False, correct=None, evaluation_domain="VALIDATION", branch="raw_iq", physical_unit_id="UNIT-A", abstention_reason="BELOW_MINIMUM_ELIGIBLE_BURSTS:1<2"),
        CoverageRow(decided=True, correct=True, evaluation_domain="TEST", branch="stft", physical_unit_id="UNIT-B"),
    ]
    summary = compute_coverage_summary(rows)

    assert summary["overall"]["eligible_windows"] == 4
    assert summary["overall"]["decided_windows"] == 3
    assert summary["overall"]["abstained_windows"] == 1
    assert summary["overall"]["coverage"] == pytest.approx(0.75)
    assert summary["overall"]["errors_among_decided"] == 1
    assert summary["overall"]["risk_among_decided"] == pytest.approx(1 / 3)

    assert summary["by_evaluation_domain"]["VALIDATION"]["eligible_windows"] == 3
    assert summary["by_evaluation_domain"]["TEST"]["eligible_windows"] == 1
    assert summary["by_branch"]["raw_iq"]["decided_windows"] == 2
    assert summary["by_physical_unit"]["UNIT-A"]["abstained_windows"] == 1
    assert summary["abstention_reason_counts"] == {"BELOW_MINIMUM_ELIGIBLE_BURSTS:1<2": 1}


def test_compute_coverage_summary_reports_not_available_when_no_reason_was_ever_recorded():
    rows = [CoverageRow(decided=False, correct=None, abstention_reason=None)]
    summary = compute_coverage_summary(rows)
    assert summary["abstention_reason_counts"] == "NOT_AVAILABLE"


def test_compute_coverage_summary_never_fabricates_a_bucket_for_an_absent_dimension():
    rows = [CoverageRow(decided=True, correct=True)]  # no domain/branch/unit supplied
    summary = compute_coverage_summary(rows)
    assert summary["by_evaluation_domain"] == {}
    assert summary["by_branch"] == {}
    assert summary["by_physical_unit"] == {}
    assert summary["overall"]["eligible_windows"] == 1


def test_compute_coverage_summary_returns_none_bucket_for_empty_rows():
    assert compute_coverage_summary([])["overall"] is None
