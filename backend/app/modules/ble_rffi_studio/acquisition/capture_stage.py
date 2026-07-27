"""Builds a Studio CaptureRecord from an already-completed legacy BLE IQ
capture directory (capture_manifest.json + siblings).

This reads the existing, validated capture tree written by
ble_sdr_capture_worker.py / BleIqCaptureService -- it never re-captures, never
writes into that legacy tree, and never trusts the legacy pipeline's own
scientific verdicts (e.g. `dataset_eligible`, `scientific_corpus_membership`).
Those belonged to the old, incompatible Dataset Studio vocabulary. Only raw,
objectively-observed acquisition facts (sample format, hashes, timestamps,
continuity counters) cross into the new contract; every eligibility/quality
decision the new module cares about is recomputed fresh in later stages.

project_id/campaign_id are NEW-module concepts the legacy capture has no
field for, so the caller always supplies them explicitly.
"""
from __future__ import annotations

from pathlib import Path

from app.infrastructure.ble.capture.ble_offline_replay import read_json

from ..contracts import CapturePurpose, CaptureRecord, DatasetRole, TargetState

_LE_SUFFIX = "_le"


class CaptureNotFoundError(Exception):
    pass


class ExecutionIdRequiredError(Exception):
    pass


class CaptureStage:
    def __init__(self, legacy_capture_root: Path) -> None:
        self.legacy_capture_root = legacy_capture_root

    def build_capture_record(
        self,
        *,
        capture_id: str,
        project_id: str,
        campaign_id: str,
        execution_id: str | None = None,
        session_id: str | None = None,
        isolation_declared_physical_unit_id: str | None = None,
        capture_purpose: CapturePurpose | None = None,
        target_state: TargetState | None = None,
        target_reference_id: str | None = None,
        dataset_role: DatasetRole | None = None,
    ) -> CaptureRecord:
        capture_dir = self.legacy_capture_root / capture_id
        manifest_path = capture_dir / "capture_manifest.json"
        if not manifest_path.is_file():
            raise CaptureNotFoundError(f"CAPTURE_MANIFEST_NOT_FOUND:{capture_id}")
        manifest = read_json(manifest_path)

        resolved_execution_id = execution_id or self._infer_execution_id(capture_dir)
        if not resolved_execution_id:
            raise ExecutionIdRequiredError(
                f"EXECUTION_ID_NOT_RECORDED_ON_THE_RAW_CAPTURE_AND_NO_REPLAY_TO_INFER_IT_FROM:{capture_id}. "
                "Pass execution_id explicitly (it identifies which hybrid acquisition session produced this capture)."
            )

        experimental = manifest.get("experimental_metadata") or {}
        resolved_session_id = session_id or experimental.get("session_id") or manifest.get("session_id")
        if not resolved_session_id:
            raise ValueError(
                f"SESSION_ID_MISSING_ON_CAPTURE:{capture_id}. Pass session_id explicitly "
                "(e.g. the hybrid acquisition session_id) when the raw capture never recorded one."
            )

        sample_format = str(manifest.get("sample_format") or manifest.get("cpu_format") or "")
        gain = manifest.get("gain_configuration") or {}
        bandwidth_hz = int(manifest["bandwidth_hz"])
        bytes_per_cpu_sample = int(manifest.get("bytes_per_cpu_sample") or 0)
        # cf32 == 2 x float32 == 8 bytes per complex sample per channel; more
        # bytes per sample than that would mean more than one interleaved
        # channel, which this capture pipeline has never produced.
        channel_count = 1 if bytes_per_cpu_sample <= 8 else bytes_per_cpu_sample // 8

        return CaptureRecord(
            project_id=project_id,
            campaign_id=campaign_id,
            capture_id=capture_id,
            session_id=resolved_session_id,
            execution_id=resolved_execution_id,
            # CaptureStage only ever reads a real legacy B200 capture tree
            # (capture_manifest.json etc. written by ble_sdr_capture_worker.py)
            # -- the synthetic generator never goes through this class.
            data_origin="REAL_B200",
            # physical_unit_id stays null here by design (see contract docstring)
            # -- only Evidence Stage resolves it, via a real AddressBinding.
            isolation_declared_physical_unit_id=isolation_declared_physical_unit_id,
            capture_purpose=capture_purpose,
            target_state=target_state,
            target_reference_id=target_reference_id,
            dataset_role=dataset_role,
            receiver_device_id=str(manifest.get("device_id") or self._device_id_from_request(capture_dir) or manifest.get("device_serial") or ""),
            sdr_model=str(manifest.get("hardware") or ""),
            sdr_serial=manifest.get("device_serial"),
            rx_channel=str(manifest.get("antenna") or ""),
            antenna_port=str(manifest.get("antenna") or ""),
            sample_rate_sps=int(manifest["sample_rate_sps"]),
            sample_dtype=sample_format,
            byte_order="little_endian" if sample_format.endswith(_LE_SUFFIX) else "unknown",
            sample_count=int(manifest["sample_count"]),
            channel_count=channel_count,
            center_frequency_hz=int(manifest["center_frequency_hz"]),
            frontend_bandwidth_hz=bandwidth_hz,
            # No distinct "effective" (post-filtering) bandwidth is recorded
            # anywhere upstream for this capture pipeline; mirror the
            # frontend value rather than inventing a different number.
            effective_bandwidth_hz=bandwidth_hz,
            gain_db=float(gain.get("gain_db", manifest.get("gain_db", 0.0))),
            gain_mode=str(gain.get("mode") or "unknown"),
            clock_source=None,  # not recorded upstream
            time_source=None,  # not recorded upstream
            capture_duration_s=float(manifest.get("actual_duration_seconds") or manifest.get("effective_duration_seconds") or 0.0),
            capture_tool=str(manifest.get("capture_software_revision") or manifest.get("capture_software_version") or ""),
            capture_tool_version=None,
            software_commit=(experimental.get("execution_freeze") or {}).get("repository_commit"),
            iq_path=str(manifest["data_path"]),
            iq_size_bytes=int(manifest.get("actual_file_size_bytes") or manifest["file_size"]),
            iq_sha256=str(manifest["data_sha256"]),
            acquisition_quality=self._acquisition_quality(manifest),
            discontinuities=int(manifest.get("discontinuity_count") or 0),
            replay_status=self._infer_replay_status(capture_dir),
            created_at=str(manifest["created_at_utc"]),
        )

    def _device_id_from_request(self, capture_dir: Path) -> str | None:
        request_path = capture_dir / "request.json"
        if not request_path.is_file():
            return None
        return read_json(request_path).get("device_id")

    def _acquisition_quality(self, manifest: dict) -> str:
        if manifest.get("capture_complete") is False:
            return "INCOMPLETE"
        ok = (
            manifest.get("diagnostic_status") == "PASSED"
            and manifest.get("continuity_status") == "PASSED"
            and manifest.get("hash_status") == "VERIFIED"
        )
        return "PASSED" if ok else "FAILED"

    def _infer_execution_id(self, capture_dir: Path) -> str | None:
        for replay_manifest_path in sorted(capture_dir.glob("offline_replays/*/replay_manifest.json")):
            execution_id = read_json(replay_manifest_path).get("execution_id")
            if execution_id:
                return execution_id
        return None

    def _infer_replay_status(self, capture_dir: Path) -> str:
        reports = sorted(capture_dir.glob("offline_replays/*/replay_final_report.json"))
        if not reports:
            return "NOT_STARTED"
        report = read_json(reports[-1])
        if report.get("exit_status") == "FULLY_PROCESSED":
            return "FULLY_PROCESSED"
        if report.get("failed_decoder_error_segments") or report.get("failed_timeout_segments"):
            return "COMPLETED_WITH_FAILED_SEGMENTS"
        return "PARTIAL"
