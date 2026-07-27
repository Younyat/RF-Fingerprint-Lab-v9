"""Fase 5 export: writes every file REQUIRED_BUNDLE_FILES demands, hashes
each one, and hashes the hash-set itself into bundle_sha256. Design
correction #17: a bundle is never auto-approved for the live pilot just
because it loads -- build() can only reach EVALUATED or REJECTED (a real,
computed comparison against frozen acceptance_criteria); moving to
APPROVED_FOR_LIVE_PILOT is a separate, explicit human sign-off step.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import scipy
import sklearn
import torch

from app.infrastructure.ble.capture.ble_offline_replay import read_json, sha256_file, write_json

from ..contracts import REQUIRED_BUNDLE_FILES, DatasetManifest, ModelBundleManifest, SplitManifest, TrainingRun
from ..evaluation import SplitEvaluationReport

_TORCH_MODEL_TYPES = {"cnn1d", "cnn2d"}


class BundleBuilder:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _save_model(self, bundle_dir: Path, model_type: str, model: Any) -> str:
        if model_type in _TORCH_MODEL_TYPES:
            filename = "model.pt"
            torch.save(model, bundle_dir / filename)
        else:
            filename = "model.joblib"
            joblib.dump(model, bundle_dir / filename)
        return filename

    def build(
        self,
        *,
        bundle_id: str,
        training_run: TrainingRun,
        model: Any,
        label_classes: list[str],
        feature_names: list[str] | None,
        scaler: Any | None = None,
        dataset: DatasetManifest,
        split: SplitManifest,
        evaluation_reports: dict[str, SplitEvaluationReport],
        calibration: dict[str, Any],
        acceptance_criteria: dict[str, Any],
        model_card_text: str,
        code_reference: dict[str, Any],
        created_at: str,
    ) -> tuple[ModelBundleManifest, list[str]]:
        bundle_dir = self.root / bundle_id
        bundle_dir.mkdir(parents=True, exist_ok=True)

        model_filename = self._save_model(bundle_dir, training_run.model_type, model)
        scaler_filename = None
        if scaler is not None:
            scaler_filename = "scaler.joblib"
            joblib.dump(scaler, bundle_dir / scaler_filename)

        write_json(bundle_dir / "model_manifest.json", {
            "model_type": training_run.model_type, "label_classes": label_classes,
            "training_run_id": training_run.training_run_id, "random_seed": training_run.random_seed,
            "model_file": model_filename,
        })
        write_json(bundle_dir / "preprocessing_config.json", {"base_preprocessing_profile_id": training_run.base_preprocessing_profile_id})
        write_json(bundle_dir / "feature_config.json", {
            "representation_profile_id": training_run.representation_profile_id, "feature_names": feature_names or [],
            "scaler_file": scaler_filename,
        })
        write_json(bundle_dir / "label_map.json", {"classes": label_classes})
        write_json(bundle_dir / "thresholds.json", calibration)
        write_json(bundle_dir / "dataset_reference.json", {
            "dataset_id": dataset.dataset_id, "dataset_version": dataset.dataset_version, "dataset_manifest_sha256": dataset.dataset_manifest_sha256,
            "data_origin": dataset.data_origin, "captures": dataset.captures, "sessions": dataset.sessions, "physical_units": dataset.physical_units,
        })
        write_json(bundle_dir / "split_reference.json", {
            "scientific_task": split.scientific_task, "split_manifest_sha256": split.split_manifest_sha256,
            "split_status": split.split_status, "leakage_check_status": split.leakage_check.status,
        })
        write_json(bundle_dir / "evaluation_report.json", {name: dataclasses.asdict(report) for name, report in evaluation_reports.items()})
        write_json(bundle_dir / "runtime_requirements.json", {
            "numpy": np.__version__, "scikit_learn": sklearn.__version__, "scipy": scipy.__version__,
            "torch": torch.__version__ if training_run.model_type in _TORCH_MODEL_TYPES else None,
        })
        write_json(bundle_dir / "input_contract.json", {
            "representation_profile_id": training_run.representation_profile_id,
            "sample_rate_sps_required": True, "expects": "ExampleRecord evidence window (iq_start_sample:iq_end_sample) from the source capture IQ file",
        })
        (bundle_dir / "model_card.md").write_text(model_card_text, encoding="utf-8")
        write_json(bundle_dir / "scientific_basis.json", {"note": "See app/modules/ble_rffi_studio/scientific_basis/technique_registry.json for the full technique/paper registry."})
        write_json(bundle_dir / "calibration_report.json", calibration)
        write_json(bundle_dir / "acceptance_criteria.json", acceptance_criteria)
        write_json(bundle_dir / "code_reference.json", code_reference)

        artifact_hashes: dict[str, str] = {}
        for required_name in REQUIRED_BUNDLE_FILES:
            actual_name = model_filename if required_name == "model_file" else required_name
            artifact_hashes[required_name] = sha256_file(bundle_dir / actual_name)

        bundle_sha256 = hashlib.sha256(json.dumps(artifact_hashes, sort_keys=True).encode("utf-8")).hexdigest()
        approval_status, reasons = self._evaluate_acceptance(acceptance_criteria, evaluation_reports, dataset, split)
        operational_use = "FORBIDDEN" if dataset.data_origin == "SYNTHETIC_TEST_ONLY" else "ALLOWED"

        manifest = ModelBundleManifest(
            bundle_id=bundle_id, training_run_id=training_run.training_run_id,
            data_origin=dataset.data_origin, operational_use=operational_use,
            artifact_hashes=artifact_hashes, bundle_sha256=bundle_sha256, approval_status=approval_status, created_at=created_at,
        )
        write_json(bundle_dir / "bundle_manifest.json", manifest.model_dump(mode="json"))
        return manifest, reasons

    def _evaluate_acceptance(
        self, acceptance_criteria: dict[str, Any], evaluation_reports: dict[str, SplitEvaluationReport],
        dataset: DatasetManifest, split: SplitManifest,
    ) -> tuple[str, list[str]]:
        reasons: list[str] = []
        # Real gates, checked again here rather than only trusted from
        # upstream -- a bundle is the artifact someone could hand to a live
        # pilot, so it re-verifies rather than assumes.
        if not dataset.frozen:
            reasons.append("Dataset is not frozen.")
        if split.split_status != "READY":
            reasons.append(f"Split status is {split.split_status}, not READY.")
        if split.leakage_check.status != "PASSED":
            reasons.append(f"Leakage check is {split.leakage_check.status}, not PASSED.")

        min_test_accuracy = acceptance_criteria.get("min_test_accuracy")
        if min_test_accuracy is not None:
            test_report = evaluation_reports.get("TEST")
            test_accuracy = test_report.accuracy if test_report else None
            if test_accuracy is None or test_accuracy < min_test_accuracy:
                reasons.append(f"TEST accuracy {test_accuracy} below required minimum {min_test_accuracy}.")
        min_validation_accuracy = acceptance_criteria.get("min_validation_accuracy")
        if min_validation_accuracy is not None:
            validation_report = evaluation_reports.get("VALIDATION")
            validation_accuracy = validation_report.accuracy if validation_report else None
            if validation_accuracy is None or validation_accuracy < min_validation_accuracy:
                reasons.append(f"VALIDATION accuracy {validation_accuracy} below required minimum {min_validation_accuracy}.")

        if reasons:
            return "REJECTED", reasons
        # A ceiling, not a step toward approval: SYNTHETIC_PIPELINE_VERIFIED
        # proves the software pipeline works end to end, nothing about a
        # physical device. approve_for_live_pilot only accepts EVALUATED, so
        # this status can never reach APPROVED_FOR_LIVE_PILOT.
        if dataset.data_origin == "SYNTHETIC_TEST_ONLY":
            return "SYNTHETIC_PIPELINE_VERIFIED", []
        return "EVALUATED", []

    def load_manifest(self, bundle_id: str) -> ModelBundleManifest | None:
        path = self.root / bundle_id / "bundle_manifest.json"
        if not path.is_file():
            return None
        return ModelBundleManifest.model_validate(read_json(path))

    def approve_for_live_pilot(self, manifest: ModelBundleManifest) -> ModelBundleManifest:
        """The explicit, separate human sign-off step. Never reachable from
        build() alone -- a bundle must already be EVALUATED (i.e. it met its
        own frozen acceptance_criteria) before this can run."""
        if manifest.data_origin != "REAL_B200" or manifest.operational_use == "FORBIDDEN":
            raise ValueError(
                f"CANNOT_APPROVE_A_SYNTHETIC_ORIGIN_BUNDLE_FOR_LIVE_PILOT:{manifest.bundle_id} "
                f"(data_origin={manifest.data_origin}). A model trained on any synthetic data can only ever "
                "reach SYNTHETIC_PIPELINE_VERIFIED -- it proves the software pipeline works, not physical RFFI capability."
            )
        if manifest.approval_status != "EVALUATED":
            raise ValueError(f"CANNOT_APPROVE_A_BUNDLE_THAT_IS_NOT_EVALUATED:{manifest.approval_status}")
        approved = manifest.model_copy(update={"approval_status": "APPROVED_FOR_LIVE_PILOT"})
        write_json(self.root / manifest.bundle_id / "bundle_manifest.json", approved.model_dump(mode="json"))
        return approved
