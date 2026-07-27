from __future__ import annotations

from typing import Literal

from .capture import DataOrigin
from .common import StudioContract
from .training import OperationalUse

BUNDLE_SCHEMA_VERSION = "ble-rffi-studio-bundle-v1"

# SYNTHETIC_PIPELINE_VERIFIED is a hard ceiling, not a step on the way to
# APPROVED_FOR_LIVE_PILOT: BundleBuilder never assigns EVALUATED to a
# synthetic-origin bundle, and approve_for_live_pilot only accepts EVALUATED,
# so a synthetic bundle structurally cannot reach APPROVED_FOR_LIVE_PILOT.
ApprovalStatus = Literal["DRAFT", "EVALUATED", "SYNTHETIC_PIPELINE_VERIFIED", "APPROVED_FOR_LIVE_PILOT", "REJECTED"]

# Every one of these files must exist inside a bundle directory and have an
# entry in artifact_hashes before approval_status can move past DRAFT.
REQUIRED_BUNDLE_FILES = (
    "model_file",
    "model_manifest.json",
    "preprocessing_config.json",
    "feature_config.json",
    "label_map.json",
    "thresholds.json",
    "dataset_reference.json",
    "split_reference.json",
    "evaluation_report.json",
    "runtime_requirements.json",
    "input_contract.json",
    "model_card.md",
    "scientific_basis.json",
    "calibration_report.json",
    "acceptance_criteria.json",
    "code_reference.json",
)


class ModelBundleManifest(StudioContract):
    schema_version: Literal["ble-rffi-studio-bundle-v1"] = BUNDLE_SCHEMA_VERSION
    bundle_id: str
    training_run_id: str
    data_origin: DataOrigin
    operational_use: OperationalUse

    artifact_hashes: dict[str, str] = {}  # filename -> sha256, one entry per REQUIRED_BUNDLE_FILES
    bundle_sha256: str | None = None
    approval_status: ApprovalStatus = "DRAFT"
    created_at: str
