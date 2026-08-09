"""Protocol-freeze close-out (2026-08-09): run_campaign_qualification_preflight
is a real, callable, persisted READY/NOT_READY check -- distinct from
run_preflight() (dataset/split structural checks). Never fabricates an item
it has no real input for (NOT_CHECKED instead), and never opens FUTURE TEST.
"""
from __future__ import annotations

import json

from app.modules.ble_scientific_results.api.scientific_results_repository import ScientificResultsRepository


def _repo(tmp_path):
    return ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")


def test_with_no_inputs_everything_not_checked_or_the_real_default_and_report_is_not_ready(tmp_path):
    repo = _repo(tmp_path)
    report = repo.run_campaign_qualification_preflight()
    assert report["items"]["b200_detected"]["status"] == "NOT_CHECKED"
    # find_frozen_association_policy() is real and, with no calibration data
    # on disk, honestly reports NO_ACCEPTED_POLICY_YET -- which is blocking.
    assert report["items"]["association_policy_state"]["status"] == "NO_ACCEPTED_POLICY_YET"
    assert report["overall_status"] == "NOT_READY"
    assert "association_policy_state: NO_ACCEPTED_POLICY_YET" in report["reasons"]


def test_persists_a_real_artifact(tmp_path):
    repo = _repo(tmp_path)
    repo.run_campaign_qualification_preflight()
    path = tmp_path / "sci_results" / "campaign_qualification_preflight_report.json"
    assert path.is_file()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["overall_status"] == "NOT_READY"


def test_b200_not_detected_is_reported_not_ready(tmp_path):
    repo = _repo(tmp_path)
    report = repo.run_campaign_qualification_preflight(b200_detected=False)
    assert report["items"]["b200_detected"]["status"] == "NOT_READY"
    assert report["overall_status"] == "NOT_READY"


def test_rq4_device_eligibility_reflects_real_counts(tmp_path):
    repo = _repo(tmp_path)
    report = repo.run_campaign_qualification_preflight(rq4_eligible_device_count=0, rq4_total_device_count=5)
    assert report["items"]["rq4_device_eligibility"]["status"] == "NOT_READY"
    assert "0/5" in report["items"]["rq4_device_eligibility"]["detail"]


def test_future_test_access_already_logged_blocks_readiness(tmp_path):
    repo = _repo(tmp_path)
    repo.log_holdout_access(
        actor="op1", process="pytest", access_type="READ_GROUP", access_path="holdout_groups/DS1/1.0.0/FUTURE_TEST",
        resource_id="DS1__1.0.0__FUTURE_TEST", resource_hash=None, reason="test", paper_run_id=None, analysis_contract_hash=None,
    )
    report = repo.run_campaign_qualification_preflight()
    assert report["items"]["protected_holdout_untouched"]["status"] == "NOT_READY"


def test_never_calls_read_group_itself(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    called = []
    monkeypatch.setattr(repo, "read_group", lambda *a, **k: called.append(1))
    repo.run_campaign_qualification_preflight()
    assert called == []
