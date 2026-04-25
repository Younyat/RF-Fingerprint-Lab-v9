from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np


DEFAULT_THRESHOLDS = {
    "min_valid_snr_db": 12.0,
    "min_doubtful_snr_db": 6.0,
    "max_valid_clipping_pct": 0.5,
    "max_doubtful_clipping_pct": 2.0,
    "max_valid_frequency_offset_hz": 5_000.0,
    "max_doubtful_frequency_offset_hz": 20_000.0,
    "min_valid_burst_duration_ms": 1.0,
    "max_silence_pct": 85.0,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _db10(value: float) -> float:
    return 10.0 * np.log10(max(float(value), 1e-20))


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(parsed):
        return None
    return parsed


class FingerprintingService:
    def __init__(self, storage_root: Path) -> None:
        self._root = storage_root
        self._captures_dir = self._root / "captures"
        self._captures_dir.mkdir(parents=True, exist_ok=True)
        self._workspace_root = self._root.parents[5]

    def get_dashboard_summary(self) -> dict[str, Any]:
        captures = self.list_capture_records()
        by_split = {
            "train": sum(1 for item in captures if item.get("dataset_split") == "train"),
            "val": sum(1 for item in captures if item.get("dataset_split") == "val"),
            "predict": sum(1 for item in captures if item.get("dataset_split") == "predict"),
        }
        return {
            "modes": [
                {
                    "id": "live_monitor",
                    "title": "Live Monitor",
                    "goal": "Tune the SDR, observe spectrum occupancy, verify live signal presence, and stabilize RF settings.",
                },
                {
                    "id": "guided_capture",
                    "title": "Guided Capture",
                    "goal": "Acquire labeled transmitter bursts with reproducible receiver settings and mandatory metadata.",
                },
                {
                    "id": "dataset_builder",
                    "title": "Dataset Builder",
                    "goal": "Review captures, reject weak acquisitions, segment regions of interest, and export curated datasets.",
                },
            ],
            "thresholds": deepcopy(DEFAULT_THRESHOLDS),
            "summary": {
                "total_captures": len(captures),
                "valid_captures": sum(1 for item in captures if item["quality_review"]["status"] == "valid"),
                "doubtful_captures": sum(1 for item in captures if item["quality_review"]["status"] == "doubtful"),
                "rejected_captures": sum(1 for item in captures if item["quality_review"]["status"] == "rejected"),
                "by_split": by_split,
            },
            "required_metadata": [
                "transmitter_id",
                "transmitter_class",
                "session_id",
                "sdr_model",
                "sdr_serial",
                "center_frequency_hz",
                "sample_rate_hz",
                "gain_settings",
                "capture_duration_s",
                "estimated_snr_db",
                "quality_flags",
                "sha256",
            ],
        }

    def list_capture_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in sorted(self._captures_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                records.append(self._load_record(path))
            except Exception:
                continue
        return records

    def list_capture_records_by_split(self, dataset_split: str) -> list[dict[str, Any]]:
        normalized = self._normalize_split(dataset_split)
        return [item for item in self.list_capture_records() if item.get("dataset_split") == normalized]

    def get_capture_record(self, capture_id: str) -> dict[str, Any]:
        path = self._capture_path(capture_id)
        if not path.exists():
            raise ValueError(f"Fingerprinting capture not found: {capture_id}")
        return self._load_record(path)

    def create_capture_record(self, payload: dict[str, Any]) -> dict[str, Any]:
        record = self._normalize_record(payload, capture_id=payload.get("capture_id"))
        self._save_record(record)
        return record

    def review_capture_record(self, capture_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        record = self.get_capture_record(capture_id)
        quality_review = record["quality_review"]
        quality_review["operator_decision"] = payload.get("operator_decision", quality_review.get("operator_decision"))
        quality_review["review_notes"] = payload.get("review_notes", quality_review.get("review_notes", ""))
        quality_review["export_windows"] = payload.get("export_windows", quality_review.get("export_windows", []))
        quality_review["updated_at_utc"] = _utc_now()
        evaluated = self._evaluate_quality(record["quality_metrics"], quality_review["operator_decision"])
        quality_review["status"] = evaluated["status"]
        quality_review["reasons"] = evaluated["reasons"]
        quality_review["quality_flags"] = evaluated["flags"]
        self._save_record(record)
        return record

    def delete_capture_record(self, capture_id: str, delete_artifacts: bool = True) -> dict[str, Any]:
        path = self._capture_path(capture_id)
        if not path.exists():
            raise ValueError(f"Fingerprinting capture not found: {capture_id}")
        record = self._load_record(path)
        removed_files: list[str] = []
        if delete_artifacts:
            removed_files = self._delete_unreferenced_artifacts(record, excluded_capture_id=capture_id)
        path.unlink()
        return {
            "capture_id": capture_id,
            "deleted": True,
            "deleted_artifacts": removed_files,
        }

    def recompute_capture_record_qc(self, capture_id: str) -> dict[str, Any]:
        record = self.get_capture_record(capture_id)
        iq_path = (
            str((record.get("artifacts") or {}).get("iq_file") or "").strip()
            or str((record.get("capture_config") or {}).get("output_path") or "").strip()
        )
        capture_like = {
            "iq_file": iq_path,
            "iq_dtype": (record.get("capture_config") or {}).get("sample_dtype", "complex64"),
            "sample_rate_hz": (record.get("capture_config") or {}).get("sample_rate_hz", 0.0),
            "center_frequency_hz": (record.get("capture_config") or {}).get("center_frequency_hz", 0.0),
            "duration_seconds": (record.get("capture_config") or {}).get("capture_duration_s", 0.0),
            "sample_count": (record.get("capture_config") or {}).get("sample_count", 0),
        }
        analysis = self._analyze_imported_capture(capture_like)
        if not analysis:
            raise ValueError(f"Unable to recompute QC for capture: {capture_id}")

        quality_metrics = record.get("quality_metrics", {})
        quality_metrics["estimated_snr_db"] = float(analysis.get("estimated_snr_db", quality_metrics.get("estimated_snr_db", 0.0) or 0.0))
        quality_metrics["spectral_snr_db"] = _safe_float(analysis.get("spectral_snr_db"))
        quality_metrics["noise_floor_db"] = _safe_float(analysis.get("noise_floor_db"))
        quality_metrics["peak_power_db"] = _safe_float(analysis.get("peak_power_db"))
        quality_metrics["average_power_db"] = _safe_float(analysis.get("average_power_db"))
        quality_metrics["occupied_bandwidth_hz"] = _safe_float(analysis.get("occupied_bandwidth_hz"))
        quality_metrics["peak_frequency_hz"] = _safe_float(analysis.get("peak_frequency_hz"))
        quality_metrics["frequency_offset_hz"] = float(analysis.get("frequency_offset_hz", quality_metrics.get("frequency_offset_hz", 0.0) or 0.0))
        quality_metrics["clipping_pct"] = float(analysis.get("clipping_pct", quality_metrics.get("clipping_pct", 0.0) or 0.0))
        quality_metrics["silence_pct"] = float(analysis.get("silence_pct", quality_metrics.get("silence_pct", 0.0) or 0.0))
        quality_metrics["burst_duration_ms"] = float(analysis.get("burst_duration_ms", quality_metrics.get("burst_duration_ms", 0.0) or 0.0))

        burst_detection = record.get("burst_detection", {})
        burst_detection["method"] = analysis.get("method", burst_detection.get("method", "manual"))
        burst_detection["energy_threshold_db"] = _safe_float(analysis.get("energy_threshold_db"))
        burst_detection["burst_count"] = int(analysis.get("burst_count", burst_detection.get("burst_count", 0) or 0))
        burst_detection["burst_start_sample"] = int(analysis.get("burst_start_sample", burst_detection.get("burst_start_sample", 0) or 0))
        burst_detection["burst_end_sample"] = int(analysis.get("burst_end_sample", burst_detection.get("burst_end_sample", 0) or 0))
        burst_detection["regions_of_interest"] = list(analysis.get("regions_of_interest", burst_detection.get("regions_of_interest", [])))
        burst_detection["max_burst_duration_ms"] = float(
            analysis.get("burst_duration_ms", burst_detection.get("max_burst_duration_ms", quality_metrics.get("burst_duration_ms", 0.0)) or 0.0)
        ) or burst_detection.get("max_burst_duration_ms")

        quality_review = record.get("quality_review", {})
        evaluated = self._evaluate_quality(quality_metrics, quality_review.get("operator_decision"))
        quality_review["status"] = evaluated["status"]
        quality_review["reasons"] = evaluated["reasons"]
        quality_review["quality_flags"] = evaluated["flags"]
        quality_review["updated_at_utc"] = _utc_now()

        self._save_record(record)
        return record

    def import_modulated_capture(self, capture: dict[str, Any], defaults: dict[str, Any] | None = None) -> dict[str, Any]:
        defaults = defaults or {}
        center_frequency_hz = float(capture.get("center_frequency_hz", 0.0))
        sample_rate_hz = float(capture.get("sample_rate_hz", 0.0))
        bandwidth_hz = float(capture.get("bandwidth_hz", sample_rate_hz))
        analysis = self._analyze_imported_capture(capture)
        burst_duration_ms = float(
            defaults.get("burst_duration_ms", analysis.get("burst_duration_ms", float(capture.get("duration_seconds", 0.0)) * 1000.0))
        )
        payload = {
            "capture_id": capture.get("id") or f"imported-{uuid4().hex[:12]}",
            "capture_mode": "guided_capture",
            "session_id": defaults.get("session_id", "session_unassigned"),
            "dataset_split": defaults.get("dataset_split", "train"),
            "capture_config": {
                "device_source": defaults.get("device_source", capture.get("source_device", "uhd")),
                "sdr_model": defaults.get("sdr_model", capture.get("driver", "uhd_gnuradio")),
                "sdr_serial": defaults.get("sdr_serial", "unknown"),
                "antenna_port": defaults.get("antenna_port", capture.get("antenna", "RX2")),
                "capture_type": defaults.get("capture_type", capture.get("capture_type", "iq_file")),
                "center_frequency_hz": center_frequency_hz,
                "sample_rate_hz": sample_rate_hz,
                "effective_bandwidth_hz": bandwidth_hz,
                "frontend_bandwidth_hz": defaults.get("frontend_bandwidth_hz", bandwidth_hz),
                "gain_mode": defaults.get("gain_mode", "manual"),
                "gain_settings": {
                    "lna_db": defaults.get("lna_db"),
                    "vga_db": defaults.get("vga_db"),
                    "if_db": defaults.get("if_db"),
                    "composite_gain_db": capture.get("gain_db"),
                },
                "ppm_correction": defaults.get("ppm_correction", 0.0),
                "lo_offset_hz": defaults.get("lo_offset_hz", 0.0),
                "capture_duration_s": capture.get("duration_seconds", 0.0),
                "sample_count": capture.get("sample_count", 0),
                "file_format": capture.get("file_extension", capture.get("capture_type", "cfile")),
                "sample_dtype": capture.get("iq_dtype", "complex64"),
                "byte_order": capture.get("byte_order", "native"),
                "channel_count": defaults.get("channel_count", 1),
                "output_path": capture.get("iq_file", ""),
            },
            "transmitter": {
                "transmitter_label": defaults.get("transmitter_label", capture.get("label", "unlabeled_transmitter")),
                "transmitter_class": defaults.get("transmitter_class", capture.get("modulation_hint", "unknown")),
                "transmitter_id": defaults.get("transmitter_id", capture.get("label", "tx_unknown")),
                "family": defaults.get("family", "unknown"),
                "ground_truth_confidence": defaults.get("ground_truth_confidence", "unknown"),
            },
            "scenario": {
                "operator": defaults.get("operator", "unknown"),
                "environment": defaults.get("environment", "unspecified"),
                "distance_m": defaults.get("distance_m"),
                "line_of_sight": defaults.get("line_of_sight"),
                "indoor": defaults.get("indoor"),
                "notes": defaults.get("notes", capture.get("notes", "")),
                "session_number": defaults.get("session_number", 1),
                "timestamp_utc": capture.get("generated_at_utc", _utc_now()),
            },
            "quality_metrics": {
                "estimated_snr_db": defaults.get("estimated_snr_db", analysis.get("estimated_snr_db", 0.0)),
                "spectral_snr_db": defaults.get("spectral_snr_db", analysis.get("spectral_snr_db")),
                "noise_floor_db": defaults.get("noise_floor_db", analysis.get("noise_floor_db")),
                "peak_power_db": defaults.get("peak_power_db", analysis.get("peak_power_db")),
                "average_power_db": defaults.get("average_power_db", analysis.get("average_power_db")),
                "occupied_bandwidth_hz": defaults.get("occupied_bandwidth_hz", analysis.get("occupied_bandwidth_hz", bandwidth_hz)),
                "peak_frequency_hz": defaults.get("peak_frequency_hz", analysis.get("peak_frequency_hz", center_frequency_hz)),
                "frequency_offset_hz": defaults.get("frequency_offset_hz", analysis.get("frequency_offset_hz", 0.0)),
                "clipping_pct": defaults.get("clipping_pct", analysis.get("clipping_pct", 0.0)),
                "sample_drop_count": defaults.get("sample_drop_count", 0),
                "buffer_overflow_count": defaults.get("buffer_overflow_count", 0),
                "silence_pct": defaults.get("silence_pct", analysis.get("silence_pct", 0.0)),
                "peak_to_average_ratio_db": defaults.get("peak_to_average_ratio_db", None),
                "kurtosis": defaults.get("kurtosis", None),
                "burst_duration_ms": burst_duration_ms,
            },
            "burst_detection": {
                "method": defaults.get("method", analysis.get("method", "manual_import")),
                "energy_threshold_db": defaults.get("energy_threshold_db", analysis.get("energy_threshold_db")),
                "pre_trigger_samples": defaults.get("pre_trigger_samples", 0),
                "post_trigger_samples": defaults.get("post_trigger_samples", 0),
                "min_burst_duration_ms": defaults.get("min_burst_duration_ms", 1.0),
                "max_burst_duration_ms": defaults.get("max_burst_duration_ms", burst_duration_ms or None),
                "burst_count": defaults.get("burst_count", analysis.get("burst_count", 1)),
                "regions_of_interest": defaults.get("regions_of_interest", analysis.get("regions_of_interest", ["whole_burst"])),
                "burst_start_sample": defaults.get("burst_start_sample", analysis.get("burst_start_sample", 0)),
                "burst_end_sample": defaults.get("burst_end_sample", analysis.get("burst_end_sample", capture.get("sample_count", 0))),
            },
            "artifacts": {
                "iq_file": capture.get("iq_file"),
                "metadata_file": capture.get("metadata_file"),
                "sha256": capture.get("sha256"),
                "source_capture_id": capture.get("id"),
            },
            "preview_metrics": {
                "live_preview_snr_db": _safe_float((capture.get("preview_metrics") or {}).get("live_preview_snr_db")),
                "live_preview_noise_floor_db": _safe_float((capture.get("preview_metrics") or {}).get("live_preview_noise_floor_db")),
                "live_preview_peak_level_db": _safe_float((capture.get("preview_metrics") or {}).get("live_preview_peak_level_db")),
                "live_preview_peak_frequency_hz": _safe_float((capture.get("preview_metrics") or {}).get("live_preview_peak_frequency_hz")),
            },
        }
        return self.create_capture_record(payload)

    def _analyze_imported_capture(self, capture: dict[str, Any]) -> dict[str, Any]:
        iq_file = Path(str(capture.get("iq_file", "")).strip())
        if not iq_file.exists():
            return {}

        sample_rate_hz = float(capture.get("sample_rate_hz", 0.0) or 0.0)
        center_frequency_hz = float(capture.get("center_frequency_hz", 0.0) or 0.0)
        if sample_rate_hz <= 0.0:
            return {}

        samples = self._load_complex_samples(iq_file, str(capture.get("iq_dtype", "complex64")))
        if samples.size == 0:
            return {}

        power = np.abs(samples) ** 2
        mean_power = float(np.mean(power))
        if not np.isfinite(mean_power) or mean_power <= 0.0:
            return {}

        noise_power = float(np.percentile(power, 20))
        avg_power_db = _db10(mean_power)
        noise_floor_db = _db10(noise_power)
        peak_power_db = _db10(float(np.max(power)))
        clipping_pct = float(np.mean((np.abs(samples.real) >= 0.999) | (np.abs(samples.imag) >= 0.999)) * 100.0)

        window = int(min(max(sample_rate_hz * 0.0005, 64), 4096))
        kernel = np.ones(window, dtype=np.float64) / window
        smoothed = np.convolve(power.astype(np.float64), kernel, mode="same")
        energy_threshold_power = max(noise_power * (10.0 ** (6.0 / 10.0)), 1e-20)
        mask = smoothed > energy_threshold_power

        burst_start, burst_end, burst_count = self._find_burst_bounds(mask)
        burst_detected = burst_start is not None and burst_end is not None
        if burst_start is None or burst_end is None:
            burst_start = 0
            burst_end = samples.size - 1
            burst_count = 0

        silence_pct = float(np.mean(~mask) * 100.0) if mask.size > 0 else 0.0
        burst_duration_ms = max(0.0, ((burst_end - burst_start + 1) / sample_rate_hz) * 1000.0)

        signal_slice = samples[burst_start:burst_end + 1] if burst_end >= burst_start else samples
        signal_power = float(np.mean(np.abs(signal_slice) ** 2)) if signal_slice.size else mean_power
        noise_reference = power[~mask] if np.any(~mask) else power
        reference_noise_power = float(np.mean(noise_reference)) if noise_reference.size else noise_power
        signal_excess_power = max(signal_power - reference_noise_power, 0.0)
        estimated_snr_db = _db10(signal_excess_power / max(reference_noise_power, 1e-20))
        if not burst_detected or silence_pct >= 99.9:
            estimated_snr_db = 0.0

        spectral_samples = signal_slice if signal_slice.size else samples
        if spectral_samples.size > 262144:
            stride = int(np.ceil(spectral_samples.size / 262144))
            spectral_samples = spectral_samples[::stride]

        windowed = spectral_samples * np.hanning(spectral_samples.size)
        spectrum = np.fft.fftshift(np.fft.fft(windowed))
        psd = np.abs(spectrum) ** 2
        freqs = np.fft.fftshift(np.fft.fftfreq(spectral_samples.size, d=1.0 / sample_rate_hz))
        peak_index = int(np.argmax(psd))
        peak_offset_hz = float(freqs[peak_index])
        peak_frequency_hz = center_frequency_hz + peak_offset_hz
        spectral_noise = float(np.percentile(psd, 20))
        spectral_peak = float(psd[peak_index])
        spectral_snr_db = _db10(spectral_peak / max(spectral_noise, 1e-20))
        psd_excess = np.clip(psd - spectral_noise, 0.0, None)
        if float(np.sum(psd_excess)) > 0.0:
            centroid_offset_hz = float(np.sum(freqs * psd_excess) / np.sum(psd_excess))
        else:
            centroid_offset_hz = peak_offset_hz
        if float(np.sum(psd_excess)) > 0.0:
            cumulative = np.cumsum(psd_excess)
            total = float(cumulative[-1])
            lower_index = int(np.searchsorted(cumulative, total * 0.005))
            upper_index = int(np.searchsorted(cumulative, total * 0.995))
            lower_index = max(0, min(lower_index, freqs.size - 1))
            upper_index = max(lower_index, min(upper_index, freqs.size - 1))
            occupied_bandwidth_hz = float(freqs[upper_index] - freqs[lower_index])
        else:
            occupied_bandwidth_hz = 0.0

        analysis_method = "auto_energy_burst" if burst_detected else "no_burst_detected"
        regions_of_interest = ["transient_start", "whole_burst"] if burst_detected else ["whole_burst"]
        if not burst_detected and spectral_snr_db >= DEFAULT_THRESHOLDS["min_doubtful_snr_db"]:
            analysis_method = "spectral_peak_detection"
            estimated_snr_db = float(spectral_snr_db)
            silence_pct = 0.0
            burst_duration_ms = float((samples.size / sample_rate_hz) * 1000.0)
            burst_count = 1
            burst_start = 0
            burst_end = samples.size - 1
            regions_of_interest = ["whole_burst"]

        return {
            "estimated_snr_db": float(estimated_snr_db),
            "noise_floor_db": float(noise_floor_db),
            "peak_power_db": float(peak_power_db),
            "average_power_db": float(avg_power_db),
            "spectral_snr_db": float(spectral_snr_db),
            "occupied_bandwidth_hz": abs(float(occupied_bandwidth_hz)),
            "peak_frequency_hz": float(peak_frequency_hz),
            "frequency_offset_hz": float(centroid_offset_hz),
            "clipping_pct": float(clipping_pct),
            "silence_pct": float(silence_pct),
            "burst_duration_ms": float(burst_duration_ms),
            "method": analysis_method,
            "energy_threshold_db": float(_db10(energy_threshold_power)),
            "burst_count": int(burst_count),
            "burst_start_sample": int(burst_start),
            "burst_end_sample": int(burst_end),
            "regions_of_interest": regions_of_interest,
        }

    @staticmethod
    def _load_complex_samples(path: Path, iq_dtype: str) -> np.ndarray:
        normalized_dtype = str(iq_dtype or "complex64").strip().lower()
        if normalized_dtype in {"complex64", "fc32", "np.complex64"}:
            return np.fromfile(path, dtype=np.complex64)
        if normalized_dtype in {"complex128", "np.complex128"}:
            return np.fromfile(path, dtype=np.complex128).astype(np.complex64)
        if normalized_dtype in {"int16", "complex int16", "ci16"}:
            raw = np.fromfile(path, dtype=np.int16)
            if raw.size < 2:
                return np.asarray([], dtype=np.complex64)
            if raw.size % 2 == 1:
                raw = raw[:-1]
            i = raw[0::2].astype(np.float32) / 32768.0
            q = raw[1::2].astype(np.float32) / 32768.0
            return (i + 1j * q).astype(np.complex64)
        return np.fromfile(path, dtype=np.complex64)

    @staticmethod
    def _find_burst_bounds(mask: np.ndarray) -> tuple[int | None, int | None, int]:
        if mask.size == 0 or not np.any(mask):
            return None, None, 0
        indices = np.flatnonzero(mask)
        transitions = np.diff(indices)
        burst_count = int(np.sum(transitions > 1) + 1)
        return int(indices[0]), int(indices[-1]), burst_count

    def _capture_path(self, capture_id: str) -> Path:
        return self._captures_dir / f"{capture_id}.json"

    def _delete_unreferenced_artifacts(self, record: dict[str, Any], excluded_capture_id: str) -> list[str]:
        removed: list[str] = []
        candidates = [
            str((record.get("artifacts") or {}).get("iq_file") or "").strip(),
            str((record.get("artifacts") or {}).get("metadata_file") or "").strip(),
            str((record.get("capture_config") or {}).get("output_path") or "").strip(),
        ]
        unique_candidates: list[Path] = []
        for candidate in candidates:
            if not candidate:
                continue
            try:
                resolved = Path(candidate).resolve()
            except OSError:
                continue
            if resolved not in unique_candidates:
                unique_candidates.append(resolved)

        for candidate in unique_candidates:
            if not candidate.exists() or not candidate.is_file():
                continue
            if not self._is_within_workspace(candidate):
                continue
            if self._is_artifact_referenced_elsewhere(candidate, excluded_capture_id=excluded_capture_id):
                continue
            candidate.unlink()
            removed.append(str(candidate))
        return removed

    def _is_artifact_referenced_elsewhere(self, artifact_path: Path, excluded_capture_id: str) -> bool:
        artifact_text = str(artifact_path)
        for path in self._captures_dir.glob("*.json"):
            if path.stem == excluded_capture_id:
                continue
            try:
                record = self._load_record(path)
            except Exception:
                continue
            references = [
                str((record.get("artifacts") or {}).get("iq_file") or "").strip(),
                str((record.get("artifacts") or {}).get("metadata_file") or "").strip(),
                str((record.get("capture_config") or {}).get("output_path") or "").strip(),
            ]
            for reference in references:
                if not reference:
                    continue
                try:
                    if str(Path(reference).resolve()) == artifact_text:
                        return True
                except OSError:
                    continue
        return False

    def _is_within_workspace(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
            workspace = self._workspace_root.resolve()
        except OSError:
            return False
        try:
            resolved.relative_to(workspace)
            return True
        except ValueError:
            return False

    def _load_record(self, path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _save_record(self, record: dict[str, Any]) -> None:
        record["updated_at_utc"] = _utc_now()
        with self._capture_path(record["capture_id"]).open("w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2, ensure_ascii=False)

    def _normalize_record(self, payload: dict[str, Any], capture_id: str | None = None) -> dict[str, Any]:
        capture_id = capture_id or uuid4().hex[:12]
        capture_config = deepcopy(payload.get("capture_config", {}))
        transmitter = deepcopy(payload.get("transmitter", {}))
        scenario = deepcopy(payload.get("scenario", {}))
        quality_metrics = deepcopy(payload.get("quality_metrics", {}))
        burst_detection = deepcopy(payload.get("burst_detection", {}))
        artifacts = deepcopy(payload.get("artifacts", {}))
        preview_metrics = deepcopy(payload.get("preview_metrics", {}))

        iq_path = artifacts.get("iq_file") or capture_config.get("output_path")
        if iq_path and not artifacts.get("sha256"):
            iq_file = Path(iq_path)
            if iq_file.exists():
                artifacts["sha256"] = _sha256_file(iq_file)

        quality = self._evaluate_quality(
            {
                "estimated_snr_db": float(quality_metrics.get("estimated_snr_db", 0.0) or 0.0),
                "frequency_offset_hz": float(quality_metrics.get("frequency_offset_hz", 0.0) or 0.0),
                "clipping_pct": float(quality_metrics.get("clipping_pct", 0.0) or 0.0),
                "sample_drop_count": int(quality_metrics.get("sample_drop_count", 0) or 0),
                "buffer_overflow_count": int(quality_metrics.get("buffer_overflow_count", 0) or 0),
                "silence_pct": float(quality_metrics.get("silence_pct", 0.0) or 0.0),
                "burst_duration_ms": float(quality_metrics.get("burst_duration_ms", 0.0) or 0.0),
            },
            payload.get("operator_decision"),
        )

        timestamp_utc = scenario.get("timestamp_utc") or _utc_now()
        dataset_split = self._normalize_split(payload.get("dataset_split", "train"))
        dataset_destination = str(capture_config.get("dataset_destination", "")).strip()
        if not dataset_destination:
            dataset_destination = f"fingerprinting/{dataset_split}"
        return {
            "capture_id": capture_id,
            "capture_mode": payload.get("capture_mode", "guided_capture"),
            "session_id": payload.get("session_id", scenario.get("session_id", "session_unassigned")),
            "dataset_split": dataset_split,
            "created_at_utc": payload.get("created_at_utc", _utc_now()),
            "capture_config": {
                "device_source": capture_config.get("device_source", "uhd"),
                "sdr_model": capture_config.get("sdr_model", "unknown"),
                "sdr_serial": capture_config.get("sdr_serial", "unknown"),
                "gain_stage": capture_config.get("gain_stage", "manual"),
                "antenna_port": capture_config.get("antenna_port", "RX2"),
                "capture_type": capture_config.get("capture_type", "iq_file"),
                "center_frequency_hz": capture_config.get("center_frequency_hz", 0.0),
                "sample_rate_hz": capture_config.get("sample_rate_hz", 0.0),
                "effective_bandwidth_hz": capture_config.get("effective_bandwidth_hz", 0.0),
                "frontend_bandwidth_hz": capture_config.get("frontend_bandwidth_hz"),
                "gain_mode": capture_config.get("gain_mode", "manual"),
                "gain_settings": capture_config.get("gain_settings", {}),
                "ppm_correction": capture_config.get("ppm_correction", 0.0),
                "lo_offset_hz": capture_config.get("lo_offset_hz", 0.0),
                "capture_duration_s": capture_config.get("capture_duration_s", 0.0),
                "sample_count": capture_config.get("sample_count", 0),
                "file_format": capture_config.get("file_format", "cfile"),
                "sample_dtype": capture_config.get("sample_dtype", "complex64"),
                "byte_order": capture_config.get("byte_order", "native"),
                "channel_count": capture_config.get("channel_count", 1),
                "output_path": capture_config.get("output_path", ""),
                "dataset_destination": dataset_destination,
            },
            "transmitter": {
                "transmitter_label": transmitter.get("transmitter_label", ""),
                "transmitter_class": transmitter.get("transmitter_class", ""),
                "transmitter_id": transmitter.get("transmitter_id", ""),
                "family": transmitter.get("family", ""),
                "ground_truth_confidence": transmitter.get("ground_truth_confidence", "unknown"),
            },
            "scenario": {
                "operator": scenario.get("operator", "unknown"),
                "environment": scenario.get("environment", "unspecified"),
                "distance_m": scenario.get("distance_m"),
                "line_of_sight": scenario.get("line_of_sight"),
                "indoor": scenario.get("indoor"),
                "notes": scenario.get("notes", ""),
                "session_number": scenario.get("session_number", 1),
                "timestamp_utc": timestamp_utc,
            },
            "quality_metrics": quality_metrics,
            "burst_detection": {
                "method": burst_detection.get("method", "manual"),
                "energy_threshold_db": burst_detection.get("energy_threshold_db"),
                "pre_trigger_samples": burst_detection.get("pre_trigger_samples", 0),
                "post_trigger_samples": burst_detection.get("post_trigger_samples", 0),
                "min_burst_duration_ms": burst_detection.get("min_burst_duration_ms", 1.0),
                "max_burst_duration_ms": burst_detection.get("max_burst_duration_ms"),
                "burst_count": burst_detection.get("burst_count", 1),
                "regions_of_interest": burst_detection.get("regions_of_interest", []),
                "burst_start_sample": burst_detection.get("burst_start_sample"),
                "burst_end_sample": burst_detection.get("burst_end_sample"),
            },
            "quality_review": {
                "status": quality["status"],
                "reasons": quality["reasons"],
                "quality_flags": quality["flags"],
                "operator_decision": payload.get("operator_decision"),
                "review_notes": payload.get("review_notes", ""),
                "export_windows": payload.get("export_windows", []),
                "updated_at_utc": _utc_now(),
            },
            "artifacts": artifacts,
            "preview_metrics": {
                "live_preview_snr_db": _safe_float(preview_metrics.get("live_preview_snr_db")),
                "live_preview_noise_floor_db": _safe_float(preview_metrics.get("live_preview_noise_floor_db")),
                "live_preview_peak_level_db": _safe_float(preview_metrics.get("live_preview_peak_level_db")),
                "live_preview_peak_frequency_hz": _safe_float(preview_metrics.get("live_preview_peak_frequency_hz")),
            },
        }

    @staticmethod
    def _normalize_split(value: Any) -> str:
        normalized = str(value or "train").strip().lower()
        if normalized not in {"train", "val", "predict"}:
            raise ValueError("dataset_split must be one of: train, val, predict")
        return normalized

    def _evaluate_quality(self, metrics: dict[str, Any], operator_decision: str | None) -> dict[str, Any]:
        reasons: list[str] = []
        flags: list[str] = []

        snr = float(metrics.get("estimated_snr_db", 0.0) or 0.0)
        clipping_pct = float(metrics.get("clipping_pct", 0.0) or 0.0)
        frequency_offset_hz = abs(float(metrics.get("frequency_offset_hz", 0.0) or 0.0))
        silence_pct = float(metrics.get("silence_pct", 0.0) or 0.0)
        sample_drop_count = int(metrics.get("sample_drop_count", 0) or 0)
        buffer_overflow_count = int(metrics.get("buffer_overflow_count", 0) or 0)
        burst_duration_ms = float(metrics.get("burst_duration_ms", 0.0) or 0.0)

        if snr < DEFAULT_THRESHOLDS["min_doubtful_snr_db"]:
            reasons.append("insufficient_snr")
            flags.append("snr_low")
        elif snr < DEFAULT_THRESHOLDS["min_valid_snr_db"]:
            reasons.append("borderline_snr")
            flags.append("snr_borderline")

        if clipping_pct > DEFAULT_THRESHOLDS["max_doubtful_clipping_pct"]:
            reasons.append("adc_clipping")
            flags.append("clipping_high")
        elif clipping_pct > DEFAULT_THRESHOLDS["max_valid_clipping_pct"]:
            reasons.append("moderate_clipping")
            flags.append("clipping_present")

        if frequency_offset_hz > DEFAULT_THRESHOLDS["max_doubtful_frequency_offset_hz"]:
            reasons.append("frequency_incorrect")
            flags.append("offset_extreme")
        elif frequency_offset_hz > DEFAULT_THRESHOLDS["max_valid_frequency_offset_hz"]:
            reasons.append("frequency_offset_high")
            flags.append("offset_high")

        if sample_drop_count > 0:
            reasons.append("sample_drops_detected")
            flags.append("sample_drop")

        if buffer_overflow_count > 0:
            reasons.append("buffer_overflow")
            flags.append("buffer_overflow")

        if silence_pct > DEFAULT_THRESHOLDS["max_silence_pct"]:
            reasons.append("absence_of_activity")
            flags.append("silence_high")

        if burst_duration_ms and burst_duration_ms < DEFAULT_THRESHOLDS["min_valid_burst_duration_ms"]:
            reasons.append("duration_insufficient")
            flags.append("burst_too_short")

        status = "valid"
        if reasons:
            status = "rejected" if any(
                item in reasons
                for item in (
                    "insufficient_snr",
                    "adc_clipping",
                    "frequency_incorrect",
                    "sample_drops_detected",
                    "buffer_overflow",
                    "absence_of_activity",
                    "duration_insufficient",
                )
            ) else "doubtful"

        if operator_decision in {"valid", "doubtful", "rejected"}:
            status = operator_decision

        return {
            "status": status,
            "reasons": reasons,
            "flags": flags,
        }
