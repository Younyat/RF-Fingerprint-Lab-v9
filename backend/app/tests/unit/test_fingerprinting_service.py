import importlib.util
import tempfile
from pathlib import Path


def load_fingerprinting_service_class() -> type:
    service_path = Path(__file__).resolve().parents[2] / "modules" / "fingerprinting" / "service.py"
    spec = importlib.util.spec_from_file_location("fingerprinting_service_module", service_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.FingerprintingService


def test_burst_rf_v1_spectral_peak_detection_uses_warnings_not_doubtful() -> None:
    FingerprintingService = load_fingerprinting_service_class()
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = FingerprintingService(Path(tmp_dir))

    metrics = {
        "qc_profile_id": "burst_rf_v1",
        "signal_family": "burst_rf",
        "selected_snr_db": 17.06,
        "estimated_snr_db": 17.06,
        "clipping_pct": 0.0,
        "silence_pct": 0.0,
        "occupied_bandwidth_hz": 329_346.0,
        "effective_bandwidth_hz": 332_329.0,
        "capture_band_edge_margin_hz": 54_039.0,
        "frequency_offset_ratio_of_capture_band": 0.675,
        "signal_within_capture_band": True,
        "method": "spectral_peak_detection",
    }

    result = service._evaluate_quality(metrics, operator_decision=None)

    assert result["status"] == "valid"
    assert result["reasons"] == []
    assert "occupied_bandwidth_near_capture_limit" in result["flags"]
    assert "peak_not_ideally_centered" in result["flags"]


def test_pre_post_qc_mismatch_is_warning_not_reason() -> None:
    FingerprintingService = load_fingerprinting_service_class()
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = FingerprintingService(Path(tmp_dir))

    metrics = {
        "qc_profile_id": "burst_rf_v1",
        "signal_family": "burst_rf",
        "selected_snr_db": 18.0,
        "estimated_snr_db": 18.0,
        "clipping_pct": 0.0,
        "silence_pct": 0.0,
        "occupied_bandwidth_hz": 330_000.0,
        "effective_bandwidth_hz": 332_000.0,
        "capture_band_edge_margin_hz": 80_000.0,
        "frequency_offset_ratio_of_capture_band": 0.5,
        "signal_within_capture_band": True,
        "method": "spectral_peak_detection",
        "live_offset_hz": 100_000.0,
        "frequency_offset_hz": 50_000.0,
    }

    result = service._evaluate_quality(metrics, operator_decision=None)

    assert result["status"] == "valid"
    assert "pre_post_qc_mismatch" in result["flags"]
    assert "pre_post_qc_mismatch" not in result["reasons"]


def test_high_margin_burst_rf_capture_with_occupied_bandwidth_warning_is_valid() -> None:
    FingerprintingService = load_fingerprinting_service_class()
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = FingerprintingService(Path(tmp_dir))

    metrics = {
        "qc_profile_id": "burst_rf_v1",
        "signal_family": "burst_rf",
        "selected_snr_db": 16.5,
        "estimated_snr_db": 16.5,
        "clipping_pct": 0.0,
        "silence_pct": 0.0,
        "occupied_bandwidth_hz": 370_840.0,
        "effective_bandwidth_hz": 374_584.0,
        "capture_band_edge_margin_hz": 97_970.0,
        "frequency_offset_ratio_of_capture_band": 0.239,
        "signal_within_capture_band": True,
        "method": "spectral_peak_detection",
        "live_offset_hz": 0.0,
        "frequency_offset_hz": 0.0,
    }

    result = service._evaluate_quality(metrics, operator_decision=None)

    assert result["status"] == "valid"
    assert result["reasons"] == []
    assert "occupied_bandwidth_near_capture_limit" in result["flags"]
