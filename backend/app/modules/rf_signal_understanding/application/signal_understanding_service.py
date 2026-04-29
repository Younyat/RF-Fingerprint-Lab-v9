from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from collections import deque

import numpy as np

from app.modules.rf_intelligence.schemas import RFIntelligenceSettings, SpectrumFrameInput
from app.modules.rf_intelligence.service import RFIntelligenceService
from app.modules.rf_signal_understanding.application.bispectral_verification_pipeline import BispectralVerificationPipeline
from app.modules.rf_signal_understanding.application.comparative_evaluation_pipeline import ComparativeEvaluationPipeline
from app.modules.rf_signal_understanding.application.decision_fusion_pipeline import DecisionFusionPipeline
from app.modules.rf_signal_understanding.application.region_classification_pipeline import RegionClassificationPipeline
from app.modules.rf_signal_understanding.application.waterfall_detection_pipeline import WaterfallDetectionPipeline
from app.modules.rf_signal_understanding.domain.schemas import AnalyzeCaptureRequest, CompareWithRFIntelligenceRequest, TrainingRequest, ValidationRequest
from app.modules.rf_signal_understanding.domain.value_objects import VALIDATION_TASKS
from app.modules.rf_signal_understanding.infrastructure.image_utils import normalize_to_uint8, write_grayscale_png
from app.modules.rf_signal_understanding.infrastructure.iq_region_extractor import IQRegionExtractor
from app.modules.rf_signal_understanding.infrastructure.model_registry import ModelRegistry
from app.modules.rf_signal_understanding.infrastructure.result_repository import ResultRepository
from app.modules.rf_signal_understanding.infrastructure.scientific_traceability import ScientificTraceability
from app.modules.rf_signal_understanding.infrastructure.spectral_feature_extractor import SpectralFeatureExtractor
from app.modules.rf_signal_understanding.infrastructure.stft_waterfall_builder import STFTWaterfallBuilder


