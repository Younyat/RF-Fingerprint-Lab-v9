"""Capture Stage against the real, already-completed BLE-IQ-e8edc49b59a0
capture (the same one Fase 1/Fase 2 of the BLE Offline Replay / Packet
Analysis Lab work verified end-to-end). No synthetic fixtures here -- if this
capture's real capture_manifest.json ever changes shape, this test is
supposed to fail loudly rather than keep passing against a mock.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.ble_rffi_studio.acquisition.capture_stage import CaptureStage, ExecutionIdRequiredError

STORAGE_ROOT = Path(__file__).resolve().parents[3] / "infrastructure" / "persistence" / "storage"
CAPTURE_ROOT = STORAGE_ROOT / "ble" / "iq_captures"
REAL_CAPTURE_ID = "BLE-IQ-e8edc49b59a0"

pytestmark = pytest.mark.skipif(not (CAPTURE_ROOT / REAL_CAPTURE_ID).is_dir(), reason="real capture fixture not present in this environment")


@pytest.fixture
def stage():
    return CaptureStage(CAPTURE_ROOT)


def test_build_capture_record_from_real_capture(stage):
    capture = stage.build_capture_record(capture_id=REAL_CAPTURE_ID, project_id="BLE-RFFI-CC2650", campaign_id="CC2650-CAMPAIGN-01")

    assert capture.capture_id == REAL_CAPTURE_ID
    assert capture.session_id == "S001-POS"
    assert capture.execution_id == "BLE-HYBRID-20260724T121557Z-ea66fb"
    assert capture.physical_unit_id is None  # never populated at capture time, only via Evidence Stage
    assert capture.sample_rate_sps == 4_000_000
    assert capture.center_frequency_hz == 2_402_000_000
    assert capture.sample_count == 40_000_000
    assert capture.channel_count == 1
    assert capture.iq_sha256 == "751d880979196d709e9f03bcd30afc79d03be34ca747b383b672551df1473874"
    assert capture.sdr_serial == "E3R04Z1B2"
    assert capture.acquisition_quality == "PASSED"
    assert capture.discontinuities == 0
    assert capture.replay_status == "FULLY_PROCESSED"
    assert capture.software_commit == "6058f3cd73b9310e2cdd8e30e5074834943a5208"


def test_capture_record_round_trips_through_canonical_json(stage):
    capture = stage.build_capture_record(capture_id=REAL_CAPTURE_ID, project_id="BLE-RFFI-CC2650", campaign_id="CC2650-CAMPAIGN-01")
    from app.modules.ble_rffi_studio.contracts import CaptureRecord
    import json
    restored = CaptureRecord.model_validate(json.loads(capture.canonical_json()))
    assert restored == capture


def test_explicit_execution_id_overrides_inference(stage):
    capture = stage.build_capture_record(capture_id=REAL_CAPTURE_ID, project_id="P1", campaign_id="C1", execution_id="EXPLICIT-OVERRIDE")
    assert capture.execution_id == "EXPLICIT-OVERRIDE"


def test_missing_execution_id_and_no_replay_raises(tmp_path):
    # A capture directory with a manifest but no offline_replays/ at all, and
    # no explicit execution_id supplied -- must fail loudly, not fabricate one.
    capture_dir = tmp_path / "captures" / "BLE-IQ-FAKE"
    capture_dir.mkdir(parents=True)
    (capture_dir / "capture_manifest.json").write_text(
        '{"capture_id":"BLE-IQ-FAKE","experimental_metadata":{"session_id":"S999"},'
        '"sample_rate_sps":4000000,"sample_format":"cf32_le","sample_count":1,"center_frequency_hz":1,'
        '"bandwidth_hz":1,"bytes_per_cpu_sample":8,"actual_duration_seconds":1.0,"data_path":"x.sigmf-data",'
        '"actual_file_size_bytes":1,"file_size":1,"data_sha256":"abc","created_at_utc":"2026-01-01T00:00:00Z",'
        '"diagnostic_status":"PASSED","continuity_status":"PASSED","hash_status":"VERIFIED","capture_complete":true}',
        encoding="utf-8",
    )
    stage = CaptureStage(tmp_path / "captures")
    with pytest.raises(ExecutionIdRequiredError):
        stage.build_capture_record(capture_id="BLE-IQ-FAKE", project_id="P1", campaign_id="C1")
