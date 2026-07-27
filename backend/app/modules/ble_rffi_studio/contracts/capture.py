from __future__ import annotations

from typing import Literal

from .common import StudioContract

CAPTURE_SCHEMA_VERSION = "ble-rffi-studio-capture-v1"

AcquisitionQuality = Literal["PASSED", "FAILED", "INCOMPLETE"]
ReplayStatus = Literal["NOT_STARTED", "PARTIAL", "FULLY_PROCESSED", "COMPLETED_WITH_FAILED_SEGMENTS"]
# Required, never defaulted: every capture must say plainly whether its IQ
# came off a real USRP B200 or out of the synthetic demo generator. This is
# the field the whole SYNTHETIC_TEST_ONLY / operational-use gate is built on.
DataOrigin = Literal["REAL_B200", "SYNTHETIC_TEST_ONLY"]

# What the operator declared they were doing when they launched this
# session -- the Guided UI's very first question ("Que quieres capturar?").
# None only for captures that predate this field (legacy/manually-built).
CapturePurpose = Literal["TARGET_DEVICE", "BACKGROUND_ENVIRONMENT"]
TargetState = Literal["POWERED_ON", "OPERATOR_DECLARED_POWERED_OFF_OR_REMOVED"]
DatasetRole = Literal["POSITIVE_CANDIDATE", "NEGATIVE_CANDIDATE"]


class CaptureRecord(StudioContract):
    """Describes one B200 IQ acquisition completely enough to reproduce and
    later interpret it -- sample format, count, and receiver configuration
    are not optional extras, they are what makes the IQ file meaningful."""

    schema_version: Literal["ble-rffi-studio-capture-v1"] = CAPTURE_SCHEMA_VERSION

    project_id: str
    campaign_id: str
    capture_id: str
    session_id: str
    execution_id: str
    data_origin: DataOrigin

    physical_unit_id: str | None = None  # null until evidence resolves an AddressBinding

    # Set only when the operator explicitly confirms, at capture time, that
    # this physical unit was the sole nearby transmitter for the whole
    # session -- a real, deliberate declaration, not inferred. Exists
    # because many real BLE devices rotate a resolvable/random advertising
    # address at the radio layer that never matches the "resolved identity"
    # a native OS BLE stack reports, making address-based AddressBinding
    # matching structurally unable to label them (observed directly: 0/4
    # real capture sessions produced an address match, including one where
    # the target was independently confirmed broadcasting seconds earlier).
    # Evidence Stage treats this as WEAKER ground truth than an
    # address+Windows-corroborated STRONG match -- it depends entirely on
    # the physical setup being correct, with no independent cross-check --
    # so it is always recorded and surfaced as PHYSICAL_ISOLATION_DECLARED,
    # never silently merged into address-based association_status values.
    isolation_declared_physical_unit_id: str | None = None

    # "Candidate" only: what the OPERATOR declared this session was for, at
    # launch time, before any evidence exists. A TARGET_DEVICE capture is not
    # yet a confirmed positive -- that still requires Evidence Stage to find
    # eligible examples; a BACKGROUND_ENVIRONMENT capture's whole point is
    # that its target_state is NEVER inferred from the absence of a signal,
    # only from this declaration (see EvidenceStage: a BACKGROUND_ENVIRONMENT
    # capture's examples are never linked as a positive for target_reference_id,
    # even if an address happens to match -- that is a real, honestly
    # surfaced contradiction, not evidence to silently trust).
    capture_purpose: CapturePurpose | None = None
    target_state: TargetState | None = None
    # Documentary only: which physical unit this capture's declared purpose
    # is about -- the unit selected for a TARGET_DEVICE capture, or the unit
    # the operator says was off/removed for a BACKGROUND_ENVIRONMENT capture.
    # Never treated as ground truth for labeling on its own -- see the
    # EvidenceStage note above (a BACKGROUND_ENVIRONMENT capture's examples
    # are never linked as positive for this unit, even on an address match).
    target_reference_id: str | None = None
    dataset_role: DatasetRole | None = None

    receiver_device_id: str
    sdr_model: str
    sdr_serial: str | None = None
    rx_channel: str
    antenna_port: str

    sample_rate_sps: int
    sample_dtype: str
    byte_order: str
    sample_count: int
    channel_count: int

    center_frequency_hz: int
    frontend_bandwidth_hz: int
    effective_bandwidth_hz: int
    gain_db: float
    gain_mode: str
    clock_source: str | None = None
    time_source: str | None = None

    capture_duration_s: float
    capture_tool: str
    capture_tool_version: str | None = None
    software_commit: str | None = None

    iq_path: str
    iq_size_bytes: int
    iq_sha256: str

    acquisition_quality: AcquisitionQuality
    discontinuities: int = 0
    replay_status: ReplayStatus = "NOT_STARTED"
    created_at: str
