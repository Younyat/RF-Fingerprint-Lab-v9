"""Fase 5: offline inference over an exported bundle -- reads a frozen model
+ scaler + label map + calibrated threshold from disk and scores NEW,
previously-unseen ExampleRecords. Deliberately offline only: this never
touches Live Monitor or any live streaming path (explicitly out of scope
until a bundle is trained, evaluated, and exported, per the original design).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np
import torch

from app.infrastructure.ble.capture.ble_offline_replay import read_json

from ..contracts import ExampleRecord, ModelBundleManifest
from ..evaluation import Evaluator
from ..preprocessing import BasePreprocessingProfile, apply_base_preprocessing, load_iq_window
from ..preprocessing.representation_profiles import feature_vector_representation, raw_iq_representation, spectrogram_representation
from ..training.training_service import DEFAULT_RAW_IQ_LENGTH, DEFAULT_SPECTROGRAM_FRAMES, DEFAULT_SPECTROGRAM_N_FFT

_TORCH_MODEL_TYPES = {"cnn1d", "cnn2d"}


class BundleNotFoundError(Exception):
    pass


class OfflineInferenceService:
    def __init__(self, bundle_root: Path, capture_iq_paths: dict[str, Path]) -> None:
        self.bundle_root = bundle_root
        self.capture_iq_paths = capture_iq_paths
        self.evaluator = Evaluator()

    def _load_bundle(self, bundle_id: str) -> dict[str, Any]:
        bundle_dir = self.bundle_root / bundle_id
        manifest_path = bundle_dir / "bundle_manifest.json"
        if not manifest_path.is_file():
            raise BundleNotFoundError(f"BUNDLE_NOT_FOUND:{bundle_id}")
        manifest = ModelBundleManifest.model_validate(read_json(manifest_path))
        model_manifest = read_json(bundle_dir / "model_manifest.json")
        feature_config = read_json(bundle_dir / "feature_config.json")
        thresholds = read_json(bundle_dir / "thresholds.json")

        model_type = model_manifest["model_type"]
        if model_type in _TORCH_MODEL_TYPES:
            model = torch.load(bundle_dir / model_manifest["model_file"], weights_only=False)
            model.eval()
        else:
            model = joblib.load(bundle_dir / model_manifest["model_file"])

        scaler = None
        if feature_config.get("scaler_file"):
            scaler = joblib.load(bundle_dir / feature_config["scaler_file"])

        return {
            "manifest": manifest, "model": model, "model_type": model_type,
            "label_classes": model_manifest["label_classes"],
            "representation_profile_id": feature_config["representation_profile_id"],
            "scaler": scaler,
            "acceptance_threshold": thresholds.get("acceptance_threshold"),
        }

    def _representation(self, window: np.ndarray, sample_rate_sps: float, representation_profile_id: str) -> np.ndarray:
        if representation_profile_id.startswith("feature_vector"):
            return feature_vector_representation(window, sample_rate_sps)
        if representation_profile_id.startswith("raw_iq"):
            return raw_iq_representation(window, DEFAULT_RAW_IQ_LENGTH)
        if representation_profile_id.startswith("spectrogram"):
            return spectrogram_representation(window, sample_rate_sps, n_fft=DEFAULT_SPECTROGRAM_N_FFT, target_frames=DEFAULT_SPECTROGRAM_FRAMES)
        raise ValueError(f"UNSUPPORTED_REPRESENTATION_PROFILE:{representation_profile_id}")

    def _predict_proba(self, bundle: dict[str, Any], X: np.ndarray) -> np.ndarray:
        if bundle["model_type"] in _TORCH_MODEL_TYPES:
            with torch.no_grad():
                logits = bundle["model"](torch.from_numpy(X.astype(np.float32)))
                return torch.softmax(logits, dim=1).numpy()
        return bundle["model"].predict_proba(X)

    def run(self, *, bundle_id: str, examples: list[ExampleRecord], base_profile: BasePreprocessingProfile | None = None) -> list[dict[str, Any]]:
        bundle = self._load_bundle(bundle_id)
        base_profile = base_profile or BasePreprocessingProfile(profile_id="base-v1")
        acceptance_threshold = bundle["acceptance_threshold"]
        if acceptance_threshold is None:
            raise ValueError(f"BUNDLE_HAS_NO_CALIBRATED_ACCEPTANCE_THRESHOLD:{bundle_id}")

        results: list[dict[str, Any]] = []
        for example in examples:
            iq_path = self.capture_iq_paths[example.capture_id]
            window = load_iq_window(iq_path, example.iq_start_sample, example.iq_end_sample)
            window = apply_base_preprocessing(window, base_profile, float(example.sample_rate_sps))
            features = self._representation(window, float(example.sample_rate_sps), bundle["representation_profile_id"])
            X = features[np.newaxis, ...]
            if bundle["scaler"] is not None:
                X = bundle["scaler"].transform(X)
            proba = self._predict_proba(bundle, X)[0]
            probabilities = {cls: float(p) for cls, p in zip(bundle["label_classes"], proba)}
            decision = self.evaluator.classify_with_threshold({"example_id": example.example_id, "probabilities": probabilities}, acceptance_threshold)
            results.append(decision)
        return results
