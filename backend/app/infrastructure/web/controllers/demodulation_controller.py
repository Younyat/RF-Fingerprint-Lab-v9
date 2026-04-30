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


class DemodulationController:
    def __init__(
        self,
        start_demodulation_use_case,
        stop_demodulation_use_case,
        get_audio_status_use_case,
        settings,
    ):
        self._start_demodulation_use_case = start_demodulation_use_case
        self._stop_demodulation_use_case = stop_demodulation_use_case
        self._get_audio_status_use_case = get_audio_status_use_case
        self._settings = settings
        self._mode = "off"
        self._results: dict[str, dict] = {}
        self._output_dir = app_settings.storage.recordings_dir / "demodulations"
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def start_demodulation(self, mode: str) -> dict:
        self._mode = mode
        try:
            return self._start_demodulation_use_case.execute(mode)
        except Exception:
            return {"status": "ok", "demodulation_mode": mode}

    def stop_demodulation(self) -> dict:
        self._mode = "off"
        try:
            return self._stop_demodulation_use_case.execute()
        except Exception:
            return {"status": "ok", "demodulation_stopped": True}

    def get_audio_status(self) -> dict:
        try:
            status = self._get_audio_status_use_case.execute()
        except Exception:
            status = {"status": "stopped", "is_playing": False}
        status["demodulation_mode"] = self._mode
        return status

    def demodulate_marker_band(
        self,
        start_frequency_hz: float,
        stop_frequency_hz: float,
        mode: str,
        duration_seconds: float = 5.0,
        apply_bandpass_filter: bool = False,
        filter_stopband_attenuation_db: float = 60.0,
        filter_transition_width_hz: float | None = None,
    ) -> dict:
        mode = mode.lower()
        if mode not in {"am", "fm", "wfm", "ask", "fsk", "psk", "ook"}:
            raise ValueError("mode must be one of am, fm, wfm, ask, fsk, psk, ook")
        if duration_seconds <= 0 or duration_seconds > 60:
            raise ValueError("duration_seconds must be between 0 and 60")
        if filter_stopband_attenuation_db < 1 or filter_stopband_attenuation_db > 60:
            raise ValueError("filter_stopband_attenuation_db must be between 1 and 60 dB")

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

        demodulation_id = str(uuid.uuid4())[:8]
        backend_root = app_settings.storage.app_root.parent
        script_path = backend_root / "tools" / "demodulate_marker_band.py"
        python_exe = os.environ.get("RADIOCONDA_PYTHON", r"C:\Users\Usuario\radioconda\python.exe")
        base_name = f"marker_{demodulation_id}_{mode}_{center_frequency_hz / 1e6:.6f}MHz"

        command = [
            python_exe,
            str(script_path),
            "--start-hz",
            str(float(start_frequency_hz)),
            "--stop-hz",
            str(float(stop_frequency_hz)),
            "--mode",
            mode,
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
        ]
        if apply_bandpass_filter:
            command.append("--apply-bandpass-filter")
            command.extend(["--filter-stopband-attenuation-db", str(float(filter_stopband_attenuation_db))])
            if filter_transition_width_hz is not None:
                command.extend(["--filter-transition-width-hz", str(float(filter_transition_width_hz))])

        was_streaming = real_spectrum_stream.is_running()
        real_spectrum_stream.begin_exclusive_operation(
            "Marker-band demodulation is using the USRP-B200 exclusively"
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
            error_output = completed.stderr or completed.stdout or "marker band demodulation failed"
            if "No devices found" in error_output:
                error_output = (
                    "UHD did not find the USRP-B200. Check the USB connection and make sure no other "
                    "GNU Radio/UHD process is using the device."
                )
            raise ValueError(error_output)

        stdout_lines = [line for line in completed.stdout.splitlines() if line.strip()]
        if not stdout_lines:
            raise ValueError("demodulation worker did not return metadata")
        metadata = json.loads(stdout_lines[-1])
        result = {
            **metadata,
            "id": demodulation_id,
            "status": "complete",
            "audio_url": f"/api/demodulation/audio/{demodulation_id}" if metadata.get("audio_file") else None,
            "metadata_url": f"/api/demodulation/results/{demodulation_id}",
        }
        self._results[demodulation_id] = result
        self._persist_result_metadata(result)
        self._mode = mode
        return result

    def list_results(self) -> list[dict]:
        results = self._load_persisted_results()
        for result_id, result in self._results.items():
            results[result_id] = result
        return sorted(results.values(), key=lambda item: str(item.get("generated_at_utc", "")))

    def get_result(self, demodulation_id: str) -> dict:
        result = self._results.get(demodulation_id) or self._load_persisted_results().get(demodulation_id)
        if result is None:
            raise ValueError(f"Demodulation result not found: {demodulation_id}")
        return result

    def get_audio_file(self, demodulation_id: str) -> Path:
        result = self.get_result(demodulation_id)
        audio_file = result.get("audio_file")
        if not audio_file:
            raise ValueError(f"No audio available for demodulation result: {demodulation_id}")
        path = Path(audio_file)
        if not path.exists():
            raise ValueError(f"Audio file not found: {path}")
        return path

    def delete_result(self, demodulation_id: str) -> dict:
        result = self.get_result(demodulation_id)
        candidate_values = [
            result.get("metadata_file"),
            result.get("audio_file"),
            result.get("iq_file"),
        ]
        removed_files: list[str] = []
        skipped_files: list[str] = []
        seen: set[str] = set()
        for value in candidate_values:
            if not value:
                continue
            try:
                path = Path(str(value)).resolve()
            except OSError:
                skipped_files.append(str(value))
                continue
            if str(path) in seen:
                continue
            seen.add(str(path))
            if not path.exists() or not path.is_file():
                continue
            if not self._is_safe_demodulation_file(path):
                skipped_files.append(str(path))
                continue
            path.unlink()
            removed_files.append(str(path))
        self._results.pop(demodulation_id, None)
        return {
            "id": demodulation_id,
            "deleted": True,
            "deleted_files": removed_files,
            "skipped_files": skipped_files,
        }

    def _persist_result_metadata(self, result: dict) -> None:
        metadata_file = result.get("metadata_file")
        if not metadata_file:
            return
        path = Path(str(metadata_file))
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8") as file:
                json.dump(result, file, indent=2, ensure_ascii=False)
        except Exception:
            return

    def _load_persisted_results(self) -> dict[str, dict]:
        results: dict[str, dict] = {}
        if not self._output_dir.exists():
            return results
        for path in self._output_dir.glob("*.json"):
            try:
                with path.open("r", encoding="utf-8") as file:
                    metadata = json.load(file)
                result = self._result_from_metadata(path, metadata)
                results[result["id"]] = result
            except Exception:
                continue
        return results

    def _is_safe_demodulation_file(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
            resolved.relative_to(self._output_dir.resolve())
            return resolved.suffix.lower() in {".json", ".wav", ".cfile", ".iq"}
        except (OSError, ValueError):
            return False

    def _result_from_metadata(self, path: Path, metadata: dict) -> dict:
        demodulation_id = str(metadata.get("id") or "").strip()
        if not demodulation_id:
            stem = path.stem
            parts = stem.split("_")
            if len(parts) >= 2 and parts[0] == "marker":
                demodulation_id = parts[1]
            else:
                demodulation_id = stem
        audio_file = metadata.get("audio_file")
        result = {
            **metadata,
            "id": demodulation_id,
            "status": metadata.get("status") or "complete",
            "metadata_file": str(path.resolve()),
            "metadata_url": f"/api/demodulation/results/{demodulation_id}",
            "audio_url": f"/api/demodulation/audio/{demodulation_id}" if audio_file else None,
        }
        return result
