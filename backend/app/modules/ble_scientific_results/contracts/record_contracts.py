"""Fase 2, Section B: the four canonical scientific record types. Each is a
read-only, 1:1 mapping from a real ble_rffi_studio/replay artifact field to
a named column here -- never a computed/inferred value dressed up as a raw
observation. A field with no real source is `None`, and its name is added
to `not_documented_fields` on that record -- never silently defaulted to 0,
"", or an inferred guess. See `records/` for the builders that populate
these from real artifacts, and each field's builder-side comment for its
exact source.

No `E0`-`E6` literal appears anywhere in this file: `ScientificBurstRecord.
burst_class` uses its own, unrelated vocabulary (RF_ACTIVITY /
BLE_SYNC_CANDIDATE / CRC_VALID_PACKET / TARGET_ASSOCIATED_PACKET).
"""
from __future__ import annotations

from typing import Literal

from .common import StudioContract

RECORD_SCHEMA_VERSION = "ble-scientific-results-records-v1"

BurstClass = Literal["RF_ACTIVITY", "BLE_SYNC_CANDIDATE", "CRC_VALID_PACKET", "TARGET_ASSOCIATED_PACKET"]


class ScientificCaptureRecord(StudioContract):
    schema_version: str = RECORD_SCHEMA_VERSION

    paper_run_id: str
    protocol_id: str
    campaign_id: str
    capture_id: str

    physical_unit_id: str | None = None
    device_model: str | None = None
    firmware_hash: str | None = None
    configuration_hash: str | None = None
    source_population: str | None = None

    channel: int | None = None
    center_frequency_hz: int | None = None
    sample_rate_hz: int | None = None
    bandwidth_hz: int | None = None
    sample_format: str | None = None
    gain_db: float | None = None
    antenna: str | None = None
    receiver_id: str | None = None
    receiver_epoch: str | None = None
    host_id: str | None = None

    day_id: str | None = None
    session_id: str | None = None
    capture_order: int | None = None
    pre_or_post: str | None = None
    intervention_arm: str | None = None
    time_since_power_on_s: float | None = None
    time_since_intervention_s: float | None = None
    packet_variant: str | None = None

    capture_start_utc: str | None = None
    duration_s: float | None = None
    expected_samples: int | None = None
    observed_samples: int | None = None
    overflow_count: int | None = None
    discontinuity_count: int | None = None
    short_read_count: int | None = None
    writer_backlog_count: int | None = None

    clipping_fraction: float | None = None
    near_zero_fraction: float | None = None
    noise_power_dbfs: float | None = None
    signal_power_dbfs: float | None = None
    snr_db: float | None = None
    occupied_bandwidth_hz: float | None = None
    frequency_offset_hz: float | None = None
    capture_quality: str | None = None

    label_status: str | None = None
    review_status: str | None = None
    experimental_role: str | None = None
    split: str | None = None

    source_iq_resolved_path: str | None = None
    source_iq_size_bytes: int | None = None
    source_iq_sha256: str | None = None
    metadata_path: str | None = None
    metadata_sha256: str | None = None

    eligible: bool | None = None
    exclusion_reason_codes: list[str] = []
    source_manifest_ids: list[str] = []
    not_documented_fields: list[str] = []


class ScientificBurstRecord(StudioContract):
    schema_version: str = RECORD_SCHEMA_VERSION

    burst_id: str
    capture_id: str
    burst_class: BurstClass

    sample_start: int
    sample_end: int
    burst_start_utc_estimate: str | None = None
    decision_window_id: str
    candidate_group_id: str | None = None
    detector_version: str | None = None

    synchronization_status: str | None = None
    synchronization_score: float | None = None
    symbol_phase: float | None = None
    frequency_offset_hz: float | None = None
    frequency_fit_quality: float | None = None

    crc_status: str | None = None
    decoded_pdu_type: str | None = None
    decoded_adva: str | None = None
    decoded_payload_hash: str | None = None

    native_event_id: str | None = None
    association_status: str | None = None
    association_time_residual_ms: float | None = None
    association_cost: float | None = None
    association_policy_hash: str | None = None

    competing_energy: float | None = None
    clipping_overlap: float | None = None
    discontinuity_overlap: float | None = None
    edge_margin_samples: int | None = None
    burst_snr_db: float | None = None
    burst_quality: str | None = None
    label_authority: str | None = None

    eligible: bool | None = None
    exclusion_reason_codes: list[str] = []
    source_artifact_ids: list[str] = []
    not_documented_fields: list[str] = []


class ScientificDecisionWindowRecord(StudioContract):
    schema_version: str = RECORD_SCHEMA_VERSION

    decision_window_id: str
    capture_id: str
    window_index: int

    window_start_sample: int
    window_end_sample: int
    window_start_utc: str | None = None
    window_end_utc: str | None = None

    active: bool
    candidate_burst_count: int
    crc_valid_burst_count: int
    target_associated_burst_count: int
    eligible_burst_count: int
    selected_burst_ids: list[str] = []
    selection_policy_hash: str | None = None
    minimum_required_bursts: int | None = None

    decision_eligible: bool
    ineligibility_reason_codes: list[str] = []
    not_documented_fields: list[str] = []


class ScientificCampaignDeviationRecord(StudioContract):
    schema_version: str = RECORD_SCHEMA_VERSION

    deviation_id: str
    paper_run_id: str
    campaign_id: str

    affected_object_type: str
    affected_object_id: str
    day_id: str | None = None
    session_id: str | None = None

    deviation_type: str
    description: str
    detected_stage: str
    detected_before_outcome_access: bool
    severity: str
    blocking: bool
    protocol_rule: str | None = None

    observed_value: str | None = None
    expected_value: str | None = None
    action: str
    scientific_impact: str

    source_artifact_ids: list[str] = []


class RecordBuildResult(StudioContract):
    schema_version: str = RECORD_SCHEMA_VERSION
    paper_run_id: str
    generated_at: str
    capture_record_count: int
    burst_record_count: int
    decision_window_record_count: int
    campaign_deviation_count: int
    captures_without_replay: list[str] = []
