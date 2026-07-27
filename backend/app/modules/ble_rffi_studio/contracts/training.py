from __future__ import annotations

from typing import Any, Literal

from .capture import DataOrigin
from .common import StudioContract

TRAINING_RUN_SCHEMA_VERSION = "ble-rffi-studio-training-run-v1"
OperationalUse = Literal["ALLOWED", "FORBIDDEN"]

ModelType = Literal["logistic_regression", "svm_rbf", "random_forest", "cnn1d", "cnn2d"]
TrainingRunStatus = Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]


class TrainingRun(StudioContract):
    schema_version: Literal["ble-rffi-studio-training-run-v1"] = TRAINING_RUN_SCHEMA_VERSION
    training_run_id: str
    project_id: str
    campaign_id: str

    dataset_id: str
    dataset_version: str
    dataset_manifest_sha256: str
    split_manifest_sha256: str
    scientific_task: str
    # Copied from the dataset this run trained on -- never user-settable,
    # never defaulted, so a synthetic-origin run can never masquerade as real.
    data_origin: DataOrigin
    operational_use: OperationalUse

    model_type: ModelType
    base_preprocessing_profile_id: str
    representation_profile_id: str
    hyperparameters: dict[str, Any] = {}
    random_seed: int
    software_versions: dict[str, str] = {}

    status: TrainingRunStatus = "QUEUED"
    started_at: str | None = None
    completed_at: str | None = None
