"""The frozen experiment contract (`analysis_contract.json`).

Every field the user's specification names is present here, even though
several (`model_branch_definitions`, `hyperparameter_search_space`,
`statistical_tests`, ...) will only be *interpreted* by the statistical
engine built in a later phase -- Fase 1's job is to store, hash, and version
them immutably, not to act on their contents yet. That is why those fields
are typed as plain JSON containers (`dict[str, Any]` / `list[Any]`) rather
than a rigid nested schema: inventing that schema now, before RQ1-4/S1-S2
exist to consume it, would be designing for a shape we cannot yet verify is
right.

Freezing is enforced the same way `DatasetManifest`/`ExampleRecord` already
enforce it elsewhere in this codebase: the pydantic model itself is
`frozen=True` (inherited from `StudioContract`), and the repository layer
never overwrites a `protocol_id`'s existing `protocol_version` -- a changed
payload always becomes a new, higher `protocol_version` in its own run
directory (see `scientific_results_repository.py`).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import model_validator

from .common import StudioContract, identity_hash

ANALYSIS_CONTRACT_SCHEMA_VERSION = "ble-scientific-results-analysis-contract-v1"

GitDirtyState = Literal["CLEAN", "DIRTY"]

# Fase 1 closure item A.2: confirmatory fields that must never silently fall
# back to an empty string. split_manifest_hash is deliberately excluded --
# it legitimately starts empty at protocol-freeze time and is only attached
# once a concrete dataset/split is chosen (see freeze_protocol()'s
# docstring in scientific_results_repository.py).
_REQUIRED_NON_EMPTY_STRING_FIELDS = (
    "protocol_id", "git_commit", "hardware_profile_id", "receiver_profile_hash",
    "association_policy_hash", "quality_policy_hash", "dataset_policy_hash", "interpretation_matrix_hash",
)


class AnalysisContract(StudioContract):
    schema_version: Literal["ble-scientific-results-analysis-contract-v1"] = ANALYSIS_CONTRACT_SCHEMA_VERSION

    protocol_id: str
    protocol_version: int  # monotonic per protocol_id, starts at 1
    creation_timestamp_utc: str

    # Determinism/environment provenance.
    git_commit: str
    git_dirty_state: GitDirtyState
    software_environment_digest: str

    # Hardware/receiver.
    hardware_profile_id: str
    receiver_profile_hash: str

    # Population and design.
    device_population: dict[str, Any] = {}
    device_ids: list[str] = []
    firmware_hashes: dict[str, str] = {}
    channels: list[int] = []
    campaign_schedule: dict[str, Any] = {}
    intervention_schedule: dict[str, Any] = {}
    content_variants: list[str] = []

    # Real enrolled inventory is heterogeneous (see
    # docs/ble/physical_device_inventory.json) -- there is no verified
    # same-model population, so the primary claim is scoped to the ENROLLED
    # units themselves, never generalized to "the CC2650 population" or any
    # other device family.
    primary_population: str = ""  # e.g. "ENROLLED_HETEROGENEOUS_DEVICES"
    primary_unit_ids: list[str] = []
    # {"group_name": str, "unit_ids": [...], "verified": bool,
    #  "verification_basis": str} -- verified must be True for len>1, see
    # _canonicalize_before_construction.
    secondary_same_model_subset: dict[str, Any] = {}
    configurable_content_subset: list[str] = []  # unit_ids eligible for RQ4 (content controls)
    device_specific_packet_profiles: dict[str, Any] = {}  # per-unit observed PDU type/interval/length, etc.
    crossover_intervention_schedule: dict[str, Any] = {}  # frozen device-day RESET/CONTINUOUS_POWER assignment
    population_claim_boundary: str = ""  # free text: exactly what population the paper's conclusions may generalize to

    # Policy hashes -- each is a content_hash() of the actual policy object
    # (association resolution, dataset quality gate, dataset admission,
    # a specific split manifest) as it exists in ble_rffi_studio at freeze
    # time, so a later silent change to that policy is detectable by
    # comparing hashes, never by trusting a free-text description.
    association_policy_hash: str
    quality_policy_hash: str
    dataset_policy_hash: str
    split_manifest_hash: str

    # Model/analysis plan.
    model_branch_definitions: list[dict[str, Any]] = []
    feature_policy: dict[str, Any] = {}
    signal_region_policy: dict[str, Any] = {}
    phase_compensation_policy: dict[str, Any] = {}
    hyperparameter_search_space: dict[str, Any] = {}
    model_selection_rule: str = ""
    random_seeds: list[int] = []
    number_of_restarts: int = 0
    threshold_selection_rule: str = ""
    abstention_rule: str = ""
    calibration_rule: str = ""

    # Statistics plan.
    multiplicity_family: dict[str, Any] = {}
    statistical_tests: list[str] = []
    effect_thresholds: dict[str, Any] = {}
    non_inferiority_margins: dict[str, Any] = {}
    minimum_independent_blocks: dict[str, Any] = {}
    interpretation_matrix_hash: str

    @model_validator(mode="before")
    @classmethod
    def _canonicalize_before_construction(cls, data: Any) -> Any:
        """Runs on the raw payload, before the frozen model is built --
        `mode="after"` cannot mutate fields on a frozen instance. Two
        deterministic-canonicalization rules live here: (1) reject a
        confirmatory field silently defaulting to/being passed as an empty
        string (Fase 1 closure item A.2 -- "prohibir que campos
        confirmatorios criticos adopten valores vacios o defaults
        silenciosos"); (2) normalize creation_timestamp_utc to a single UTC
        representation (`+00:00` offset -> trailing `Z`) so the same instant
        expressed two equivalent ways never produces two different
        content_hash() values."""
        if not isinstance(data, dict):
            return data
        empty_fields = [field for field in _REQUIRED_NON_EMPTY_STRING_FIELDS if isinstance(data.get(field), str) and data[field].strip() == ""]
        if empty_fields:
            raise ValueError(f"ANALYSIS_CONTRACT_EMPTY_CONFIRMATORY_FIELDS:{','.join(sorted(empty_fields))}")

        # Real inventory correction: the enrolled devices are five
        # heterogeneous BLE transmitters (CC2541 SensorTag, Shelly Plug,
        # two "keyfobdemo" units, one CC2650 SensorTag) -- there is no
        # verified same-model five-unit population. A protocol that still
        # asserts one must fail to freeze, not just be discouraged in docs.
        primary_population = str(data.get("primary_population") or "")
        forbidden_terms = ("five cc2650", "5 cc2650", "same-model five-unit", "same model five-unit")
        if any(term in primary_population.lower() for term in forbidden_terms):
            raise ValueError(f"ANALYSIS_CONTRACT_RETAINS_FALSIFIED_SAME_MODEL_ASSUMPTION:primary_population={primary_population!r}")
        if primary_population and not data.get("primary_unit_ids"):
            raise ValueError("ANALYSIS_CONTRACT_PRIMARY_POPULATION_WITHOUT_PRIMARY_UNIT_IDS")

        same_model_subset = data.get("secondary_same_model_subset") or {}
        if isinstance(same_model_subset, dict) and same_model_subset:
            unit_ids = same_model_subset.get("unit_ids") or []
            verified = same_model_subset.get("verified")
            if len(unit_ids) > 1 and verified is not True:
                raise ValueError(
                    f"ANALYSIS_CONTRACT_UNVERIFIED_SAME_MODEL_GROUP:secondary_same_model_subset claims {len(unit_ids)} "
                    "units without verified=True -- a same-model group with more than one member requires an explicit, "
                    "documented verification_basis (hardware_revision/firmware_hash/radio_chip match), never an assumption."
                )

        timestamp = data.get("creation_timestamp_utc")
        if isinstance(timestamp, str) and timestamp.endswith("+00:00"):
            data = {**data, "creation_timestamp_utc": timestamp[: -len("+00:00")] + "Z"}
        return data

    @staticmethod
    def make_protocol_id(*, project_id: str, seed_material: str) -> str:
        return identity_hash(project_id, seed_material, prefix="protocol")
