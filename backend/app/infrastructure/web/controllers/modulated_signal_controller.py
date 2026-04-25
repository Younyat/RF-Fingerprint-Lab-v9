from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path

from app.config.settings import settings as app_settings
from app.infrastructure.sdr.real_spectrum_stream import real_spectrum_stream
from app.infrastructure.sdr.rf_safety import (
    DEFAULT_USRP_B200_LIMITS,
    validate_gain,
    validate_sample_rate,
    validate_start_stop,
)


class ModulatedSignalController:
    _capture_oversample_factor = 1.25
    _max_capture_sample_rate_hz = 12_500_000.0
    _max_capture_file_size_bytes = 768 * 1024 * 1024

    def __init__(self, settings) -> None:
        self._settings = settings
        self._cfile_output_dir = app_settings.storage.recordings_dir / "modulated_signal_captures"
        self._iq_output_dir = app_settings.storage.recordings_dir / "modulated_signal_iq_captures"
        self._cfile_output_dir.mkdir(parents=True, exist_ok=True)
        self._iq_output_dir.mkdir(parents=True, exist_ok=True)

    def capture_marker_band(
        self,
        start_frequency_hz: float,
        stop_frequency_hz: float,
        duration_seconds: float = 5.0,
        label: str = "",
        modulation_hint: str = "unknown",
        notes: str = "",
        dataset_split: str = "train",
        session_id: str = "",
        transmitter_id: str = "",
        transmitter_class: str = "",
        operator: str = "",
        environment: str = "",
        file_format: str = "cfile",
        live_preview_snr_db: float | None = None,
        live_preview_noise_floor_db: float | None = None,
        live_preview_peak_level_db: float | None = None,
        live_preview_peak_frequency_hz: float | None = None,
        capture_mode: str = "immediate",
        trigger_threshold_db: float = 6.0,
        pre_trigger_ms: float = 0.0,
        post_trigger_ms: float = 50.0,
        trigger_max_wait_s: float = 5.0,
    ) -> dict:
        file_format = file_format.lower()
        if file_format not in {"cfile", "iq"}:
            raise ValueError("file_format must be cfile or iq")
        if duration_seconds <= 0 or duration_seconds > 120:
            raise ValueError("duration_seconds must be between 0 and 120")
        if capture_mode not in {"immediate", "triggered_burst"}:
            raise ValueError("capture_mode must be immediate or triggered_burst")
        if pre_trigger_ms < 0 or post_trigger_ms < 0:
            raise ValueError("pre_trigger_ms and post_trigger_ms must be non-negative")
        if trigger_max_wait_s <= 0 or trigger_max_wait_s > 120:
            raise ValueError("trigger_max_wait_s must be between 0 and 120")

        center_frequency_hz, bandwidth_hz = validate_start_stop(start_frequency_hz, stop_frequency_hz)
        validate_gain(self._settings.gain.gain_db)
        requested_sample_rate_hz = max(
            bandwidth_hz * self._capture_oversample_factor,
            DEFAULT_USRP_B200_LIMITS.min_sample_rate_hz,
        )
        if requested_sample_rate_hz > self._max_capture_sample_rate_hz:
            max_bandwidth_hz = self._max_capture_sample_rate_hz / self._capture_oversample_factor
            raise ValueError(
                "Capture Lab bandwidth is too large for reliable acquisition in this workflow. "
                f"Requested bandwidth: {bandwidth_hz / 1e6:.2f} MHz. "
                f"Safe limit: {max_bandwidth_hz / 1e6:.2f} MHz. "
                "Reduce bandwidth or capture a narrower window."
            )

        sample_rate_hz = min(
            max(
                float(self._settings.frequency.sample_rate_hz),
                requested_sample_rate_hz,
                DEFAULT_USRP_B200_LIMITS.min_sample_rate_hz,
            ),
            min(DEFAULT_USRP_B200_LIMITS.max_sample_rate_hz, self._max_capture_sample_rate_hz),
        )
        validate_sample_rate(sample_rate_hz)
        effective_capture_horizon_s = float(duration_seconds)
        if capture_mode == "triggered_burst":
            effective_capture_horizon_s = max(
                float(duration_seconds),
                float(trigger_max_wait_s) + (float(pre_trigger_ms) + float(post_trigger_ms)) / 1000.0 + 0.25,
            )
        estimated_file_size_bytes = int(effective_capture_horizon_s * sample_rate_hz * 8)
        if estimated_file_size_bytes > self._max_capture_file_size_bytes:
            raise ValueError(
                "Capture would generate an excessively large IQ file for Capture Lab. "
                f"Estimated size: {estimated_file_size_bytes / (1024 * 1024):.1f} MiB. "
                f"Limit: {self._max_capture_file_size_bytes / (1024 * 1024):.1f} MiB. "
                "Reduce duration or bandwidth."
            )

        capture_id = str(uuid.uuid4())[:8]
        backend_root = app_settings.storage.app_root.parent
        script_path = backend_root / "tools" / "capture_marker_band_iq.py"
        python_exe = os.environ.get("RADIOCONDA_PYTHON", r"C:\Users\Usuario\radioconda\python.exe")
        output_dir = self._iq_output_dir if file_format == "iq" else self._cfile_output_dir
        base_name = f"{file_format}_{capture_id}_{center_frequency_hz / 1e6:.6f}MHz_{bandwidth_hz / 1e3:.1f}kHz"

        command = [
            python_exe,
            str(script_path),
            "--capture-id",
            capture_id,
            "--start-hz",
            str(float(start_frequency_hz)),
            "--stop-hz",
            str(float(stop_frequency_hz)),
            "--duration",
            str(float(duration_seconds)),
            "--sample-rate",
            str(sample_rate_hz),
            "--gain",
            str(float(self._settings.gain.gain_db)),
            "--antenna",
            app_settings.default_device.antenna,
            "--device-addr",
            app_settings.default_device.device_args,
            "--output-dir",
            str(output_dir),
            "--base-name",
            base_name,
            "--file-format",
            file_format,
            "--label",
            label,
            "--modulation-hint",
            modulation_hint,
            "--notes",
            notes,
            "--dataset-split",
            dataset_split,
            "--session-id",
            session_id,
            "--transmitter-id",
            transmitter_id,
            "--transmitter-class",
            transmitter_class,
            "--operator",
            operator,
            "--environment",
            environment,
            "--capture-mode",
            capture_mode,
            "--trigger-threshold-db",
            str(float(trigger_threshold_db)),
            "--pre-trigger-ms",
            str(float(pre_trigger_ms)),
            "--post-trigger-ms",
            str(float(post_trigger_ms)),
            "--trigger-max-wait-s",
            str(float(trigger_max_wait_s)),
        ]
        if live_preview_snr_db is not None:
            command.extend(["--live-preview-snr-db", str(float(live_preview_snr_db))])
        if live_preview_noise_floor_db is not None:
            command.extend(["--live-preview-noise-floor-db", str(float(live_preview_noise_floor_db))])
        if live_preview_peak_level_db is not None:
            command.extend(["--live-preview-peak-level-db", str(float(live_preview_peak_level_db))])
        if live_preview_peak_frequency_hz is not None:
            command.extend(["--live-preview-peak-frequency-hz", str(float(live_preview_peak_frequency_hz))])

        was_streaming = real_spectrum_stream.is_running()
        real_spectrum_stream.begin_exclusive_operation(
            "Marker-band IQ capture is using the USRP-B200 exclusively"
        )
        try:
            completed = subprocess.run(
                command,
                cwd=str(backend_root),
                capture_output=True,
                text=True,
                timeout=max(effective_capture_horizon_s + 30.0, 45.0),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except Exception as exc:
            raise ValueError(str(exc)) from exc
        finally:
            real_spectrum_stream.end_exclusive_operation()
            if was_streaming:
                real_spectrum_stream.ensure_started(self._settings)

        if completed.returncode != 0:
            error_output = completed.stderr or completed.stdout or "marker band IQ capture failed"
            if "No devices found" in error_output:
                error_output = (
                    "UHD did not find the USRP-B200. Check the USB connection and make sure no other "
                    "GNU Radio/UHD process is using the device."
                )
            raise ValueError(error_output)

        stdout_lines = [line for line in completed.stdout.splitlines() if line.strip()]
        if not stdout_lines:
            raise ValueError("IQ capture worker did not return metadata")
        return self._with_urls(json.loads(stdout_lines[-1]))

    def list_captures(self) -> list[dict]:
        captures = []
        metadata_paths = list(self._cfile_output_dir.glob("*.json")) + list(self._iq_output_dir.glob("*.json"))
        for path in sorted(metadata_paths, key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                with path.open("r", encoding="utf-8") as file:
                    captures.append(self._with_urls(json.load(file)))
            except Exception:
                continue
        return captures

    def get_capture(self, capture_id: str) -> dict:
        for capture in self.list_captures():
            if capture.get("id") == capture_id:
                return capture
        raise ValueError(f"Modulated signal capture not found: {capture_id}")

    def get_iq_file(self, capture_id: str) -> Path:
        capture = self.get_capture(capture_id)
        return self._existing_file(capture.get("iq_file"), "IQ file")

    def get_metadata_file(self, capture_id: str) -> Path:
        capture = self.get_capture(capture_id)
        return self._existing_file(capture.get("metadata_file"), "metadata file")

    def _existing_file(self, value: str | None, label: str) -> Path:
        if not value:
            raise ValueError(f"{label} is not available")
        path = Path(value)
        if not path.exists():
            raise ValueError(f"{label} not found: {path}")
        return path

    def _with_urls(self, capture: dict) -> dict:
        capture_id = capture.get("id")
        if capture_id:
            capture["iq_url"] = f"/api/modulated-signals/captures/{capture_id}/iq"
            capture["metadata_url"] = f"/api/modulated-signals/captures/{capture_id}/metadata"
        return capture
