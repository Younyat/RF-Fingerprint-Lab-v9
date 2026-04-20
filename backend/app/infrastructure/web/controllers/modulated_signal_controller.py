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
    def __init__(self, settings) -> None:
        self._settings = settings
        self._output_dir = app_settings.storage.recordings_dir / "modulated_signal_captures"
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def capture_marker_band(
        self,
        start_frequency_hz: float,
        stop_frequency_hz: float,
        duration_seconds: float = 5.0,
        label: str = "",
        modulation_hint: str = "unknown",
        notes: str = "",
    ) -> dict:
        if duration_seconds <= 0 or duration_seconds > 120:
            raise ValueError("duration_seconds must be between 0 and 120")

        center_frequency_hz, bandwidth_hz = validate_start_stop(start_frequency_hz, stop_frequency_hz)
        validate_gain(self._settings.gain.gain_db)
        sample_rate_hz = min(
            max(
                float(self._settings.frequency.sample_rate_hz),
                bandwidth_hz * 4.0,
                DEFAULT_USRP_B200_LIMITS.min_sample_rate_hz,
            ),
            DEFAULT_USRP_B200_LIMITS.max_sample_rate_hz,
        )
        validate_sample_rate(sample_rate_hz)

        capture_id = str(uuid.uuid4())[:8]
        backend_root = app_settings.storage.app_root.parent
        script_path = backend_root / "tools" / "capture_marker_band_iq.py"
        python_exe = os.environ.get("RADIOCONDA_PYTHON", r"C:\Users\Usuario\radioconda\python.exe")
        base_name = f"iq_{capture_id}_{center_frequency_hz / 1e6:.6f}MHz_{bandwidth_hz / 1e3:.1f}kHz"

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
            str(self._output_dir),
            "--base-name",
            base_name,
            "--label",
            label,
            "--modulation-hint",
            modulation_hint,
            "--notes",
            notes,
        ]

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
                timeout=max(float(duration_seconds) + 30.0, 45.0),
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
        for path in sorted(self._output_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
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
