"""Orchestration-level tests for the two Guided Validation hardware
actions, using a STUB CampaignOrchestrator (same pattern as
ble_rffi_studio/test_paper_campaign_runner.py's _StubOrchestrator) -- never
touches real hardware. Verifies run_timing_diagnostic/
run_target_absence_control correctly wire run_session()'s real return
shape into association reconstruction + classification + persistence."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.ble_scientific_results.api import ScientificResultsRepository
from app.modules.ble_scientific_results.guided_validation import GuidedBleScientificValidationService
from app.modules.ble_scientific_results.guided_validation.service import HardwareActionError

from ._helpers import make_candidate, make_ledger_row, write_replay_artifacts


class _StubOrchestrator:
    def __init__(self, session_result: dict | None = None, raise_error: Exception | None = None) -> None:
        self.session_result = session_result
        self.raise_error = raise_error
        self.calls: list[dict] = []

    def run_session(self, **kwargs):
        self.calls.append(kwargs)
        if self.raise_error:
            raise self.raise_error
        return self.session_result


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + ("\n" if rows else ""), encoding="utf-8")


def _register_address_binding(ble_root: Path, *, binding_id: str, unit_id: str, address: str) -> None:
    _write_json(ble_root / "registry" / "address_bindings" / f"{binding_id}.json", {
        "binding_id": binding_id, "project_id": "P", "address": address, "address_type": "public",
        "bound_physical_unit_id": unit_id, "binding_status": "BOUND", "binding_evidence": [],
        "first_seen": "2026-08-06T00:00:00Z", "last_seen": "2026-08-06T00:00:00Z", "history": [],
    })


def _register_physical_unit(ble_root: Path, unit_id: str) -> None:
    _write_json(ble_root / "registry" / "physical_units" / f"{unit_id}.json", {
        "physical_unit_id": unit_id, "project_id": "P", "device_family": "TEST", "status": "ACTIVE",
        "operator_declaration_id": "decl-1", "first_registered_at": "2026-08-06T00:00:00Z",
    })


def _write_capture_manifest(legacy_capture_root: Path, capture_id: str, *, created_at_utc: str) -> None:
    _write_json(legacy_capture_root / capture_id / "capture_manifest.json", {
        "data_sha256": f"sha-{capture_id}", "data_path": f"{capture_id}.cf32", "ble_channel": 37,
        "sample_rate_sps": 4_000_000, "created_at_utc": created_at_utc,
    })


def _new_repository_and_paths(tmp_path: Path):
    ble_root = tmp_path / "ble_rffi_studio"
    legacy_capture_root = ble_root.parent / "ble" / "iq_captures"
    native_scan_root = ble_root.parent / "ble" / "native" / "scans"
    repository = ScientificResultsRepository(tmp_path / "sci_results", ble_root)
    return repository, ble_root, legacy_capture_root, native_scan_root


def test_run_timing_diagnostic_raises_without_a_campaign_orchestrator(tmp_path):
    repository, *_ = _new_repository_and_paths(tmp_path)
    service = GuidedBleScientificValidationService(repository, campaign_orchestrator=None)
    with pytest.raises(HardwareActionError):
        service.run_timing_diagnostic(run_id="RUN-1", physical_unit_id="DEV-1", capture_duration_s=180, channel=37, receiver_profile="default", operator_id="OP-1")


def test_run_timing_diagnostic_raises_for_a_device_with_no_bound_address(tmp_path):
    repository, ble_root, *_ = _new_repository_and_paths(tmp_path)
    service = GuidedBleScientificValidationService(repository, campaign_orchestrator=_StubOrchestrator())
    with pytest.raises(HardwareActionError):
        service.run_timing_diagnostic(run_id="RUN-1", physical_unit_id="UNKNOWN-DEVICE", capture_duration_s=180, channel=37, receiver_profile="default", operator_id="OP-1")


def test_run_timing_diagnostic_classifies_a_clean_capture_as_calibration_possible(tmp_path):
    repository, ble_root, legacy_capture_root, native_scan_root = _new_repository_and_paths(tmp_path)
    _register_physical_unit(ble_root, "DEV-1")
    _register_address_binding(ble_root, binding_id="bind-1", unit_id="DEV-1", address="AA:BB:CC:DD:EE:FF")

    capture_id, session_id = "CAP-DIAG-1", "SESSION-DIAG-1"
    _write_capture_manifest(legacy_capture_root, capture_id, created_at_utc="2026-08-06T00:00:00.000000Z")
    _write_jsonl(native_scan_root / session_id / "advertisements.jsonl", [
        {"address": "AA:BB:CC:DD:EE:FF", "timestamp_callback_utc": "2026-08-06T00:00:00.050000Z"},
    ])
    candidate = make_candidate(index=0, capture_id=capture_id, processing_status="PROCESSED", crc_status="VALID")
    ledger_row = make_ledger_row(candidate_id=candidate["candidate_id"], association_strength="STRONG", time_delta_ms=50.0)
    ledger_row["address_match_status"] = "MATCHED"
    ledger_row["temporal_match_status"] = "MATCHED"
    ledger_row["advertiser_address_canonical"] = "AA:BB:CC:DD:EE:FF"
    write_replay_artifacts(ble_root, capture_id=capture_id, candidates=[candidate], ledger_rows=[ledger_row])

    orchestrator = _StubOrchestrator({"capture_id": capture_id, "session_id": session_id})
    service = GuidedBleScientificValidationService(repository, campaign_orchestrator=orchestrator)

    result = service.run_timing_diagnostic(run_id="RUN-1", physical_unit_id="DEV-1", capture_duration_s=180, channel=37, receiver_profile="default", operator_id="OP-1")

    assert result["diagnosis_code"] == "ASSOCIATION_CALIBRATION_POSSIBLE"
    assert result["narrow_window_valid_count"] == 1
    assert orchestrator.calls[0]["physical_unit_id"] == "DEV-1"
    assert orchestrator.calls[0]["capture_purpose"] == "TARGET_DEVICE_ON"
    assert orchestrator.calls[0]["isolation_declared"] is True

    action_root = repository.root / "guided_validation" / "RUN-1" / "timing_diagnostics"
    action_dirs = list(action_root.iterdir())
    assert len(action_dirs) == 1
    assert (action_dirs[0] / "timing_diagnostic.json").is_file()
    assert (action_dirs[0] / "action_manifest.json").is_file()
    assert (action_dirs[0] / "native_events.jsonl").is_file()


def test_run_timing_diagnostic_detects_no_native_coverage(tmp_path):
    repository, ble_root, legacy_capture_root, native_scan_root = _new_repository_and_paths(tmp_path)
    _register_physical_unit(ble_root, "DEV-1")
    _register_address_binding(ble_root, binding_id="bind-1", unit_id="DEV-1", address="AA:BB:CC:DD:EE:FF")

    capture_id, session_id = "CAP-DIAG-2", "SESSION-DIAG-2"
    _write_capture_manifest(legacy_capture_root, capture_id, created_at_utc="2026-08-06T00:00:00.000000Z")
    # native scan directory never created -> zero events
    orchestrator = _StubOrchestrator({"capture_id": capture_id, "session_id": session_id})
    service = GuidedBleScientificValidationService(repository, campaign_orchestrator=orchestrator)

    result = service.run_timing_diagnostic(run_id="RUN-2", physical_unit_id="DEV-1", capture_duration_s=180, channel=37, receiver_profile="default", operator_id="OP-1")
    assert result["diagnosis_code"] == "NATIVE_SCANNER_NOT_RUNNING"


def test_run_timing_diagnostic_persists_a_failed_action_and_reraises(tmp_path):
    repository, ble_root, *_ = _new_repository_and_paths(tmp_path)
    _register_physical_unit(ble_root, "DEV-1")
    _register_address_binding(ble_root, binding_id="bind-1", unit_id="DEV-1", address="AA:BB:CC:DD:EE:FF")
    orchestrator = _StubOrchestrator(raise_error=RuntimeError("B200_BUSY:held_by=other-process"))
    service = GuidedBleScientificValidationService(repository, campaign_orchestrator=orchestrator)

    with pytest.raises(HardwareActionError):
        service.run_timing_diagnostic(run_id="RUN-3", physical_unit_id="DEV-1", capture_duration_s=180, channel=37, receiver_profile="default", operator_id="OP-1")

    action_root = repository.root / "guided_validation" / "RUN-3" / "timing_diagnostics"
    manifest = json.loads(next(action_root.iterdir()).joinpath("action_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "FAILED"
    assert "B200_BUSY" in manifest["error"]


def test_run_target_absence_control_requires_every_device_confirmed_individually(tmp_path):
    repository, ble_root, *_ = _new_repository_and_paths(tmp_path)
    _register_physical_unit(ble_root, "DEV-1")
    _register_physical_unit(ble_root, "DEV-2")
    orchestrator = _StubOrchestrator()
    service = GuidedBleScientificValidationService(repository, campaign_orchestrator=orchestrator)

    with pytest.raises(HardwareActionError):
        service.run_target_absence_control(run_id="RUN-4", confirmed_devices_off={"DEV-1": True}, capture_duration_s=180, channel=37, operator_id="OP-1")
    assert orchestrator.calls == []  # never attempted the real capture without full confirmation


def test_run_target_absence_control_valid_when_no_enrolled_device_detected(tmp_path):
    repository, ble_root, legacy_capture_root, native_scan_root = _new_repository_and_paths(tmp_path)
    _register_physical_unit(ble_root, "DEV-1")
    _register_address_binding(ble_root, binding_id="bind-1", unit_id="DEV-1", address="AA:BB:CC:DD:EE:FF")

    capture_id, session_id = "CAP-ABSENCE-1", "SESSION-ABSENCE-1"
    _write_capture_manifest(legacy_capture_root, capture_id, created_at_utc="2026-08-06T00:00:00.000000Z")
    _write_jsonl(native_scan_root / session_id / "advertisements.jsonl", [{"address": "11:22:33:44:55:66", "timestamp_callback_utc": "2026-08-06T00:00:00.100000Z"}])
    write_replay_artifacts(ble_root, capture_id=capture_id, candidates=[], ledger_rows=[])

    orchestrator = _StubOrchestrator({"capture_id": capture_id, "session_id": session_id})
    service = GuidedBleScientificValidationService(repository, campaign_orchestrator=orchestrator)

    result = service.run_target_absence_control(run_id="RUN-5", confirmed_devices_off={"DEV-1": True}, capture_duration_s=180, channel=37, operator_id="OP-1")
    assert result["status"] == "VALID"
    assert result["devices_detected"] == []
    assert orchestrator.calls[0]["capture_purpose"] == "BACKGROUND_TARGET_OFF"
    assert orchestrator.calls[0]["operator_confirmed_target_absent"] is True


def test_run_target_absence_control_invalid_when_a_device_is_still_detected(tmp_path):
    repository, ble_root, legacy_capture_root, native_scan_root = _new_repository_and_paths(tmp_path)
    _register_physical_unit(ble_root, "DEV-1")
    _register_address_binding(ble_root, binding_id="bind-1", unit_id="DEV-1", address="AA:BB:CC:DD:EE:FF")

    capture_id, session_id = "CAP-ABSENCE-2", "SESSION-ABSENCE-2"
    _write_capture_manifest(legacy_capture_root, capture_id, created_at_utc="2026-08-06T00:00:00.000000Z")
    _write_jsonl(native_scan_root / session_id / "advertisements.jsonl", [{"address": "AA:BB:CC:DD:EE:FF", "timestamp_callback_utc": "2026-08-06T00:00:00.100000Z"}])
    write_replay_artifacts(ble_root, capture_id=capture_id, candidates=[], ledger_rows=[])

    orchestrator = _StubOrchestrator({"capture_id": capture_id, "session_id": session_id})
    service = GuidedBleScientificValidationService(repository, campaign_orchestrator=orchestrator)

    result = service.run_target_absence_control(run_id="RUN-6", confirmed_devices_off={"DEV-1": True}, capture_duration_s=180, channel=37, operator_id="OP-1")
    assert result["status"] == "TARGET_ABSENCE_CONTROL_INVALID"
    assert result["devices_detected"] == ["DEV-1"]


def test_run_target_absence_control_invalid_with_no_native_coverage(tmp_path):
    repository, ble_root, legacy_capture_root, native_scan_root = _new_repository_and_paths(tmp_path)
    _register_physical_unit(ble_root, "DEV-1")
    capture_id, session_id = "CAP-ABSENCE-3", "SESSION-ABSENCE-3"
    _write_capture_manifest(legacy_capture_root, capture_id, created_at_utc="2026-08-06T00:00:00.000000Z")
    write_replay_artifacts(ble_root, capture_id=capture_id, candidates=[], ledger_rows=[])
    # no advertisements.jsonl written -> no native coverage at all

    orchestrator = _StubOrchestrator({"capture_id": capture_id, "session_id": session_id})
    service = GuidedBleScientificValidationService(repository, campaign_orchestrator=orchestrator)

    result = service.run_target_absence_control(run_id="RUN-7", confirmed_devices_off={"DEV-1": True}, capture_duration_s=180, channel=37, operator_id="OP-1")
    assert result["status"] == "TARGET_ABSENCE_CONTROL_INVALID_NO_NATIVE_COVERAGE"
