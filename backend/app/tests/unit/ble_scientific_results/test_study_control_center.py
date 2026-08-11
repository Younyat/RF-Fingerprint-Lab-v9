"""Study Control Center, Phase 1 (2026-08-11): get_study_control_center_status()
computes no science -- only real gating logic over already-real getters. These
tests prove the dependency-gated BLOCKED/READY/COMPLETE state machine against
an empty repository and against a repository with real qualification data.
"""
from __future__ import annotations

import json

from app.modules.ble_scientific_results.api.scientific_results_repository import ScientificResultsRepository


def _repo(tmp_path):
    return ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")


def _phase(status, phase_id):
    return next(p for p in status["phases"] if p["phase_id"] == phase_id)


def test_empty_repository_phase_01_is_ready_and_everything_downstream_is_blocked(tmp_path):
    repo = _repo(tmp_path)
    status = repo.get_study_control_center_status()
    assert len(status["phases"]) == 17
    assert _phase(status, "01")["state"] == "READY"
    assert _phase(status, "01")["blocking_reasons"] == []
    for phase_id in ("02", "03", "04", "17"):
        phase = _phase(status, phase_id)
        assert phase["state"] == "BLOCKED"
        assert phase["blocking_reasons"]


def test_phase_01_completes_when_qualification_report_is_ready(tmp_path):
    repo = _repo(tmp_path)
    (repo.root / "campaign_qualification_preflight_report.json").write_text(
        json.dumps({"overall_status": "READY", "items": {}}), encoding="utf-8",
    )
    status = repo.get_study_control_center_status()
    phase01 = _phase(status, "01")
    assert phase01["state"] == "COMPLETE"
    assert phase01["real_data_available"] is True
    # Phase 02 depends only on phase 01 -- now unblocked (though it will be
    # BLOCKED again itself if no physical units are registered -- that's
    # phase 02's OWN prerequisite check, not phase 01's).
    phase02 = _phase(status, "02")
    assert "Hardware Qualification" not in phase02["blocking_reasons"]


def test_phase_01_preliminary_when_qualification_report_is_preliminary(tmp_path):
    repo = _repo(tmp_path)
    (repo.root / "campaign_qualification_preflight_report.json").write_text(
        json.dumps({"overall_status": "PRELIMINARY", "items": {}}), encoding="utf-8",
    )
    status = repo.get_study_control_center_status()
    assert _phase(status, "01")["state"] == "PRELIMINARY"


def test_phase_01_blocked_when_qualification_report_is_not_ready(tmp_path):
    repo = _repo(tmp_path)
    (repo.root / "campaign_qualification_preflight_report.json").write_text(
        json.dumps({"overall_status": "NOT_READY", "items": {}}), encoding="utf-8",
    )
    status = repo.get_study_control_center_status()
    assert _phase(status, "01")["state"] == "BLOCKED"


def test_every_phase_reports_git_sha_and_protocol_version(tmp_path):
    repo = _repo(tmp_path)
    status = repo.get_study_control_center_status()
    for phase in status["phases"]:
        assert phase["git_sha"]
        assert "protocol_version" in phase