class RFSignalUnderstandingService:
    def __init__(self, storage_root: Path, legacy_service: RFIntelligenceService | None = None) -> None:
        self.storage_root = storage_root
        self.module_root = Path(__file__).resolve().parents[1]
        self.repository = ResultRepository(storage_root)
        self.model_registry = ModelRegistry(self.module_root / "models")
        self.traceability = ScientificTraceability(self.module_root / "configs" / "references.json")
        self.waterfall_builder = STFTWaterfallBuilder()
        self.detector = WaterfallDetectionPipeline()
        self.classifier = RegionClassificationPipeline()
        self.iq_extractor = IQRegionExtractor()
        self.spectral_extractor = SpectralFeatureExtractor()
        self.bispectral = BispectralVerificationPipeline()
        self.fusion = DecisionFusionPipeline()
        self.comparison = ComparativeEvaluationPipeline()
        self.legacy_service = legacy_service or RFIntelligenceService()
        self._live_rows: deque[list[float]] = deque(maxlen=160)
        self._live_timestamps: deque[str | None] = deque(maxlen=160)
        self._live_signature: tuple[int, float, float] | None = None

    def analyze_capture(self, request: AnalyzeCaptureRequest) -> dict[str, Any]:
        analysis_id = request.analysis_id or self.repository.new_analysis_id()
        analysis_dir = self.repository.analysis_dir(analysis_id)
        input_path = Path(request.file_path).expanduser().resolve()
        iq_samples = self._read_iq(input_path)
        input_metadata = {
            "file_path": str(input_path),
            "sample_rate_hz": float(request.sample_rate_hz),
            "center_frequency_hz": float(request.center_frequency_hz),
            "format": request.format,
            "sample_count": int(iq_samples.size),
        }
        self.repository.write_json(analysis_dir, "input_metadata.json", input_metadata)

        waterfall = self.waterfall_builder.build(
            iq_samples,
            request.sample_rate_hz,
            request.center_frequency_hz,
            request.n_fft,
            request.hop_length,
            request.window,
            analysis_dir,
        )
        matrix = waterfall["waterfall_matrix"]
        regions = self.detector.detect(matrix, waterfall["time_axis_s"], waterfall["freq_axis_hz"])
        self.repository.write_json(analysis_dir, "regions.json", regions)

        result_regions: list[dict[str, Any]] = []
        fused_decisions: list[dict[str, Any]] = []
        for region in regions:
            region_matrix = self._region_matrix(matrix, region)
            region_png = analysis_dir / "regions" / f"{region['bbox_id']}.png"
            write_grayscale_png(region_png, normalize_to_uint8(region_matrix))
            iq_info = self.iq_extractor.extract(iq_samples, request.sample_rate_hz, request.center_frequency_hz, region, analysis_dir)
            segment = np.fromfile(iq_info["iq_segment_path"], dtype=np.complex64)
            classification = self.classifier.classify(region_matrix, region)
            spectral = self.spectral_extractor.extract(segment, request.sample_rate_hz, region_matrix, region)
            bispectral = self.bispectral.verify(segment)
            spectral_path = self.repository.write_json(analysis_dir, f"features/{region['bbox_id']}_spectral_features.json", spectral)
            bispectral_path = self.repository.write_json(analysis_dir, f"features/{region['bbox_id']}_bispectral_features.json", bispectral)
            fused = self.fusion.fuse(region, classification["visual"], classification["mlp"], spectral, bispectral)
            fused_decisions.append(fused)
            result_regions.append(
                {
                    "bbox_id": region["bbox_id"],
                    "time_start_s": region["time_start_s"],
                    "time_end_s": region["time_end_s"],
                    "freq_start_hz": region["freq_start_hz"],
                    "freq_end_hz": region["freq_end_hz"],
                    "detector": {"type": region["detector"], "confidence": region["confidence"]},
                    "classification": {
                        "visual_label": classification["visual"]["label"],
                        "visual_confidence": classification["visual"]["confidence"],
                        "mlp_label": classification["mlp"]["label"],
                        "mlp_confidence": classification["mlp"]["confidence"],
                        "visual": classification["visual"],
                        "mlp": classification["mlp"],
                    },
                    "iq_extraction": iq_info,
                    "region_image_path": str(region_png),
                    "features": {
                        "spectral_features_path": str(spectral_path.relative_to(analysis_dir)),
                        "bispectral_features_path": str(bispectral_path.relative_to(analysis_dir)),
                        "spectral": spectral,
                        "bispectral": bispectral,
                    },
                    "final_decision": {
                        "label": fused["final_label"],
                        "confidence": fused["final_confidence"],
                        "status": fused["decision_status"],
                        "method": fused["method"],
                        "limitations": fused["limitations"],
                    },
                }
            )

        trace = self.traceability.for_steps(
            ["waterfall_generation", "region_detection", "mlp_spectral_classification", "bispectral_verification"]
        )
        result = {
            "analysis_id": analysis_id,
            "input": input_metadata,
            "waterfall": {
                "n_fft": request.n_fft,
                "hop_length": request.hop_length,
                "window": request.window,
                "image_path": "waterfall.png",
                "matrix_path": "waterfall.npy",
                "power_db_min": waterfall["power_db_min"],
                "power_db_max": waterfall["power_db_max"],
            },
            "regions": result_regions,
            "summary": self._summary(result_regions, fused_decisions),
            "scientific_traceability": trace,
        }
        self.repository.write_json(analysis_dir, "scientific_traceability.json", trace)
        self.repository.write_json(analysis_dir, "results.json", result)
        return result

    def get_result(self, analysis_id: str) -> dict[str, Any]:
        return self.repository.read_result(analysis_id)

    def analyze_live_frame(self, raw_frame: dict[str, Any], legacy_result: dict[str, Any] | None = None) -> dict[str, Any]:
        levels = raw_frame.get("levels_db") or []
        freqs = raw_frame.get("frequencies_hz") or []
        if not levels or not freqs:
            return self._empty_live_result(raw_frame, "No live spectrum frame is available yet.")

        signature = (
            min(len(levels), len(freqs)),
            float(raw_frame.get("center_frequency_hz") or 0.0),
            float(raw_frame.get("span_hz") or raw_frame.get("sample_rate_hz") or 0.0),
        )
        if self._live_signature is not None and signature != self._live_signature:
            self._live_rows.clear()
            self._live_timestamps.clear()
        self._live_signature = signature

        self._live_rows.append([float(value) for value in levels])
        self._live_timestamps.append(raw_frame.get("timestamp_utc"))
        min_width = min(len(row) for row in self._live_rows)
        if min_width <= 0:
            return self._empty_live_result(raw_frame, "Live spectrum rows are empty.")
        matrix = np.asarray([row[:min_width] for row in self._live_rows], dtype=np.float32)
        freq_axis = [float(value) for value in freqs[: matrix.shape[1]]]
        frame_interval_s = float(raw_frame.get("frame_interval_s") or 0.1)
        time_axis = [index * frame_interval_s for index in range(matrix.shape[0])]
        regions = self.detector.detect(matrix, time_axis, freq_axis)
        result_regions: list[dict[str, Any]] = []

        for region in regions[:8]:
            region_matrix = self._region_matrix(matrix, region)
            classification = self.classifier.classify(region_matrix, region)
            spectral = self._live_spectral_features(region_matrix, region)
            bispectral = {
                "available": False,
                "reason": "Live mode currently receives PSD/waterfall frames, not raw I/Q samples.",
                "bispectral_peak_energy": 0.0,
                "bispectral_peak_location": [0.0, 0.0],
                "bispectral_entropy": 0.0,
                "phase_coupling_score": 0.0,
                "nonlinear_energy_ratio": 0.0,
            }
            fused = self.fusion.fuse(region, classification["visual"], classification["mlp"], spectral, bispectral, legacy_result)
            result_regions.append(
                {
                    "bbox_id": region["bbox_id"],
                    "time_start_s": region["time_start_s"],
                    "time_end_s": region["time_end_s"],
                    "freq_start_hz": region["freq_start_hz"],
                    "freq_end_hz": region["freq_end_hz"],
                    "detector": {"type": region["detector"], "confidence": region["confidence"]},
                    "classification": {
                        "visual_label": classification["visual"]["label"],
                        "visual_confidence": classification["visual"]["confidence"],
                        "mlp_label": classification["mlp"]["label"],
                        "mlp_confidence": classification["mlp"]["confidence"],
                        "visual": classification["visual"],
                        "mlp": classification["mlp"],
                    },
                    "features": {"spectral": spectral, "bispectral": bispectral},
                    "final_decision": {
                        "label": fused["final_label"],
                        "confidence": fused["final_confidence"],
                        "status": fused["decision_status"],
                        "method": fused["method"],
                        "limitations": fused["limitations"],
                    },
                }
            )

        trace = self.traceability.for_steps(["waterfall_generation", "region_detection", "mlp_spectral_classification"])
        return {
            "analysis_id": self.repository.new_analysis_id("rsu_live"),
            "mode": "live",
            "source": raw_frame.get("source", "real_sdr"),
            "timestamp_utc": raw_frame.get("timestamp_utc"),
            "input": {
                "center_frequency_hz": raw_frame.get("center_frequency_hz"),
                "sample_rate_hz": raw_frame.get("sample_rate_hz"),
                "span_hz": raw_frame.get("span_hz"),
                "format": "live_psd_waterfall",
            },
            "waterfall": {
                "rows": int(matrix.shape[0]),
                "freq_bins": int(matrix.shape[1]),
                "image_path": None,
                "note": "Live waterfall is built from recent real PSD frames.",
            },
            "regions": result_regions,
            "summary": self._summary(result_regions, []),
            "scientific_traceability": trace,
        }

    def compare_live_with_rf_intelligence(self, raw_frame: dict[str, Any]) -> dict[str, Any]:
        legacy = self._legacy_result_from_frame(raw_frame)
        new_result = self.analyze_live_frame(raw_frame, legacy)
        first_region = new_result["regions"][0] if new_result["regions"] else {}
        first_decision = first_region.get("final_decision", {})
        new_summary = {
            "method": "live_waterfall_region_mlp_fusion",
            "label": first_decision.get("label", "unknown"),
            "confidence": first_decision.get("confidence", 0.0),
            "evidence": self._evidence_lines(first_region),
            "scientific_traceability": new_result["scientific_traceability"],
        }
        return {
            "analysis_id": f"compare_live_{new_result['analysis_id']}",
            "legacy_rf_intelligence": legacy,
            "new_rf_signal_understanding": new_summary,
            "comparison": self.comparison.compare(legacy, new_summary),
            "live_result": new_result,
        }

    def compare_with_rf_intelligence(self, request: CompareWithRFIntelligenceRequest) -> dict[str, Any]:
        new_result = self.analyze_capture(request)
        legacy = self._legacy_result(request)
        first_region = new_result["regions"][0] if new_result["regions"] else {}
        first_decision = first_region.get("final_decision", {})
        new_summary = {
            "method": "waterfall_region_mlp_bispectral_fusion",
            "label": first_decision.get("label", "unknown"),
            "confidence": first_decision.get("confidence", 0.0),
            "evidence": self._evidence_lines(first_region),
            "scientific_traceability": new_result["scientific_traceability"],
        }
        comparison = self.comparison.compare(legacy, new_summary)
        response = {
            "analysis_id": f"compare_{new_result['analysis_id']}",
            "legacy_rf_intelligence": legacy,
            "new_rf_signal_understanding": new_summary,
            "comparison": comparison,
        }
        analysis_dir = self.repository.analysis_dir(new_result["analysis_id"])
        self.repository.write_json(analysis_dir, "comparison_with_legacy.json", response)
        return response

    def train_region_detector(self, request: TrainingRequest) -> dict[str, Any]:
        return self._training_stub(request, "region_detection", ["iou", "map", "precision", "recall"])

    def train_classifier(self, request: TrainingRequest) -> dict[str, Any]:
        return self._training_stub(request, "signal_type_classification", ["accuracy", "macro_f1", "top_k_accuracy"])

    def validate(self, request: ValidationRequest) -> dict[str, Any]:
        return {
            "task": request.task,
            "dataset_path": request.dataset_path,
            "metrics_required": VALIDATION_TASKS[request.task],
            "status": "validation_spec_ready",
            "note": "Detection, signal-type classification, robustness, and transmitter identification are separate validation tasks.",
        }

    def models(self) -> list[dict[str, Any]]:
        return self.model_registry.list_models()

    def references(self) -> dict[str, Any]:
        return self.traceability.references()

    def _read_iq(self, input_path: Path) -> np.ndarray:
        if not input_path.exists():
            raise FileNotFoundError(f"I/Q capture not found: {input_path}")
        return np.fromfile(input_path, dtype=np.complex64)

    def _region_matrix(self, matrix: np.ndarray, region: dict[str, Any]) -> np.ndarray:
        bounds = region.get("pixel_bounds", {})
        t0 = int(bounds.get("time_start", 0))
        t1 = int(bounds.get("time_end", matrix.shape[0] - 1))
        f0 = int(bounds.get("freq_start", 0))
        f1 = int(bounds.get("freq_end", matrix.shape[1] - 1))
        return matrix[max(t0, 0) : min(t1 + 1, matrix.shape[0]), max(f0, 0) : min(f1 + 1, matrix.shape[1])]

    def _summary(self, regions: list[dict[str, Any]], decisions: list[dict[str, Any]]) -> dict[str, Any]:
        labels: dict[str, int] = {}
        for decision in decisions:
            label = str(decision.get("final_label", "unknown"))
            labels[label] = labels.get(label, 0) + 1
        return {
            "region_count": len(regions),
            "labels": labels,
            "warning": "Labels are signal-type hypotheses, not confirmed protocol decoding.",
        }

    def _legacy_result(self, request: CompareWithRFIntelligenceRequest) -> dict[str, Any]:
        if request.legacy_frame:
            return self._legacy_result_from_frame(request.legacy_frame)
        return {
            "method": "band_profile_matching",
            "label": "unknown",
            "family": "unknown",
            "confidence": 0.0,
            "evidence": ["No legacy spectrum frame was supplied for rf_intelligence comparison."],
        }

    def _legacy_result_from_frame(self, raw_frame: dict[str, Any]) -> dict[str, Any]:
        frame = SpectrumFrameInput(
            timestamp_utc=raw_frame.get("timestamp_utc"),
            center_frequency_hz=raw_frame.get("center_frequency_hz", 0),
            span_hz=raw_frame.get("span_hz", 0),
            start_frequency_hz=raw_frame.get("start_frequency_hz"),
            stop_frequency_hz=raw_frame.get("stop_frequency_hz"),
            sample_rate_hz=raw_frame.get("sample_rate_hz"),
            frequencies_hz=raw_frame.get("frequencies_hz") or [],
            levels_db=raw_frame.get("levels_db") or [],
        )
        scene = self.legacy_service.analyze_frame(frame, RFIntelligenceSettings())
        if scene.detections:
            detection = scene.detections[0]
            return {
                "method": "band_profile_matching",
                "label": detection.label,
                "family": detection.candidate_family,
                "confidence": detection.confidence,
                "evidence": detection.evidence.notes,
            }
        return {
            "method": "band_profile_matching",
            "label": "unknown",
            "family": "unknown",
            "confidence": 0.0,
            "evidence": ["rf_intelligence did not detect an active object in the current live frame."],
        }

    def _evidence_lines(self, region: dict[str, Any]) -> list[str]:
        if not region:
            return ["No clear active time-frequency region detected."]
        classification = region.get("classification", {})
        features = region.get("features", {}).get("spectral", {})
        return [
            "active time-frequency region detected",
            f"visual classifier predicts {classification.get('visual_label', 'unknown')}",
            f"MLP temporal membership supports {classification.get('mlp_label', 'unknown')}",
            f"spectral features indicate occupied bandwidth {features.get('occupied_bandwidth_hz', 0.0):.1f} Hz",
        ]

    def _training_stub(self, request: TrainingRequest, task: str, metrics: list[str]) -> dict[str, Any]:
        return {
            "model_type": request.model_type,
            "model_id": request.model_id or f"{request.model_type}_v1",
            "dataset_path": request.dataset_path,
            "task": task,
            "status": "not_started",
            "metrics_required": metrics,
            "note": "Training endpoint is reserved; provide labeled waterfall regions before enabling model fitting.",
        }

    def _live_spectral_features(self, region_matrix: np.ndarray, region: dict[str, Any]) -> dict[str, float]:
        matrix = np.asarray(region_matrix, dtype=np.float32)
        if matrix.size == 0:
            snr_db = 0.0
            entropy = 0.0
            duty = 0.0
        else:
            power = np.maximum(matrix - np.min(matrix), 1e-9)
            probs = power.ravel() / np.sum(power)
            entropy = float(-np.sum(probs * np.log2(probs + 1e-12)) / max(np.log2(probs.size), 1.0))
            snr_db = float(np.percentile(matrix, 95) - np.percentile(matrix, 20))
            duty = float(np.mean(np.max(matrix, axis=1) > np.percentile(matrix, 75))) if matrix.ndim == 2 else 0.0
        return {
            "occupied_bandwidth_hz": float(region.get("occupied_bandwidth_hz", 0.0)),
            "spectral_centroid_hz": float(region.get("center_frequency_hz", 0.0)),
            "spectral_spread_hz": float(region.get("occupied_bandwidth_hz", 0.0)) / 2.0,
            "spectral_entropy": entropy,
            "spectral_kurtosis": 0.0,
            "peak_count": 0.0,
            "burst_duration_s": max(float(region.get("time_end_s", 0.0)) - float(region.get("time_start_s", 0.0)), 0.0),
            "duty_cycle": duty,
            "frequency_drift_hz": 0.0,
            "time_occupancy_ratio": duty,
            "snr_db": snr_db,
        }

    def _empty_live_result(self, raw_frame: dict[str, Any], reason: str) -> dict[str, Any]:
        return {
            "analysis_id": self.repository.new_analysis_id("rsu_live"),
            "mode": "live",
            "source": raw_frame.get("source", "real_sdr"),
            "timestamp_utc": raw_frame.get("timestamp_utc"),
            "input": {
                "center_frequency_hz": raw_frame.get("center_frequency_hz"),
                "sample_rate_hz": raw_frame.get("sample_rate_hz"),
                "span_hz": raw_frame.get("span_hz"),
                "format": "live_psd_waterfall",
            },
            "waterfall": {"rows": 0, "freq_bins": 0, "image_path": None, "note": reason},
            "regions": [],
            "summary": {"region_count": 0, "labels": {}, "warning": reason},
            "scientific_traceability": self.traceability.for_steps(["waterfall_generation", "region_detection"]),
        }
