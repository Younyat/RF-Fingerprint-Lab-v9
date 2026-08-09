"""Real production caller for run_confirmatory_statistical_plan()
(2026-08-09): ScientificResultsRepository.run_confirmatory_statistical_plan
persists a real artifact under 06_statistics/, not just a value returned
from a unit test.
"""
from __future__ import annotations

import json

from app.modules.ble_scientific_results.api.scientific_results_repository import ScientificResultsRepository


def _repo(tmp_path):
    return ScientificResultsRepository(tmp_path / "scientific_reports", tmp_path / "ble_rffi_studio")


def test_run_confirmatory_statistical_plan_persists_a_real_artifact(tmp_path):
    repo = _repo(tmp_path)
    as_dict = repo.run_confirmatory_statistical_plan(
        "RUN-1", non_inferiority_differences=[0.01, -0.02, 0.0, 0.01, -0.01], non_inferiority_margin=0.1,
    )
    assert as_dict["non_inferiority"]["status"] == "EXECUTED"

    persisted_path = tmp_path / "scientific_reports" / "RUN-1" / "06_statistics" / "confirmatory_statistical_plan_report.json"
    assert persisted_path.is_file()
    on_disk = json.loads(persisted_path.read_text(encoding="utf-8"))
    assert on_disk["non_inferiority"]["status"] == "EXECUTED"
    assert on_disk["rq3_within_device_permutation_test"]["status"] == "SKIPPED_NO_DATA"


def test_get_confirmatory_statistical_plan_report_reads_back_the_persisted_artifact(tmp_path):
    repo = _repo(tmp_path)
    assert repo.get_confirmatory_statistical_plan_report("RUN-2") is None

    repo.run_confirmatory_statistical_plan("RUN-2")
    reloaded = repo.get_confirmatory_statistical_plan_report("RUN-2")
    assert reloaded is not None
    assert reloaded["balanced_accuracy"]["status"] == "SKIPPED_NO_DATA"
