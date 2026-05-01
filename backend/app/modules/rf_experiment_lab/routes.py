from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field


class ExperimentConfigBody(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


class RegionDetectionBody(BaseModel):
    waterfall_matrix: list[list[float]]
    time_axis_s: list[float] = Field(default_factory=list)
    freq_axis_hz: list[float] = Field(default_factory=list)
    mode: str = "morphological_heuristic"
    parameters: dict[str, Any] = Field(default_factory=dict)


class ForensicReportBody(BaseModel):
    case_id: str = "rf_case_unassigned"
    evidence_id: str = "rf_capture_unassigned"
    raw_iq_path: str | None = None
    metadata_path: str | None = None
    detector_mode: str = "morphological_heuristic"
    stage_1_result: dict[str, Any] = Field(default_factory=dict)
    stage_2_result: dict[str, Any] = Field(default_factory=dict)


class SigMFExportBody(BaseModel):
    iq_path: str | None = None
    cfile_path: str | None = None
    metadata_path: str
    output_dir: str | None = None


class HDF5ExportBody(BaseModel):
    output_path: str | None = None
    dataset_id: str = "rf_experiment_dataset"
    dataset_version: str = "experiment_dataset_v0.1"
    capture_ids: list[str] = Field(default_factory=list)
    representations: list[str] = Field(default_factory=lambda: ["raw_iq", "spectrogram", "waterfall", "fft_psd"])
    split_strategy: str = "metadata_or_session_disjoint"
    label_schema: dict[str, Any] = Field(default_factory=dict)
    qc_policy: str = "accepted_for_training_doubtful_for_robustness_rejected_excluded"
    notes: str = ""


class DryRunPreviewBody(BaseModel):
    metadata_path: str
    template_id: str = "morphological_baseline"
    experiment_config: dict[str, Any] | None = None
    waterfall_matrix: list[list[float]] = Field(default_factory=list)
    time_axis_s: list[float] = Field(default_factory=list)
    freq_axis_hz: list[float] = Field(default_factory=list)


class E0MorphologicalBaselineBody(BaseModel):
    metadata_path: str
    experiment_config: dict[str, Any] | None = None
    waterfall_matrix: list[list[float]] | None = None
    waterfall_matrix_path: str | None = None
    spectrogram_matrix_path: str | None = None
    time_axis_s: list[float] = Field(default_factory=list)
    freq_axis_hz: list[float] = Field(default_factory=list)
    annotations: list[dict[str, Any]] = Field(default_factory=list)


class RepresentationBody(BaseModel):
    metadata_path: str
    iq_path: str | None = None
    raw_file: str | None = None
    output_dir: str | None = None
    window_size_samples: int = 65536
    overlap: float = 0.0
    start_sample: int = 0
    max_preview_windows: int = 1
    max_export_windows: int = 32
    n_fft: int = 1024
    hop_length: int = 512
    window_type: str = "hann"
    welch_nperseg: int = 1024
    normalization: str = "none"


class RepresentationManifestBody(BaseModel):
    metadata_path: str
    iq_path: str | None = None
    raw_file: str | None = None
    output_dir: str | None = None
    dataset_id: str = "rf_experiment_dataset"
    dataset_version: str = "unversioned"
    artifact_paths: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)


class E5SpectralBaselineBody(BaseModel):
    dataset_version: str = "unversioned"
    capture_ids: list[str] = Field(default_factory=list)
    input_representation: str = "fft_psd"
    feature_set: str = "psd_basic"
    models: list[str] = Field(default_factory=lambda: ["logistic_regression", "random_forest", "svm_rbf", "knn"])
    label_field: str = "transmitter_id"
    split: dict[str, Any] = Field(default_factory=lambda: {"strategy": "session_disjoint", "group_by": ["session_id"]})
    window_size_samples: int = 4096
    overlap: float = 0.0
    n_fft: int = 1024
    welch_nperseg: int = 1024
    force_sklearn_unavailable: bool = False


class E1RawIQCNN1DBody(BaseModel):
    dataset_version: str = "unversioned"
    capture_ids: list[str] = Field(default_factory=list)
    label_field: str = "transmitter_id"
    split: dict[str, Any] = Field(default_factory=lambda: {"strategy": "session_disjoint", "group_by": ["session_id"]})
    window_size_samples: int = 2048
    overlap: float = 0.0
    max_windows: int = 128
    epochs: int = 30
    batch_size: int = 32
    learning_rate: float = 0.001
    optimizer: str = "adam"
    weight_decay: float = 0.0
    early_stopping: bool = True
    patience: int = 5
    seed: int = 42
    device: str = "auto"
    force_torch_unavailable: bool = False


