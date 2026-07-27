"""Orchestrates baseline-model training against a READY split with a PASSED
leakage check -- it refuses to run otherwise, rather than silently training
on a split that hasn't earned that status. Windows are loaded from the real
capture IQ files, base-preprocessed (per design, nothing signal-altering
unless explicitly justified), turned into the feature_vector representation,
scaled with TRAIN-only statistics, then handed to a baseline model.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from app.infrastructure.ble.capture.ble_offline_replay import utc_now

from ..contracts import ExampleRecord, SplitManifest, TrainingRun
from ..preprocessing import BasePreprocessingProfile, TrainOnlyScaler, apply_base_preprocessing, feature_vector_representation, load_iq_window
from ..preprocessing.representation_profiles import FEATURE_NAMES, raw_iq_representation, spectrogram_representation
from .baseline_models import BaselineModelTrainer
from .cnn_models import CnnTrainer

UNKNOWN_CLASS_LABEL = "UNKNOWN"
DEFAULT_RAW_IQ_LENGTH = 800
DEFAULT_SPECTROGRAM_N_FFT = 64
DEFAULT_SPECTROGRAM_FRAMES = 32


@dataclass
class TrainingArtifacts:
    training_run: TrainingRun
    model: Any
    scaler: TrainOnlyScaler | None
    label_classes: list[str]
    metrics: dict[str, dict[str, Any]]
    predictions: dict[str, list[dict[str, Any]]]
    feature_names: list[str] = field(default_factory=lambda: list(FEATURE_NAMES))
    # Real wall-clock: predict_proba() on one VALIDATION example, averaged.
    # None when VALIDATION is empty -- never fabricated as 0.
    validation_latency_ms: float | None = None


class TrainingService:
    def __init__(self, capture_iq_paths: dict[str, Path], base_profile: BasePreprocessingProfile | None = None) -> None:
        self.capture_iq_paths = capture_iq_paths
        self.base_profile = base_profile or BasePreprocessingProfile(profile_id="base-v1")

    def _label_for(self, example: ExampleRecord) -> str:
        return example.physical_unit_id or UNKNOWN_CLASS_LABEL

    def _window_for(self, example: ExampleRecord) -> np.ndarray:
        path = self.capture_iq_paths[example.capture_id]
        window = load_iq_window(path, example.iq_start_sample, example.iq_end_sample)
        return apply_base_preprocessing(window, self.base_profile, float(example.sample_rate_sps))

    def _features_for(self, examples: list[ExampleRecord]) -> np.ndarray:
        if not examples:
            return np.zeros((0, len(FEATURE_NAMES)))
        return np.stack([feature_vector_representation(self._window_for(e), float(e.sample_rate_sps)) for e in examples])

    def run_baseline(self, *, training_run: TrainingRun, split: SplitManifest, examples_by_id: dict[str, ExampleRecord]) -> TrainingArtifacts:
        if split.split_status != "READY":
            raise ValueError(f"CANNOT_TRAIN_ON_A_SPLIT_THAT_IS_NOT_READY:{split.split_status}")
        if split.leakage_check.status != "PASSED":
            raise ValueError(f"CANNOT_TRAIN_WHEN_LEAKAGE_CHECK_DID_NOT_PASS:{split.leakage_check.status}")
        if training_run.model_type not in ("logistic_regression", "svm_rbf", "random_forest"):
            raise ValueError(f"run_baseline only supports classical baseline model_types, got {training_run.model_type}")

        by_split: dict[str, list[ExampleRecord]] = {"TRAIN": [], "VALIDATION": [], "TEST": []}
        for assignment in split.assignments:
            by_split[assignment.split].append(examples_by_id[assignment.example_id])
        if not by_split["TRAIN"]:
            raise ValueError("NO_TRAIN_EXAMPLES_IN_SPLIT")

        started_at = utc_now()
        X = {name: self._features_for(exs) for name, exs in by_split.items()}
        y = {name: [self._label_for(e) for e in exs] for name, exs in by_split.items()}

        scaler = TrainOnlyScaler()
        scaler.fit(X["TRAIN"], split="TRAIN")
        X_scaled = {name: (scaler.transform(arr) if len(arr) else arr) for name, arr in X.items()}

        trainer = BaselineModelTrainer()
        model = trainer.build(training_run.model_type, training_run.random_seed, training_run.hyperparameters)
        trainer.fit(model, X_scaled["TRAIN"], y["TRAIN"])
        classes = trainer.classes(model)

        metrics: dict[str, dict[str, Any]] = {}
        predictions: dict[str, list[dict[str, Any]]] = {}
        for name in ("TRAIN", "VALIDATION", "TEST"):
            exs = by_split[name]
            if not exs:
                continue
            proba = trainer.predict_proba(model, X_scaled[name])
            predicted_idx = np.argmax(proba, axis=1)
            predicted_labels = [classes[i] for i in predicted_idx]
            true_labels = y[name]
            accuracy = float(np.mean([p == t for p, t in zip(predicted_labels, true_labels)]))
            metrics[name] = {"accuracy": accuracy, "n_examples": len(true_labels)}
            predictions[name] = [
                {
                    "example_id": exs[i].example_id,
                    "true_label": true_labels[i],
                    "predicted_label": predicted_labels[i],
                    "probabilities": {cls: float(p) for cls, p in zip(classes, proba[i])},
                }
                for i in range(len(exs))
            ]

        validation_latency_ms = self._measure_latency_ms(lambda sample: trainer.predict_proba(model, sample), X_scaled["VALIDATION"])

        completed_run = training_run.model_copy(update={"status": "COMPLETED", "started_at": started_at, "completed_at": utc_now()})
        return TrainingArtifacts(training_run=completed_run, model=model, scaler=scaler, label_classes=classes, metrics=metrics, predictions=predictions, validation_latency_ms=validation_latency_ms)

    def _measure_latency_ms(self, predict_one, validation_X: np.ndarray, repeats: int = 10) -> float | None:
        if len(validation_X) == 0:
            return None
        sample = validation_X[:1]
        timings = []
        for _ in range(repeats):
            start = time.perf_counter()
            predict_one(sample)
            timings.append((time.perf_counter() - start) * 1000.0)
        return float(np.mean(timings))

    def _cnn_representation(self, example: ExampleRecord, model_type: str) -> np.ndarray:
        window = self._window_for(example)
        if model_type == "cnn1d":
            return raw_iq_representation(window, DEFAULT_RAW_IQ_LENGTH)
        return spectrogram_representation(window, float(example.sample_rate_sps), n_fft=DEFAULT_SPECTROGRAM_N_FFT, target_frames=DEFAULT_SPECTROGRAM_FRAMES)

    def run_cnn(self, *, training_run: TrainingRun, split: SplitManifest, examples_by_id: dict[str, ExampleRecord], epochs: int = 30) -> TrainingArtifacts:
        if split.split_status != "READY":
            raise ValueError(f"CANNOT_TRAIN_ON_A_SPLIT_THAT_IS_NOT_READY:{split.split_status}")
        if split.leakage_check.status != "PASSED":
            raise ValueError(f"CANNOT_TRAIN_WHEN_LEAKAGE_CHECK_DID_NOT_PASS:{split.leakage_check.status}")
        if training_run.model_type not in ("cnn1d", "cnn2d"):
            raise ValueError(f"run_cnn only supports cnn1d/cnn2d, got {training_run.model_type}")

        by_split: dict[str, list[ExampleRecord]] = {"TRAIN": [], "VALIDATION": [], "TEST": []}
        for assignment in split.assignments:
            by_split[assignment.split].append(examples_by_id[assignment.example_id])
        if not by_split["TRAIN"]:
            raise ValueError("NO_TRAIN_EXAMPLES_IN_SPLIT")

        started_at = utc_now()
        classes = sorted({self._label_for(e) for e in by_split["TRAIN"]})
        class_to_idx = {label: idx for idx, label in enumerate(classes)}

        X = {name: (np.stack([self._cnn_representation(e, training_run.model_type) for e in exs]) if exs else np.zeros((0,))) for name, exs in by_split.items()}
        y_labels = {name: [self._label_for(e) for e in exs] for name, exs in by_split.items()}

        trainer = CnnTrainer()
        model = trainer.build(training_run.model_type, num_classes=len(classes))
        y_train_idx = np.array([class_to_idx.get(label, -1) for label in y_labels["TRAIN"]])
        if (y_train_idx < 0).any():
            raise ValueError("TRAIN_LABEL_NOT_IN_CLASS_SET")  # cannot happen: classes are derived from TRAIN itself
        trainer.fit(model, X["TRAIN"], y_train_idx, random_seed=training_run.random_seed, epochs=epochs)

        metrics: dict[str, dict[str, Any]] = {}
        predictions: dict[str, list[dict[str, Any]]] = {}
        for name in ("TRAIN", "VALIDATION", "TEST"):
            exs = by_split[name]
            if not exs:
                continue
            proba = trainer.predict_proba(model, X[name])
            predicted_idx = np.argmax(proba, axis=1)
            predicted_labels = [classes[i] for i in predicted_idx]
            true_labels = y_labels[name]
            # A VALIDATION/TEST example whose true label never appeared in
            # TRAIN (e.g. an UNKNOWN_DEVICE_REJECTION unknown-device session)
            # cannot be "correctly classified" among TRAIN's classes -- it is
            # excluded from this closed-set accuracy, not silently counted
            # as right or wrong; Fase 5's UNKNOWN calibration handles it.
            comparable = [i for i in range(len(exs)) if true_labels[i] in class_to_idx]
            accuracy = float(np.mean([predicted_labels[i] == true_labels[i] for i in comparable])) if comparable else None
            metrics[name] = {"accuracy": accuracy, "n_examples": len(true_labels), "n_comparable_to_train_classes": len(comparable)}
            predictions[name] = [
                {
                    "example_id": exs[i].example_id,
                    "true_label": true_labels[i],
                    "predicted_label": predicted_labels[i],
                    "probabilities": {cls: float(p) for cls, p in zip(classes, proba[i])},
                }
                for i in range(len(exs))
            ]

        validation_latency_ms = self._measure_latency_ms(lambda sample: trainer.predict_proba(model, sample), X["VALIDATION"])

        completed_run = training_run.model_copy(update={"status": "COMPLETED", "started_at": started_at, "completed_at": utc_now()})
        return TrainingArtifacts(training_run=completed_run, model=model, scaler=None, label_classes=classes, metrics=metrics, predictions=predictions, validation_latency_ms=validation_latency_ms)
