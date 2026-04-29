from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AnalyzeCaptureRequest(BaseModel):
    file_path: str
    sample_rate_hz: float
    center_frequency_hz: float
    format: Literal["complex64", "cfile", "iq"] = "complex64"
    n_fft: int = 1024
    hop_length: int = 256
    window: str = "hann"
    analysis_id: str | None = None


class CompareWithRFIntelligenceRequest(AnalyzeCaptureRequest):
    legacy_frame: dict[str, Any] | None = None


class TrainingRequest(BaseModel):
    dataset_path: str | None = None
    model_type: Literal["region_detector", "waterfall_classifier", "mlp_spectral_classifier"] = "region_detector"
    model_id: str | None = None


class ValidationRequest(BaseModel):
    dataset_path: str | None = None
    task: Literal["region_detection", "signal_type_classification", "robustness", "transmitter_identification"] = "region_detection"


class ModelSummary(BaseModel):
    model_id: str
    model_type: str
    status: str
    path: str
    trained: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
