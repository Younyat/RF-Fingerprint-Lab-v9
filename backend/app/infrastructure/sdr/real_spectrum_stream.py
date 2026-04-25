from __future__ import annotations

import json
import os
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config.settings import settings as app_settings
from app.infrastructure.sdr.rf_safety import validate_frequency_window, validate_gain


class RealSpectrumStream:
    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._latest_frame: dict[str, Any] | None = None
        self._last_error: str | None = None
        self._config_key: tuple | None = None
        self._runtime_key: tuple | None = None
        self._exclusive_reason: str | None = None
        self._lock = threading.Lock()

    def get_latest(self, analyzer_settings) -> dict:
        self.ensure_started(analyzer_settings)
        with self._lock:
            if self._latest_frame is not None:
                return dict(self._latest_frame)
            return {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "center_frequency_hz": analyzer_settings.frequency.center_frequency_hz,
                "span_hz": analyzer_settings.frequency.sample_rate_hz,
                "frequencies_hz": [],
                "levels_db": [],
                "source": "real_sdr_pending",
                "error": self._last_error or "Waiting for first real SDR frame",
            }

    def ensure_started(self, analyzer_settings) -> None:
        with self._lock:
            if self._exclusive_reason is not None:
                self._last_error = self._exclusive_reason
                return

        config_key = self._make_config_key(analyzer_settings)
        runtime_key = self._make_runtime_key(analyzer_settings)
        if self._process is not None and self._process.poll() is None:
            if self._config_key == config_key:
                if self._runtime_key != runtime_key:
                    if self._send_update(analyzer_settings):
                        self._runtime_key = runtime_key
                        self._latest_frame = None
                        self._last_error = None
                        return
                    self.stop()
                else:
                    return

        self.stop()
        self._config_key = config_key
        self._runtime_key = runtime_key
        self._latest_frame = None
        self._last_error = None

        try:
            validate_frequency_window(
                analyzer_settings.frequency.center_frequency_hz,
                analyzer_settings.frequency.sample_rate_hz,
            )
            validate_gain(analyzer_settings.gain.gain_db)
        except ValueError as exc:
            self._last_error = str(exc)
            return

        python_exe = os.environ.get("RADIOCONDA_PYTHON", r"C:\Users\Usuario\radioconda\python.exe")
        backend_root = app_settings.storage.app_root.parent
        script_path = backend_root / "tools" / "spectrum_stream_worker.py"

        if not Path(python_exe).exists():
            self._last_error = f"RadioConda Python not found: {python_exe}"
            return
        if not script_path.exists():
            self._last_error = f"Spectrum stream worker not found: {script_path}"
            return

        command = [
            python_exe,
            "-u",
            str(script_path),
            "--freq",
            f"{analyzer_settings.frequency.center_frequency_hz / 1e6:.9f}",
            "--sample-rate",
            str(float(analyzer_settings.frequency.sample_rate_hz)),
            "--gain",
            str(float(analyzer_settings.gain.gain_db)),
            "--antenna",
            app_settings.default_device.antenna,
            "--device-addr",
            app_settings.default_device.device_args,
            "--fft-size",
            str(int(analyzer_settings.resolution.fft_size)),
            "--max-fft-size",
            os.environ.get("REAL_SDR_MAX_FFT_SIZE", "65536"),
            "--rbw",
            str(float(analyzer_settings.resolution.rbw_hz)),
            "--vbw",
            str(float(analyzer_settings.resolution.vbw_hz)),
            "--fps",
            os.environ.get("REAL_SDR_FPS", "10"),
        ]

        try:
            self._process = subprocess.Popen(
                command,
                cwd=str(backend_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except Exception as exc:
            self._last_error = str(exc)
            self._process = None
            return

        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def stop(self) -> None:
        if self._process is not None and self._process.poll() is None:
            if self._process.stdin is not None:
                try:
                    self._process.stdin.close()
                except Exception:
                    pass
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None

    def apply_settings(self, analyzer_settings) -> None:
        self.ensure_started(analyzer_settings)

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def begin_exclusive_operation(self, reason: str) -> None:
        self.stop()
        with self._lock:
            self._exclusive_reason = reason
            self._latest_frame = None
            self._last_error = reason

    def end_exclusive_operation(self) -> None:
        with self._lock:
            self._exclusive_reason = None

    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                frame = json.loads(line)
            except json.JSONDecodeError:
                continue
            with self._lock:
                if frame.get("source") == "real_sdr_error":
                    self._last_error = frame.get("error", "Unknown SDR error")
                else:
                    self._latest_frame = frame
                    self._last_error = None

    def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        for line in process.stderr:
            line = line.strip()
            if line:
                with self._lock:
                    self._last_error = line

    def _make_config_key(self, analyzer_settings) -> tuple:
        return (
            app_settings.default_device.antenna,
            app_settings.default_device.device_args,
        )

    def _make_runtime_key(self, analyzer_settings) -> tuple:
        return (
            float(analyzer_settings.frequency.center_frequency_hz),
            float(analyzer_settings.frequency.sample_rate_hz),
            float(analyzer_settings.gain.gain_db),
            int(analyzer_settings.resolution.fft_size),
            float(analyzer_settings.resolution.rbw_hz),
            float(analyzer_settings.resolution.vbw_hz),
        )

    def _send_update(self, analyzer_settings) -> bool:
        process = self._process
        if process is None or process.poll() is not None or process.stdin is None:
            return False

        command = {
            "command": "update",
            "center_freq_hz": float(analyzer_settings.frequency.center_frequency_hz),
            "sample_rate_hz": float(analyzer_settings.frequency.sample_rate_hz),
            "gain_db": float(analyzer_settings.gain.gain_db),
            "fft_size": int(analyzer_settings.resolution.fft_size),
            "rbw_hz": float(analyzer_settings.resolution.rbw_hz),
            "vbw_hz": float(analyzer_settings.resolution.vbw_hz),
        }

        try:
            process.stdin.write(json.dumps(command) + "\n")
            process.stdin.flush()
            return True
        except Exception as exc:
            self._last_error = str(exc)
            return False


real_spectrum_stream = RealSpectrumStream()
