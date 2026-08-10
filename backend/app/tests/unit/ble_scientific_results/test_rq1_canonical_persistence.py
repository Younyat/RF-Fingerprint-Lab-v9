"""Protocol-freeze close-out, point 4 (2026-08-10):
persist_rq1_acquisition_dependence_report is the ONLY place that writes
evaluate_rq1_acquisition_dependence()'s in-memory numbers to a canonical,
disk-persisted artifact, and only ever with real, caller-supplied linking
metadata (protocol_version, contract_sha256, git_sha, bundle/split ids and
hashes, source evaluation domains) -- it invents nothing.
"""
from __future__ import annotations

import json

from app.modules.ble_rffi_studio.evaluation import Evaluator, evaluate_rq1_acquisition_dependence
from app.modules.ble_scientific_results.api.scientific_results_repository import ScientificResultsRepository


def _repo(tmp_path):
    return ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")


def _real_rq1_report():
    evaluator = Evaluator()
    known_classes = ["A", "B"]
    predictions = [
        {"example_id": "c0", "true_label": "A", "predicted_label": "A"},
        {"example_id": "c1", "true_label": "A", "predicted_label": "A"},
        {"example_id": "b0", "true_label": "B", "predicted_label": "B"},
    ]
    same = evaluator.evaluate_split("VALIDATION", predictions, known_classes)
    return evaluate_rq1_acquisition_dependence(scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", window_report=same, capture_report=same)


def test_persists_a_real_canonical_artifact_with_every_required_linking_field(tmp_path):
    repo = _repo(tmp_path)
    rq1_report = _real_rq1_report()

    artifact = repo.persist_rq1_acquisition_dependence_report(
        paper_run_id="RUN-RQ1-1", protocol_id="PROTO-1", protocol_version=1, contract_sha256="real-contract-hash",
        rq1_report=rq1_report, model_bundle_id="BUNDLE-1", model_bundle_sha256="bundle-hash",
        confirmatory_split_manifest_id="SPLIT-CONF-1", confirmatory_split_manifest_sha256="split-conf-hash",
        diagnostic_split_manifest_id="SPLIT-DIAG-1", diagnostic_split_manifest_sha256="split-diag-hash",
        source_evaluation_domains={"window": "same-capture", "capture": "capture-disjoint"},
        uncertainty_ci={"ci_low": 0.5, "ci_high": 0.9}, coverage=0.95,
    )

    for required_field in (
        "protocol_id", "protocol_version", "contract_sha256", "git_sha", "model_bundle_id", "model_bundle_sha256",
        "confirmatory_split_manifest_id", "confirmatory_split_manifest_sha256",
        "diagnostic_split_manifest_id", "diagnostic_split_manifest_sha256",
        "source_evaluation_domains", "ba_window", "ba_capture", "ba_future", "delta_dependence", "delta_future",
        "uncertainty_ci", "coverage", "generated_at",
    ):
        assert required_field in artifact, required_field

    assert artifact["protocol_id"] == "PROTO-1"
    assert artifact["contract_sha256"] == "real-contract-hash"
    assert artifact["ba_window"] == rq1_report.ba_window
    assert artifact["delta_dependence"] == rq1_report.delta_dependence


def test_persisted_artifact_round_trips_from_disk(tmp_path):
    repo = _repo(tmp_path)
    rq1_report = _real_rq1_report()
    repo.persist_rq1_acquisition_dependence_report(
        paper_run_id="RUN-RQ1-2", protocol_id="PROTO-1", protocol_version=1, contract_sha256="real-contract-hash",
        rq1_report=rq1_report, model_bundle_id="BUNDLE-1", model_bundle_sha256="bundle-hash",
        confirmatory_split_manifest_id="SPLIT-CONF-1", confirmatory_split_manifest_sha256="split-conf-hash",
        diagnostic_split_manifest_id="SPLIT-DIAG-1", diagnostic_split_manifest_sha256="split-diag-hash",
        source_evaluation_domains={},
    )
    path = tmp_path / "sci_results" / "RUN-RQ1-2" / "06_statistics" / "rq1_acquisition_dependence_report.json"
    assert path.is_file()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["model_bundle_id"] == "BUNDLE-1"

    reloaded = repo.get_rq1_acquisition_dependence_report("RUN-RQ1-2")
    assert reloaded == on_disk
    assert repo.get_rq1_acquisition_dependence_report("RUN-NEVER-RAN") is None


def test_uncertainty_and_coverage_stay_none_when_not_supplied_never_fabricated(tmp_path):
    repo = _repo(tmp_path)
    rq1_report = _real_rq1_report()
    artifact = repo.persist_rq1_acquisition_dependence_report(
        paper_run_id="RUN-RQ1-3", protocol_id="PROTO-1", protocol_version=1, contract_sha256="real-contract-hash",
        rq1_report=rq1_report, model_bundle_id="BUNDLE-1", model_bundle_sha256="bundle-hash",
        confirmatory_split_manifest_id="SPLIT-CONF-1", confirmatory_split_manifest_sha256="split-conf-hash",
        diagnostic_split_manifest_id="SPLIT-DIAG-1", diagnostic_split_manifest_sha256="split-diag-hash",
        source_evaluation_domains={},
    )
    assert artifact["uncertainty_ci"] is None
    assert artifact["coverage"] is None
