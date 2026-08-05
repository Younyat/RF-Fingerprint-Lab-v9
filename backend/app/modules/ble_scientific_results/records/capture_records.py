"""Fase 2, B.2: ScientificCaptureRecord builder. One row per real
CaptureRecord already frozen in ble_rffi_studio -- every field is either a
direct copy of an existing artifact field or explicitly None +
not_documented_fields. Nothing here recomputes DSP or re-derives anything
Evidence Stage/Dataset Builder/Split Builder already decided.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.modules.ble_rffi_studio.contracts import CaptureRecord, DatasetManifest, ExampleRecord, SplitManifest

from ..contracts import ScientificCaptureRecord
from .iq_resolution import resolve_iq_path, resolve_replay_dir

# Fields the user's specification names that have NO source anywhere in
# ble_rffi_studio's real capture/example/registry schema today (verified
# directly against contracts/capture.py, contracts/physical_unit.py --
# never assumed). Listed once here so every capture record reports the
# same, consistent gap rather than each builder call re-deriving it.
_STRUCTURALLY_ABSENT_CAPTURE_FIELDS = (
    "firmware_hash", "configuration_hash", "receiver_epoch", "host_id", "day_id",
    "capture_order", "pre_or_post", "intervention_arm", "time_since_power_on_s",
    "time_since_intervention_s", "packet_variant", "review_status",
)


def _load_physical_unit_model(ble_root: Path, physical_unit_id: str | None) -> tuple[str | None, str | None]:
    """Returns (device_model, source_manifest_id_or_None). Reads the real
    PhysicalUnitRecord.model field -- honestly None on essentially every
    real unit in this repository today, since no operator workflow
    currently populates it (verified: registry/physical_units/*.json)."""
    if not physical_unit_id:
        return None, None
    path = ble_root / "registry" / "physical_units" / f"{physical_unit_id}.json"
    if not path.is_file():
        return None, None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("model"), physical_unit_id


def _load_source_acquisition_quality(legacy_capture_root: Path, capture_id: str) -> dict[str, Any] | None:
    replay_dir = resolve_replay_dir(legacy_capture_root, capture_id)
    if replay_dir is None:
        return None
    report_path = replay_dir / "replay_final_report.json"
    if not report_path.is_file():
        return None
    return json.loads(report_path.read_text(encoding="utf-8")).get("source_acquisition_quality")


def _capture_split(split: SplitManifest, capture_id: str) -> str | None:
    for assignment in split.assignments:
        if assignment.capture_id == capture_id:
            return assignment.split
    return None


def _label_status(capture: CaptureRecord, examples: list[ExampleRecord]) -> str:
    """Derived, real classification (never a raw artifact field by this
    exact name): RESOLVED_POSITIVE if any example resolved to a
    physical_unit_id, RESOLVED_NEGATIVE for a declared background capture
    with none resolved, UNRESOLVED otherwise -- mirrors the same real
    distinction ble_rffi_studio's own EvidenceStage already draws between
    "no address match" and "operator confirmed absent", just as one
    queryable field."""
    if any(example.physical_unit_id is not None for example in examples):
        return "RESOLVED_POSITIVE"
    if capture.capture_purpose in ("BACKGROUND_TARGET_OFF", "BACKGROUND_GENERAL"):
        return "RESOLVED_NEGATIVE"
    return "UNRESOLVED"


def build_capture_record(
    *, paper_run_id: str, protocol_id: str, campaign_id: str, capture: CaptureRecord, examples: list[ExampleRecord],
    dataset: DatasetManifest, split: SplitManifest, ble_root: Path, legacy_capture_root: Path,
) -> ScientificCaptureRecord:
    not_documented = list(_STRUCTURALLY_ABSENT_CAPTURE_FIELDS)

    device_model, physical_unit_manifest_id = _load_physical_unit_model(ble_root, capture.physical_unit_id)
    quality = _load_source_acquisition_quality(legacy_capture_root, capture.capture_id)
    if quality is None:
        not_documented += ["overflow_count", "discontinuity_count", "short_read_count"]

    iq_path = resolve_iq_path(legacy_capture_root, capture)
    metadata_path = ble_root / "captures" / f"{capture.capture_id}.json"
    metadata_bytes = metadata_path.read_bytes() if metadata_path.is_file() else None

    # Simple arithmetic identity from the capture's own declared
    # configuration (duration x sample rate), not an inference -- lets
    # campaign accounting flag SAMPLE_COUNT_MISMATCH by comparing this
    # against observed_samples (capture.sample_count).
    expected_samples = round(capture.capture_duration_s * capture.sample_rate_sps) if capture.capture_duration_s and capture.sample_rate_sps else None

    # No per-capture aggregate SNR/noise/signal-power/occupied-bandwidth/
    # CFO field exists anywhere in ble_rffi_studio today -- mean_power_dbfs/
    # peak_power_dbfs exist only per-candidate (candidate_manifest.jsonl),
    # and aggregating them into one capture-level number is a Section E
    # descriptive-summary computation, not a raw canonical value.
    not_documented += ["clipping_fraction", "near_zero_fraction", "noise_power_dbfs", "signal_power_dbfs", "snr_db", "occupied_bandwidth_hz", "frequency_offset_hz", "writer_backlog_count"]

    eligible = capture.acquisition_quality == "PASSED" and bool(examples)
    exclusion_reasons: list[str] = []
    if capture.acquisition_quality != "PASSED":
        exclusion_reasons.append(f"CAPTURE_QUALITY_{capture.acquisition_quality}")
    if not examples:
        exclusion_reasons.append("NO_EVIDENCE_EXAMPLES")

    source_manifest_ids = [capture.capture_id]
    if physical_unit_manifest_id:
        source_manifest_ids.append(physical_unit_manifest_id)

    return ScientificCaptureRecord(
        paper_run_id=paper_run_id, protocol_id=protocol_id, campaign_id=campaign_id, capture_id=capture.capture_id,
        physical_unit_id=capture.physical_unit_id, device_model=device_model, source_population=capture.capture_purpose,
        channel=examples[0].channel if examples else None, center_frequency_hz=capture.center_frequency_hz,
        sample_rate_hz=capture.sample_rate_sps, bandwidth_hz=capture.effective_bandwidth_hz, sample_format=capture.sample_dtype,
        gain_db=capture.gain_db, antenna=capture.antenna_port, receiver_id=capture.receiver_device_id,
        capture_start_utc=capture.created_at, duration_s=capture.capture_duration_s,
        expected_samples=expected_samples, observed_samples=capture.sample_count,
        overflow_count=(quality or {}).get("overflow_count"), discontinuity_count=(quality or {}).get("discontinuity_count"),
        short_read_count=(quality or {}).get("short_read_count"), writer_backlog_count=None,
        clipping_fraction=None, near_zero_fraction=None, noise_power_dbfs=None, signal_power_dbfs=None, snr_db=None,
        occupied_bandwidth_hz=None, frequency_offset_hz=None, capture_quality=capture.acquisition_quality,
        label_status=_label_status(capture, examples), review_status=None, experimental_role=capture.capture_purpose,
        split=_capture_split(split, capture.capture_id),
        source_iq_resolved_path=str(iq_path), source_iq_size_bytes=capture.iq_size_bytes, source_iq_sha256=capture.iq_sha256,
        metadata_path=str(metadata_path) if metadata_path.is_file() else None,
        metadata_sha256=hashlib.sha256(metadata_bytes).hexdigest() if metadata_bytes else None,
        eligible=eligible, exclusion_reason_codes=exclusion_reasons, source_manifest_ids=source_manifest_ids,
        not_documented_fields=sorted(set(not_documented)),
    )
