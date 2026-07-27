"""Fase 5 end-to-end: train -> evaluate -> calibrate -> export a real bundle
to disk -> reload it in a FRESH OfflineInferenceService (simulating a
completely separate process, as a real offline inference deployment would
be) -> score held-out TEST examples purely from the bundle's own files.
"""
from __future__ import annotations

import pytest

from app.modules.ble_rffi_studio.contracts import TrainingRun
from app.modules.ble_rffi_studio.dataset import DatasetBuilder
from app.modules.ble_rffi_studio.evaluation import Evaluator
from app.modules.ble_rffi_studio.export import BundleBuilder
from app.modules.ble_rffi_studio.inference import OfflineInferenceService
from app.modules.ble_rffi_studio.quality import SplitBuilder
from app.modules.ble_rffi_studio.training import TrainingService

from ._helpers import write_synthetic_capture_iq


@pytest.fixture
def trained_artifacts(tmp_path):
    examples, capture_iq_paths = write_synthetic_capture_iq(tmp_path, units=2, sessions_per_unit=3, examples_per_session=10)
    builder = DatasetBuilder(tmp_path / "datasets")
    draft = builder.build_draft(dataset_id="SYN-DS", dataset_version="1.0.0", project_id="P1", campaign_id="C1", examples=examples, data_origin="REAL_B200", creation_policy={}, created_at="2026-07-26T00:00:00Z")
    dataset = builder.freeze(draft)
    split = SplitBuilder().build(dataset=dataset, examples=examples, scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", created_at="2026-07-26T00:00:00Z")
    examples_by_id = {e.example_id: e for e in examples}
    training_run = TrainingRun(
        training_run_id="run-1", project_id="P1", campaign_id="C1", dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version,
        dataset_manifest_sha256=dataset.dataset_manifest_sha256, split_manifest_sha256=split.split_manifest_sha256,
        scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", model_type="logistic_regression",
        data_origin="REAL_B200", operational_use="ALLOWED", base_preprocessing_profile_id="base-v1", representation_profile_id="feature_vector-v1", random_seed=0,
    )
    artifacts = TrainingService(capture_iq_paths).run_baseline(training_run=training_run, split=split, examples_by_id=examples_by_id)
    return dataset, split, artifacts, examples_by_id, capture_iq_paths


def test_bundle_contains_every_required_file_with_a_real_hash(trained_artifacts, tmp_path):
    from app.modules.ble_rffi_studio.contracts import REQUIRED_BUNDLE_FILES

    dataset, split, artifacts, examples_by_id, capture_iq_paths = trained_artifacts
    evaluator = Evaluator()
    evaluation_reports = {name: evaluator.evaluate_split(name, preds, artifacts.label_classes) for name, preds in artifacts.predictions.items()}
    threshold = evaluator.calibrate_unknown_threshold(artifacts.predictions["VALIDATION"], artifacts.label_classes)
    calibration = {"acceptance_threshold": threshold, "calibrated_on": "VALIDATION", "min_identified_precision": 0.9}

    bundle_builder = BundleBuilder(tmp_path / "bundles")
    manifest, reasons = bundle_builder.build(
        bundle_id="bundle-1", training_run=artifacts.training_run, model=artifacts.model, label_classes=artifacts.label_classes,
        feature_names=artifacts.feature_names, scaler=artifacts.scaler, dataset=dataset, split=split,
        evaluation_reports=evaluation_reports, calibration=calibration, acceptance_criteria={"min_test_accuracy": 0.6},
        model_card_text="# Test model\nSynthetic demonstration only.", code_reference={"module": "ble_rffi_studio"},
        created_at="2026-07-26T00:00:00Z",
    )

    assert set(manifest.artifact_hashes.keys()) == set(REQUIRED_BUNDLE_FILES)
    assert all(len(h) == 64 for h in manifest.artifact_hashes.values())  # real sha256 hex digests
    assert manifest.bundle_sha256 is not None


def test_bundle_is_evaluated_not_auto_approved_when_criteria_are_met(trained_artifacts, tmp_path):
    dataset, split, artifacts, examples_by_id, capture_iq_paths = trained_artifacts
    evaluator = Evaluator()
    evaluation_reports = {name: evaluator.evaluate_split(name, preds, artifacts.label_classes) for name, preds in artifacts.predictions.items()}
    threshold = evaluator.calibrate_unknown_threshold(artifacts.predictions["VALIDATION"], artifacts.label_classes)
    calibration = {"acceptance_threshold": threshold}

    bundle_builder = BundleBuilder(tmp_path / "bundles")
    manifest, reasons = bundle_builder.build(
        bundle_id="bundle-1", training_run=artifacts.training_run, model=artifacts.model, label_classes=artifacts.label_classes,
        feature_names=artifacts.feature_names, scaler=artifacts.scaler, dataset=dataset, split=split,
        evaluation_reports=evaluation_reports, calibration=calibration, acceptance_criteria={"min_test_accuracy": 0.5},
        model_card_text="# Test model", code_reference={}, created_at="2026-07-26T00:00:00Z",
    )
    assert manifest.approval_status == "EVALUATED"  # never APPROVED_FOR_LIVE_PILOT straight out of build()
    assert reasons == []


def test_bundle_is_rejected_when_criteria_are_not_met(trained_artifacts, tmp_path):
    dataset, split, artifacts, examples_by_id, capture_iq_paths = trained_artifacts
    evaluator = Evaluator()
    evaluation_reports = {name: evaluator.evaluate_split(name, preds, artifacts.label_classes) for name, preds in artifacts.predictions.items()}
    calibration = {"acceptance_threshold": 0.99}

    bundle_builder = BundleBuilder(tmp_path / "bundles")
    manifest, reasons = bundle_builder.build(
        bundle_id="bundle-2", training_run=artifacts.training_run, model=artifacts.model, label_classes=artifacts.label_classes,
        feature_names=artifacts.feature_names, scaler=artifacts.scaler, dataset=dataset, split=split,
        evaluation_reports=evaluation_reports, calibration=calibration, acceptance_criteria={"min_test_accuracy": 1.1},  # unreachable by construction (accuracy is capped at 1.0)
        model_card_text="# Test model", code_reference={}, created_at="2026-07-26T00:00:00Z",
    )
    assert manifest.approval_status == "REJECTED"
    assert reasons


def test_approve_for_live_pilot_requires_evaluated_status_first(trained_artifacts, tmp_path):
    dataset, split, artifacts, examples_by_id, capture_iq_paths = trained_artifacts
    evaluator = Evaluator()
    evaluation_reports = {name: evaluator.evaluate_split(name, preds, artifacts.label_classes) for name, preds in artifacts.predictions.items()}
    calibration = {"acceptance_threshold": 0.99}
    bundle_builder = BundleBuilder(tmp_path / "bundles")
    rejected_manifest, _ = bundle_builder.build(
        bundle_id="bundle-3", training_run=artifacts.training_run, model=artifacts.model, label_classes=artifacts.label_classes,
        feature_names=artifacts.feature_names, scaler=artifacts.scaler, dataset=dataset, split=split,
        evaluation_reports=evaluation_reports, calibration=calibration, acceptance_criteria={"min_test_accuracy": 1.1},  # unreachable by construction (accuracy is capped at 1.0)
        model_card_text="# Test model", code_reference={}, created_at="2026-07-26T00:00:00Z",
    )
    assert rejected_manifest.approval_status == "REJECTED"
    with pytest.raises(ValueError):
        bundle_builder.approve_for_live_pilot(rejected_manifest)


def test_offline_inference_reloads_a_fresh_bundle_and_scores_unseen_examples(trained_artifacts, tmp_path):
    dataset, split, artifacts, examples_by_id, capture_iq_paths = trained_artifacts
    evaluator = Evaluator()
    evaluation_reports = {name: evaluator.evaluate_split(name, preds, artifacts.label_classes) for name, preds in artifacts.predictions.items()}
    threshold = evaluator.calibrate_unknown_threshold(artifacts.predictions["VALIDATION"], artifacts.label_classes, min_identified_precision=0.7)
    calibration = {"acceptance_threshold": threshold, "calibrated_on": "VALIDATION"}

    bundle_builder = BundleBuilder(tmp_path / "bundles")
    manifest, _ = bundle_builder.build(
        bundle_id="bundle-inference", training_run=artifacts.training_run, model=artifacts.model, label_classes=artifacts.label_classes,
        feature_names=artifacts.feature_names, scaler=artifacts.scaler, dataset=dataset, split=split,
        evaluation_reports=evaluation_reports, calibration=calibration, acceptance_criteria={"min_test_accuracy": 0.5},
        model_card_text="# Test model", code_reference={}, created_at="2026-07-26T00:00:00Z",
    )

    test_example_ids = {a.example_id for a in split.assignments if a.split == "TEST"}
    test_examples = [examples_by_id[eid] for eid in test_example_ids]

    # A brand-new service instance, as a real separate offline-inference
    # process would be -- nothing here reuses the in-memory trained model.
    inference_service = OfflineInferenceService(tmp_path / "bundles", capture_iq_paths)
    decisions = inference_service.run(bundle_id="bundle-inference", examples=test_examples)

    assert len(decisions) == len(test_examples)
    assert all(d["final_decision"] in ("IDENTIFIED", "UNKNOWN", "INSUFFICIENT_EVIDENCE") for d in decisions)
    correct = sum(1 for d, e in zip(decisions, test_examples) if d["final_decision"] == "IDENTIFIED" and d["predicted_class"] == e.physical_unit_id)
    assert correct / len(test_examples) > 0.5


def test_offline_inference_raises_for_an_unknown_bundle_id(tmp_path):
    inference_service = OfflineInferenceService(tmp_path / "bundles", {})
    with pytest.raises(Exception):
        inference_service.run(bundle_id="does-not-exist", examples=[])