class E3SpectrogramCNN2DBody(BaseModel):
    dataset_version: str = "unversioned"
    capture_ids: list[str] = Field(default_factory=list)
    task: str = "device_fingerprinting"
    input_representation: str = "spectrogram"
    label_field: str | None = None
    split: dict[str, Any] = Field(default_factory=lambda: {"strategy": "session_disjoint", "group_by": ["session_id"]})
    window_size_samples: int = 4096
    overlap: float = 0.0
    max_samples: int = 128
    n_fft: int = 256
    hop_length: int = 128
    window_type: str = "hann"
    image_height: int = 128
    image_width: int = 128
    normalization_mode: str = "per_sample_standardization"
    epochs: int = 30
    batch_size: int = 32
    learning_rate: float = 0.001
    optimizer: str = "adam"
    weight_decay: float = 0.0
    early_stopping: bool = True
    patience: int = 5
    seed: int = 42
    device: str = "auto"
    force_torch_unavailable: bool = False


class ExperimentCompareBody(BaseModel):
    experiment_ids: list[str] = Field(default_factory=list)
    metric: str = "macro_f1"


class BenchmarkReportBody(BaseModel):
    experiment_ids: list[str] = Field(default_factory=list)
    sort_metric: str = "macro_f1"
    include_predictions_summary: bool = False
    include_group_metrics: bool = False
    include_confusion_matrices: bool = False
    output_format: str = "json"
    export: bool = False


def _ok(data: Any, message: str = "ok", available: bool = True, status: str = "ok") -> dict[str, Any]:
    return {
        "status": status,
        "module": "rf_experiment_lab",
        "available": available,
        "message": message,
        "data": data,
        "errors": [],
    }


def _error(exc: Exception, status: str = "error", available: bool = True) -> dict[str, Any]:
    return {
        "status": status,
        "module": "rf_experiment_lab",
        "available": available,
        "message": str(exc),
        "data": None,
        "errors": [{"type": exc.__class__.__name__, "message": str(exc)}],
    }


def build_rf_experiment_lab_router(service) -> APIRouter:
    router = APIRouter(prefix="/rf-experiment-lab", tags=["rf-experiment-lab"])

    @router.get("/overview")
    async def overview() -> dict[str, Any]:
        return _ok(service.overview(), "RF Experiment Lab overview")

    @router.get("/health")
    async def health() -> dict[str, Any]:
        return _ok(service.health(), "RF Experiment Lab health")

    @router.get("/dataset/summary")
    async def dataset_summary() -> dict[str, Any]:
        return _ok(service.dataset_adapter.dataset_summary(), "Dataset adapter summary")

    @router.get("/dataset/captures")
    async def dataset_captures() -> list[dict[str, Any]]:
        return _ok(service.dataset_adapter.list_existing_captures(), "Existing captures visible to RF Experiment Lab")

    @router.get("/techniques")
    async def techniques() -> list[dict[str, Any]]:
        return _ok(service.registry.list_techniques(), "Registered paper-inspired techniques")

    @router.get("/region-detectors")
    async def region_detectors() -> list[dict[str, Any]]:
        return _ok(service.registry.list_region_detectors(), "Registered region detectors")

    @router.get("/configs")
    async def list_configs() -> list[dict[str, Any]]:
        return _ok(service.list_configs(), "Experiment configs")

    @router.get("/configs/template/{template_id}")
    async def config_template(template_id: str) -> dict[str, Any]:
        try:
            return _ok(service.create_template(template_id), "Experiment config template")
        except Exception as exc:
            return _error(exc, status="not_found")

    @router.post("/configs")
    async def save_config(body: ExperimentConfigBody) -> dict[str, Any]:
        try:
            return _ok(service.save_config(body.payload), "Experiment config saved")
        except Exception as exc:
            return _error(exc)

    @router.get("/configs/{experiment_id}")
    async def get_config(experiment_id: str) -> dict[str, Any]:
        try:
            return _ok(service.get_config(experiment_id), "Experiment config loaded")
        except Exception as exc:
            return _error(exc, status="not_found")

    @router.get("/results")
    async def results() -> list[dict[str, Any]]:
        return _ok(service.list_results(), "Experiment results")

    @router.get("/experiments")
    async def list_experiments() -> dict[str, Any]:
        return _ok(service.list_experiments(), "Executed RF Experiment Lab experiments")

    @router.get("/experiments/{experiment_id}")
    async def experiment_detail(experiment_id: str) -> dict[str, Any]:
        try:
            return _ok(service.get_experiment_detail(experiment_id), "Experiment detail loaded")
        except Exception as exc:
            return _error(exc, status="not_found")

    @router.post("/experiments/compare")
    async def compare_experiments(body: ExperimentCompareBody) -> dict[str, Any]:
        try:
            return _ok(service.compare_experiments(body.model_dump()), "Experiment comparison completed")
        except Exception as exc:
            return _error(exc)

    @router.post("/benchmark/report")
    async def benchmark_report(body: BenchmarkReportBody) -> dict[str, Any]:
        try:
            return _ok(service.benchmark_report(body.model_dump()), "Benchmark report generated")
        except Exception as exc:
            return _error(exc)

    @router.post("/dry-run/preview")
    async def dry_run_preview(body: DryRunPreviewBody) -> dict[str, Any]:
        try:
            return _ok(service.dry_run_preview(body.model_dump()), "Dry-run preview completed without training")
        except Exception as exc:
            return _error(exc)

    @router.post("/experiments/e0-morphological-baseline/preview")
    async def e0_morphological_baseline_preview(body: E0MorphologicalBaselineBody) -> dict[str, Any]:
        try:
            return _ok(
                service.e0_morphological_baseline_preview(body.model_dump()),
                "E0 morphological baseline preview completed without training",
            )
        except Exception as exc:
            return _error(exc)

    @router.post("/experiments/e0-morphological-baseline/run")
    async def e0_morphological_baseline_run(body: E0MorphologicalBaselineBody) -> dict[str, Any]:
        try:
            return _ok(
                service.e0_morphological_baseline_run(body.model_dump()),
                "E0 morphological baseline run completed",
            )
        except Exception as exc:
            return _error(exc)

    @router.post("/experiments/e5-spectral-baseline/preview")
    async def e5_spectral_baseline_preview(body: E5SpectralBaselineBody) -> dict[str, Any]:
        try:
            return _ok(
                service.e5_spectral_baseline_preview(body.model_dump()),
                "E5 spectral feature baseline preview completed without training",
            )
        except Exception as exc:
            return _error(exc)

    @router.post("/experiments/e5-spectral-baseline/run")
    async def e5_spectral_baseline_run(body: E5SpectralBaselineBody) -> dict[str, Any]:
        try:
            return _ok(
                service.e5_spectral_baseline_run(body.model_dump()),
                "E5 spectral feature baseline run completed",
            )
        except Exception as exc:
            return _error(exc)

    @router.post("/experiments/e1-raw-iq-cnn1d/preview")
    async def e1_raw_iq_cnn1d_preview(body: E1RawIQCNN1DBody) -> dict[str, Any]:
        try:
            return _ok(
                service.e1_raw_iq_cnn1d_preview(body.model_dump()),
                "E1 Raw IQ CNN 1D preview completed without training",
            )
        except Exception as exc:
            return _error(exc)

    @router.post("/experiments/e1-raw-iq-cnn1d/run")
    async def e1_raw_iq_cnn1d_run(body: E1RawIQCNN1DBody) -> dict[str, Any]:
        try:
            return _ok(
                service.e1_raw_iq_cnn1d_run(body.model_dump()),
                "E1 Raw IQ CNN 1D run completed",
            )
        except Exception as exc:
            return _error(exc)

    @router.post("/experiments/e3-spectrogram-cnn2d/preview")
    async def e3_spectrogram_cnn2d_preview(body: E3SpectrogramCNN2DBody) -> dict[str, Any]:
        try:
            return _ok(
                service.e3_spectrogram_cnn2d_preview(body.model_dump()),
                "E3 Spectrogram/Waterfall CNN 2D preview completed without training",
            )
        except Exception as exc:
            return _error(exc)

    @router.post("/experiments/e3-spectrogram-cnn2d/run")
    async def e3_spectrogram_cnn2d_run(body: E3SpectrogramCNN2DBody) -> dict[str, Any]:
        try:
            return _ok(
                service.e3_spectrogram_cnn2d_run(body.model_dump()),
                "E3 Spectrogram/Waterfall CNN 2D run completed",
            )
        except Exception as exc:
            return _error(exc)

    @router.post("/experiments/{experiment_id}/run")
    async def run_experiment(experiment_id: str, dry_run: bool = Query(default=True)) -> dict[str, Any]:
        try:
            result = service.run_experiment(experiment_id, dry_run=dry_run)
            return _ok(result, "Dry-run experiment completed" if dry_run else "Experiment request handled")
        except Exception as exc:
            return _error(exc)

    @router.post("/region-detection/detect")
    async def detect_regions(body: RegionDetectionBody) -> dict[str, Any]:
        try:
            result = service.detect_regions(body.waterfall_matrix, body.time_axis_s, body.freq_axis_hz, body.mode, body.parameters)
            status = "not_implemented" if result.get("status") == "not_implemented" else "ok"
            return _ok(result, result.get("message", "Region detection completed"), available=status == "ok", status=status)
        except Exception as exc:
            return _error(exc)

    @router.post("/representations/raw-iq/preview")
    async def raw_iq_preview(body: RepresentationBody) -> dict[str, Any]:
        return _representation_response(service, "raw_iq", body.model_dump(), preview=True)

    @router.post("/representations/raw-iq/export")
    async def raw_iq_export(body: RepresentationBody) -> dict[str, Any]:
        return _representation_response(service, "raw_iq", body.model_dump(), preview=False)

    @router.post("/representations/fft-psd/preview")
    async def fft_psd_preview(body: RepresentationBody) -> dict[str, Any]:
        return _representation_response(service, "fft_psd", body.model_dump(), preview=True)

    @router.post("/representations/fft-psd/export")
    async def fft_psd_export(body: RepresentationBody) -> dict[str, Any]:
        return _representation_response(service, "fft_psd", body.model_dump(), preview=False)

    @router.post("/representations/spectrogram/preview")
    async def spectrogram_preview(body: RepresentationBody) -> dict[str, Any]:
        return _representation_response(service, "spectrogram", body.model_dump(), preview=True)

    @router.post("/representations/spectrogram/export")
    async def spectrogram_export(body: RepresentationBody) -> dict[str, Any]:
        return _representation_response(service, "spectrogram", body.model_dump(), preview=False)

    @router.post("/representations/waterfall/preview")
    async def waterfall_preview(body: RepresentationBody) -> dict[str, Any]:
        return _representation_response(service, "waterfall", body.model_dump(), preview=True)

    @router.post("/representations/waterfall/export")
    async def waterfall_export(body: RepresentationBody) -> dict[str, Any]:
        return _representation_response(service, "waterfall", body.model_dump(), preview=False)

    @router.post("/representations/manifest/export")
    async def representations_manifest_export(body: RepresentationManifestBody) -> dict[str, Any]:
        try:
            return _ok(service.representation_manifest_export(body.model_dump()), "Representations manifest exported")
        except Exception as exc:
            return _error(exc)

    @router.post("/forensics/report")
    async def forensic_report(body: ForensicReportBody) -> dict[str, Any]:
        return _ok(service.build_forensic_report(body.model_dump()), "Forensic report preview")

    @router.post("/sigmf/preview")
    async def sigmf_preview(body: SigMFExportBody) -> dict[str, Any]:
        try:
            return _ok(service.sigmf_preview(body.model_dump()), "SigMF preview completed")
        except Exception as exc:
            return _error(exc)

    @router.post("/sigmf/export")
    async def sigmf_export(body: SigMFExportBody) -> dict[str, Any]:
        try:
            return _ok(service.sigmf_export(body.model_dump()), "SigMF export completed")
        except Exception as exc:
            return _error(exc)

    @router.post("/hdf5-manifest/preview")
    async def hdf5_manifest_preview(body: HDF5ExportBody) -> dict[str, Any]:
        try:
            result = service.hdf5_manifest_preview(body.model_dump())
            return _ok(result, "HDF5 experiment manifest preview completed", available=result.get("available", True))
        except Exception as exc:
            return _error(exc)

    @router.post("/hdf5-manifest/export")
    async def hdf5_manifest_export(body: HDF5ExportBody) -> dict[str, Any]:
        try:
            result = service.hdf5_manifest_export(body.model_dump())
            return _ok(result, "HDF5 experiment manifest export completed", available=result.get("available", True))
        except Exception as exc:
            return _error(exc)

    @router.post("/dataset-version/preview")
    async def dataset_version_preview(body: HDF5ExportBody) -> dict[str, Any]:
        try:
            return _ok(service.dataset_version_preview(body.model_dump()), "Dataset version preview completed")
        except Exception as exc:
            return _error(exc)

    @router.post("/exports/sigmf")
    async def export_sigmf(body: SigMFExportBody) -> dict[str, Any]:
        try:
            return _ok(service.export_sigmf(body.model_dump()), "SigMF export completed")
        except Exception as exc:
            return _error(exc)

    @router.post("/exports/hdf5-manifest")
    async def export_hdf5_manifest(body: HDF5ExportBody) -> dict[str, Any]:
        try:
            return _ok(service.export_hdf5_manifest(body.model_dump()), "HDF5 manifest export completed")
        except Exception as exc:
            return _error(exc)

    return router


def _representation_response(service, representation_type: str, payload: dict[str, Any], preview: bool) -> dict[str, Any]:
    try:
        data = service.representation_preview(representation_type, payload) if preview else service.representation_export(representation_type, payload)
        action = "preview" if preview else "export"
        return _ok(data, f"{representation_type} representation {action} completed")
    except Exception as exc:
        return _error(exc)
