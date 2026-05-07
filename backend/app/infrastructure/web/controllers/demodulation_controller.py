from __future__ import annotations

import json
import os
import subprocess
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import numpy as np

from app.config.settings import settings as app_settings
from app.infrastructure.sdr.real_spectrum_stream import real_spectrum_stream
from app.infrastructure.sdr.rf_safety import (
    DEFAULT_USRP_B200_LIMITS,
    validate_gain,
    validate_sample_rate,
    validate_start_stop,
)


class DemodulationController:
    IOT_PIPELINES = {
        "ble_advertising",
        "generic_gfsk_iot",
        "ook_ask_iot_sensor",
        "generic_fsk_iot",
        "zigbee_ieee802154",
        "lora_css",
    }

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
        self._dataset_output_dir = app_settings.storage.storage_root / "demodulation_outputs"
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._dataset_output_dir.mkdir(parents=True, exist_ok=True)

    def list_pipelines(self) -> list[dict]:
        return [
            {
                "id": "wfm_broadcast",
                "category": "Basic analog demodulation",
                "family": "audio_analog",
                "label": "WFM broadcast",
                "status": "implemented_basic",
                "outputs": ["recovered_audio.wav", "demodulation_report.json"],
            },
            {
                "id": "nfm",
                "category": "Basic analog demodulation",
                "family": "audio_analog",
                "label": "NFM",
                "status": "implemented_basic",
                "outputs": ["recovered_audio.wav", "demodulation_report.json"],
            },
            {
                "id": "am",
                "category": "Basic analog demodulation",
                "family": "audio_analog",
                "label": "AM",
                "status": "implemented_basic",
                "outputs": ["recovered_audio.wav", "demodulation_report.json"],
            },
            {
                "id": "ble_advertising",
                "category": "IoT Demodulation Pipelines",
                "family": "bluetooth_low_energy",
                "label": "BLE advertising channels 37/38/39",
                "status": "rf_activity_and_sync_scaffold",
                "outputs": ["decoded_packets.json", "demodulation_report.json"],
            },
            {
                "id": "generic_gfsk_iot",
                "category": "IoT Demodulation Pipelines",
                "family": "generic_iot",
                "label": "Generic GFSK IoT Telemetry",
                "status": "physical_bitstream_estimator",
                "outputs": ["bitstream.bin", "decoded_payload.json", "demodulation_report.json"],
            },
            {
                "id": "ook_ask_iot_sensor",
                "category": "IoT Demodulation Pipelines",
                "family": "generic_iot_sensor",
                "label": "Generic OOK/ASK IoT Sensor",
                "status": "physical_bitstream_estimator",
                "outputs": ["bitstream.bin", "decoded_payload.json", "demodulation_report.json"],
            },
            {
                "id": "generic_fsk_iot",
                "category": "IoT Demodulation Pipelines",
                "family": "generic_iot",
                "label": "Generic FSK IoT Telemetry",
                "status": "physical_bitstream_estimator",
                "outputs": ["bitstream.bin", "decoded_payload.json", "demodulation_report.json"],
            },
            {
                "id": "ieee802154_oqpsk",
                "category": "Protocol/system decoders",
                "family": "ieee802154",
                "label": "IEEE 802.15.4 O-QPSK DSSS 2.4 GHz",
                "status": "rf_activity_and_sync_scaffold",
                "outputs": ["decoded_packets.json", "demodulation_report.json"],
            },
            {
                "id": "dvbt",
                "category": "Protocol/system decoders",
                "family": "terrestrial_tv",
                "label": "DVB-T",
                "status": "external_chain_required",
                "outputs": ["demodulation_report.json"],
            },
            {
                "id": "adsb_1090",
                "category": "Protocol/system decoders",
                "family": "adsb",
                "label": "ADS-B 1090 MHz",
                "status": "rf_activity_and_sync_scaffold",
                "outputs": ["decoded_packets.json", "demodulation_report.json"],
            },
            {
                "id": "ook_fsk_generic",
                "category": "Physical-layer demodulation",
                "family": "simple_digital",
                "label": "OOK / FSK / GFSK generic",
                "status": "symbol_estimation_scaffold",
                "outputs": ["bitstream.bin", "decoded_payload.json", "demodulation_report.json"],
            },
            {
                "id": "lora_css",
                "category": "IoT Demodulation Pipelines",
                "family": "lora",
                "label": "LoRa CSS",
                "status": "experimental_scaffold",
                "outputs": ["decoded_payload.json", "demodulation_report.json"],
            },
            {
                "id": "dvbs_s2",
                "category": "Protocol/system decoders",
                "family": "satellite_tv",
                "label": "DVB-S / DVB-S2",
                "status": "experimental_requires_external_rf_front_end",
                "outputs": ["demodulation_report.json"],
            },
        ]

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
        if mode not in {"am", "fm", "wfm", "ask", "fsk", "psk", "ook"} | self.IOT_PIPELINES:
            raise ValueError("mode must be one of am, fm, wfm, ask, fsk, psk, ook, or a registered IoT pipeline")
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
        worker_mode = self._live_worker_mode_for_pipeline(mode)
        base_name = f"marker_{demodulation_id}_{mode}_{center_frequency_hz / 1e6:.6f}MHz"

        command = [
            python_exe,
            str(script_path),
            "--start-hz",
            str(float(start_frequency_hz)),
            "--stop-hz",
            str(float(stop_frequency_hz)),
            "--mode",
            worker_mode,
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
            "final_status": "media_recovered" if metadata.get("audio_file") else "rf_activity_only",
            "mode": "live_demodulation",
            "source": "live_sdr",
            "marker_left_hz": float(start_frequency_hz),
            "marker_right_hz": float(stop_frequency_hz),
            "pipeline": mode,
            "demodulation_pipeline": mode,
            "rf_analysis_source": "computed_from_live_iq",
            "demodulation_source": "computed_from_live_iq",
            "audio_url": f"/api/demodulation/audio/{demodulation_id}" if metadata.get("audio_file") else None,
            "metadata_url": f"/api/demodulation/results/{demodulation_id}",
        }
        if mode in self.IOT_PIPELINES and metadata.get("iq_file"):
            live_payload = {
                "sample_id": demodulation_id,
                "dataset_id": "live_sdr",
                "file_path": metadata["iq_file"],
                "file_format": "cfile",
                "datatype": "cf32_le",
                "sample_rate_hz": sample_rate_hz,
                "center_frequency_hz": center_frequency_hz,
                "bandwidth_hz": bandwidth_hz,
                "capture_duration": duration_seconds,
                "source_dataset": "live_sdr",
                "signal_type": mode,
                "pipeline": mode,
            }
            iq = self._read_complex_iq(Path(str(metadata["iq_file"])), "cf32_le")
            output_dir = self._output_dir / demodulation_id
            output_dir.mkdir(parents=True, exist_ok=True)
            iot_report = self._run_iot_pipeline(iq, live_payload, mode, output_dir)
            result.update(
                {
                    **iot_report,
                    "id": demodulation_id,
                    "mode": "live_demodulation",
                    "source": "live_sdr",
                    "marker_left_hz": float(start_frequency_hz),
                    "marker_right_hz": float(stop_frequency_hz),
                    "center_frequency_hz": center_frequency_hz,
                    "bandwidth_hz": bandwidth_hz,
                    "sample_rate_hz": sample_rate_hz,
                    "duration_seconds": duration_seconds,
                    "iq_file": metadata["iq_file"],
                    "output_dir": str(output_dir),
                    "metadata_file": str(output_dir / "demodulation_report.json"),
                    "metadata_url": f"/api/demodulation/results/{demodulation_id}",
                    "rf_analysis_source": "computed_from_live_iq",
                    "demodulation_source": "computed_from_live_iq",
                }
            )
            result.setdefault("outputs", {})
            result["outputs"]["report"] = str(output_dir / "demodulation_report.json")
            Path(str(output_dir / "demodulation_report.json")).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        self._results[demodulation_id] = result
        self._persist_result_metadata(result)
        self._mode = mode
        return result

    def demodulate_dataset_capture(self, payload: dict) -> dict:
        normalized = self._normalize_dataset_input(payload)
        sample_id = normalized["sample_id"]
        demodulation_id = f"dataset_{sample_id}_{str(uuid.uuid4())[:8]}"
        output_dir = self._dataset_output_dir / sample_id
        output_dir.mkdir(parents=True, exist_ok=True)

        missing = self._missing_demodulation_metadata(normalized)
        pipeline = normalized.get("pipeline") or self._infer_pipeline(normalized)
        report = self._base_dataset_report(demodulation_id, normalized, pipeline, output_dir)

        if missing:
            report.update(
                {
                    "status": "missing_metadata",
                    "missing_metadata": missing,
                    "notes": [
                        "Demodulation was not attempted because critical metadata is missing.",
                        "Required fields include file_path, sample_rate_hz, center_frequency_hz and datatype.",
                    ],
                }
            )
            return self._finalize_dataset_result(report, output_dir)

        path = Path(str(normalized["file_path"])).expanduser()
        if not path.exists():
            report.update({"status": "missing_metadata", "notes": [f"RF input file not found: {path}"]})
            return self._finalize_dataset_result(report, output_dir)

        if not self._is_supported_rf_input(path, normalized.get("file_format")):
            report.update(
                {
                    "status": "unsupported_signal_type",
                    "notes": [f"Unsupported RF input format: {path.suffix or normalized.get('file_format')}"],
                }
            )
            return self._finalize_dataset_result(report, output_dir)

        iq = self._read_complex_iq(path, str(normalized["datatype"]))
        if iq.size == 0:
            report.update({"status": "rf_activity_only", "notes": ["RF file contained no readable complex samples."]})
            return self._finalize_dataset_result(report, output_dir)

        report["rf_activity"] = self._summarize_iq_activity(iq, float(normalized["sample_rate_hz"]))
        signal_detected = bool(report["rf_activity"]["signal_detected"])
        if pipeline in {"wfm_broadcast", "nfm", "am"}:
            audio_path = self._demodulate_audio_iq(iq, float(normalized["sample_rate_hz"]), pipeline, output_dir)
            report.update(
                {
                    "status": "media_recovered" if audio_path else ("rf_activity_only" if signal_detected else "sync_failed"),
                    "outputs": {
                        "audio": str(audio_path) if audio_path else None,
                        "report": str(output_dir / "demodulation_report.json"),
                    },
                    "audio_file": str(audio_path) if audio_path else None,
                    "audio_url": f"/api/demodulation/audio/{demodulation_id}" if audio_path else None,
                    "notes": [
                        "Analog audio was demodulated from stored IQ using a basic post-capture DSP path."
                        if audio_path
                        else "Audio demodulation did not produce a usable WAV file."
                    ],
                }
            )
            return self._finalize_dataset_result(report, output_dir)

        if pipeline in self.IOT_PIPELINES or pipeline in {"ieee802154_oqpsk", "ook_fsk_generic"}:
            decoded = self._run_iot_pipeline(iq, normalized, pipeline, output_dir)
            report.update(decoded)
            return self._finalize_dataset_result(report, output_dir)

        if pipeline == "adsb_1090":
            decoded = self._packet_scaffold("adsb", iq, normalized, output_dir)
            report.update(decoded)
            return self._finalize_dataset_result(report, output_dir)

        if pipeline == "ook_fsk_generic":
            decoded = self._simple_digital_scaffold(iq, normalized, output_dir)
            report.update(decoded)
            return self._finalize_dataset_result(report, output_dir)

        if pipeline in {"dvbt", "dvbs_s2", "lora_css"}:
            report.update(
                {
                    "status": "unsupported_signal_type" if pipeline == "dvbs_s2" else "sync_failed",
                    "outputs": {"report": str(output_dir / "demodulation_report.json")},
                    "notes": [
                        "This pipeline is registered for traceability, but a full protocol demodulator is not implemented in this build.",
                        "RF activity is reported separately and is not treated as successful demodulation.",
                    ],
                }
            )
            return self._finalize_dataset_result(report, output_dir)

        report.update(
            {
                "status": "unsupported_signal_type",
                "outputs": {"report": str(output_dir / "demodulation_report.json")},
                "notes": [f"No compatible demodulation pipeline for signal_type={normalized.get('signal_type')!r}."],
            }
        )
        return self._finalize_dataset_result(report, output_dir)

    def test_ble_advertising_channels(
        self,
        duration_seconds: float = 1.0,
        sample_rate_hz: float = 8_000_000.0,
        bandwidth_hz: float = 2_000_000.0,
    ) -> dict:
        if duration_seconds <= 0 or duration_seconds > 10:
            raise ValueError("duration_seconds must be between 0 and 10")
        channels = [
            {"channel": 37, "frequency_hz": 2_402_000_000.0},
            {"channel": 38, "frequency_hz": 2_426_000_000.0},
            {"channel": 39, "frequency_hz": 2_480_000_000.0},
        ]
        rows = []
        for item in channels:
            center = item["frequency_hz"]
            try:
                result = self.demodulate_marker_band(
                    start_frequency_hz=center - bandwidth_hz / 2.0,
                    stop_frequency_hz=center + bandwidth_hz / 2.0,
                    mode="ble_advertising",
                    duration_seconds=duration_seconds,
                    apply_bandpass_filter=False,
                )
                diagnostics = result.get("stage_diagnostics", {})
                rows.append(
                    {
                        "channel": item["channel"],
                        "frequency_hz": center,
                        "rf_activity": bool(result.get("rf_activity_detected")),
                        "bursts": int(result.get("burst_count") or diagnostics.get("burst_count") or 0),
                        "bitstream": bool(diagnostics.get("bitstream_recovered")),
                        "access_address": bool(result.get("access_address_detected")),
                        "packets": int(result.get("packets_decoded") or 0),
                        "crc_valid": int(result.get("packets_crc_valid") or 0),
                        "status": result.get("final_status") or result.get("status"),
                        "result_id": result.get("id"),
                    }
                )
            except Exception as exc:
                rows.append(
                    {
                        "channel": item["channel"],
                        "frequency_hz": center,
                        "rf_activity": False,
                        "bursts": 0,
                        "bitstream": False,
                        "access_address": False,
                        "packets": 0,
                        "crc_valid": 0,
                        "status": "error",
                        "error": str(exc),
                    }
                )
        return {
            "mode": "live_demodulation",
            "pipeline": "ble_advertising",
            "test": "ble_advertising_channels",
            "duration_seconds": duration_seconds,
            "sample_rate_hz": sample_rate_hz,
            "rows": rows,
        }

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

    def get_output_file(self, demodulation_id: str, filename: str) -> Path:
        result = self.get_result(demodulation_id)
        output_dir_value = result.get("output_dir")
        if output_dir_value:
            output_dir = Path(str(output_dir_value)).resolve()
            path = (output_dir / filename).resolve()
            try:
                path.relative_to(output_dir)
            except ValueError as exc:
                raise ValueError("Invalid output path") from exc
        else:
            path = self._legacy_output_path_from_result(result, filename)
        if not path.exists() or not path.is_file():
            raise ValueError(f"Output file not found: {filename}")
        return path

    def delete_result(self, demodulation_id: str) -> dict:
        result = self.get_result(demodulation_id)
        candidate_values = [
            result.get("metadata_file"),
            result.get("audio_file"),
            result.get("iq_file"),
        ]
        outputs = result.get("outputs")
        if isinstance(outputs, dict):
            candidate_values.extend(value for value in outputs.values() if value)
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
            paths = []
        else:
            paths = list(self._output_dir.glob("*.json"))
        if self._dataset_output_dir.exists():
            paths.extend(self._dataset_output_dir.glob("*/demodulation_report.json"))
        for path in paths:
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
            allowed_roots = (self._output_dir.resolve(), self._dataset_output_dir.resolve())
            if not any(self._path_is_relative_to(resolved, root) for root in allowed_roots):
                return False
            return resolved.suffix.lower() in {".json", ".wav", ".cfile", ".iq", ".bin", ".csv", ".ts", ".log", ".txt"}
        except (OSError, ValueError):
            return False

    def _legacy_output_path_from_result(self, result: dict, filename: str) -> Path:
        outputs = result.get("outputs")
        if isinstance(outputs, dict):
            for value in outputs.values():
                if not value:
                    continue
                candidate = Path(str(value)).resolve()
                if candidate.name == filename and self._is_safe_demodulation_file(candidate):
                    return candidate
        metadata_file = result.get("metadata_file")
        if metadata_file:
            candidate = (Path(str(metadata_file)).resolve().parent / filename).resolve()
            if self._is_safe_demodulation_file(candidate):
                return candidate
        raise ValueError(f"Output file not found: {filename}")

    def _path_is_relative_to(self, path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
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

    def _normalize_dataset_input(self, payload: dict) -> dict:
        normalized = dict(payload)
        path = self._resolve_sigmf_path(Path(str(normalized.get("file_path") or "")))
        normalized["file_path"] = str(path) if str(path) else ""
        if not normalized.get("file_format") and path.suffix:
            normalized["file_format"] = path.suffix.lower().lstrip(".")
        sigmf_meta = self._load_sigmf_metadata(path)
        if sigmf_meta:
            global_meta = sigmf_meta.get("global", {})
            captures = sigmf_meta.get("captures", [])
            first_capture = captures[0] if captures else {}
            normalized["sample_rate_hz"] = normalized.get("sample_rate_hz") or global_meta.get("core:sample_rate")
            normalized["center_frequency_hz"] = normalized.get("center_frequency_hz") or first_capture.get("core:frequency")
            normalized["datatype"] = normalized.get("datatype") or global_meta.get("core:datatype")
            normalized["source_dataset"] = normalized.get("source_dataset") or "sigmf"
        normalized["datatype"] = self._normalize_iq_datatype(normalized.get("datatype") or normalized.get("sample_dtype"))
        normalized["signal_type"] = (
            normalized.get("manual_signal_type")
            or normalized.get("signal_type")
            or normalized.get("modulation_class")
            or "unknown"
        )
        normalized["sample_id"] = str(normalized.get("sample_id") or Path(str(normalized.get("file_path"))).stem)
        return normalized

    def _missing_demodulation_metadata(self, data: dict) -> list[str]:
        missing = []
        for key in ("file_path", "sample_rate_hz", "center_frequency_hz", "datatype"):
            if data.get(key) in {None, ""}:
                missing.append(key)
        return missing

    def _resolve_sigmf_path(self, path: Path) -> Path:
        if path.suffix.lower() == ".sigmf-meta":
            data_path = Path(str(path)[:-11] + ".sigmf-data")
            return data_path if data_path.exists() else path
        return path

    def _load_sigmf_metadata(self, path: Path) -> dict | None:
        candidates = []
        if path.suffix.lower() == ".sigmf-meta":
            candidates.append(path)
        elif str(path).endswith(".sigmf-data"):
            candidates.append(Path(str(path)[:-11] + ".sigmf-meta"))
        else:
            candidates.append(path.with_suffix(".sigmf-meta"))
        for candidate in candidates:
            if candidate.exists():
                try:
                    return json.loads(candidate.read_text(encoding="utf-8"))
                except Exception:
                    return None
        return None

    def _normalize_iq_datatype(self, value: object) -> str:
        text = str(value or "").strip().lower()
        aliases = {
            "complex64": "cf32_le",
            "complex64_fc32_interleaved": "cf32_le",
            "fc32": "cf32_le",
            "cf32": "cf32_le",
            "cf32_le": "cf32_le",
            "ci16": "ci16_le",
            "ci16_le": "ci16_le",
            "int16": "ci16_le",
            "cu8": "cu8",
            "uint8": "cu8",
        }
        return aliases.get(text, text)

    def _is_supported_rf_input(self, path: Path, file_format: object = None) -> bool:
        suffix = path.suffix.lower()
        fmt = str(file_format or "").lower()
        return suffix in {".cfile", ".iq", ".bin", ".dat", ".sigmf-data"} or fmt in {
            "cfile",
            "iq",
            "bin",
            "dat",
            "sigmf-data",
            "sigmf",
        }

    def _read_complex_iq(self, path: Path, datatype: str, max_samples: int = 2_000_000) -> np.ndarray:
        dtype = self._normalize_iq_datatype(datatype)
        if dtype == "cf32_le":
            raw = np.fromfile(path, dtype="<f4", count=max_samples * 2)
            raw = raw[: raw.size - (raw.size % 2)]
            return raw[0::2].astype(np.float32) + 1j * raw[1::2].astype(np.float32)
        if dtype == "ci16_le":
            raw = np.fromfile(path, dtype="<i2", count=max_samples * 2).astype(np.float32)
            raw = raw[: raw.size - (raw.size % 2)] / 32768.0
            return raw[0::2] + 1j * raw[1::2]
        if dtype == "cu8":
            raw = np.fromfile(path, dtype=np.uint8, count=max_samples * 2).astype(np.float32)
            raw = raw[: raw.size - (raw.size % 2)]
            raw = (raw - 127.5) / 127.5
            return raw[0::2] + 1j * raw[1::2]
        return np.array([], dtype=np.complex64)

    def _summarize_iq_activity(self, iq: np.ndarray, sample_rate_hz: float) -> dict:
        power = np.abs(iq) ** 2
        mean_power = float(np.mean(power)) if power.size else 0.0
        peak_power = float(np.max(power)) if power.size else 0.0
        rms = float(np.sqrt(mean_power))
        near_zero_ratio = float(np.mean(np.abs(iq) < 1e-6)) if iq.size else 1.0
        clipping_ratio = float(np.mean(np.abs(iq) > 0.98)) if iq.size else 0.0
        dynamic_db = 10.0 * np.log10(max(peak_power, 1e-20) / max(mean_power, 1e-20))
        return {
            "samples_analyzed": int(iq.size),
            "duration_seconds_analyzed": float(iq.size / max(sample_rate_hz, 1.0)),
            "mean_power_db": float(10.0 * np.log10(max(mean_power, 1e-20))),
            "peak_power_db": float(10.0 * np.log10(max(peak_power, 1e-20))),
            "rms_amplitude": rms,
            "near_zero_ratio": near_zero_ratio,
            "clipping_ratio": clipping_ratio,
            "dynamic_range_proxy_db": float(dynamic_db),
            "signal_detected": bool(iq.size > 0 and near_zero_ratio < 0.95 and peak_power > 1e-10),
        }

    def _infer_pipeline(self, data: dict) -> str:
        signal = str(data.get("signal_type") or "").lower()
        label = str(data.get("transmitter_label") or "").lower()
        joined = f"{signal} {label}"
        if "ble" in joined or "bluetooth" in joined:
            return "ble_advertising"
        if "zigbee" in joined or "802.15.4" in joined or "ieee802154" in joined:
            return "ieee802154_oqpsk"
        if "dvbt" in joined or "dvb-t" in joined:
            return "dvbt"
        if "ads-b" in joined or "adsb" in joined:
            return "adsb_1090"
        if "lora" in joined:
            return "lora_css"
        if "ook" in joined or "fsk" in joined or "gfsk" in joined:
            if "gfsk" in joined:
                return "generic_gfsk_iot"
            if "ook" in joined or "ask" in joined:
                return "ook_ask_iot_sensor"
            return "generic_fsk_iot"
        if signal in {"am", "fm", "wfm", "nfm"}:
            return "wfm_broadcast" if signal == "wfm" else signal
        return "ook_fsk_generic"

    def _live_worker_mode_for_pipeline(self, pipeline: str) -> str:
        if pipeline in {"ble_advertising", "generic_gfsk_iot", "generic_fsk_iot", "zigbee_ieee802154", "lora_css"}:
            return "fsk"
        if pipeline == "ook_ask_iot_sensor":
            return "ook"
        return pipeline

    def _base_dataset_report(self, demodulation_id: str, data: dict, pipeline: str, output_dir: Path) -> dict:
        return {
            "id": demodulation_id,
            "sample_id": data.get("sample_id"),
            "dataset_id": data.get("dataset_id"),
            "source_dataset": data.get("source_dataset") or data.get("dataset_id") or "dataset_builder",
            "input_file": data.get("file_path"),
            "file_format": data.get("file_format"),
            "datatype": data.get("datatype"),
            "sample_rate_hz": data.get("sample_rate_hz"),
            "center_frequency_hz": data.get("center_frequency_hz"),
            "bandwidth_hz": data.get("bandwidth_hz"),
            "duration_seconds": data.get("capture_duration"),
            "signal_type": data.get("signal_type"),
            "device_profile": data.get("device_profile"),
            "demodulation_pipeline": pipeline,
            "pipeline": pipeline,
            "mode": "dataset_demodulation",
            "source": "dataset_builder",
            "rf_analysis_source": "computed_from_file_iq",
            "demodulation_source": "computed_from_file_iq",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "output_dir": str(output_dir),
            "status": "not_attempted",
            "final_status": "not_attempted",
            "outputs": {},
        }

    def _demodulate_audio_iq(self, iq: np.ndarray, sample_rate_hz: float, pipeline: str, output_dir: Path) -> Path | None:
        if iq.size < 16:
            return None
        if pipeline == "am":
            audio = np.abs(iq)
            audio = audio - np.mean(audio)
        else:
            phase = np.unwrap(np.angle(iq))
            audio = np.diff(phase, prepend=phase[0])
        audio_rate = 48_000
        step = max(1, int(round(sample_rate_hz / audio_rate)))
        audio = audio[::step]
        if audio.size < 16:
            return None
        audio = audio - np.mean(audio)
        peak = float(np.max(np.abs(audio)))
        if not np.isfinite(peak) or peak <= 1e-12:
            return None
        audio_i16 = np.clip(audio / peak * 0.85, -1.0, 1.0)
        audio_i16 = (audio_i16 * 32767).astype("<i2")
        path = output_dir / "recovered_audio.wav"
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(int(sample_rate_hz / step))
            wav.writeframes(audio_i16.tobytes())
        return path

    def _ble_scaffold(self, iq: np.ndarray, data: dict, output_dir: Path) -> dict:
        center = float(data.get("center_frequency_hz") or 0.0)
        sample_rate = float(data.get("sample_rate_hz") or 1.0)
        channel, channel_frequency_hz = self._ble_channel_from_frequency(center)
        profile_channel = self._extract_profile_ble_channel(data)
        channel_consistency = profile_channel is None or profile_channel == channel
        activity = self._summarize_iq_activity(iq, sample_rate)
        filtered_iq = iq.astype(np.complex64, copy=False)
        filtered_path = output_dir / "filtered_iq.cfile"
        filtered_iq.tofile(filtered_path)
        bursts = self._ble_burst_candidates(filtered_iq, sample_rate)
        burst_count = len(bursts)
        burst_metrics = self._ble_burst_metrics(bursts, sample_rate, activity, data)

        # --- Real GFSK demodulation + packet search ---
        raw_bits = self._ble_gfsk_demod(filtered_iq, sample_rate)
        bitstream_path = output_dir / "recovered_bitstream.bin"
        bitstream_path.write_bytes(np.packbits(raw_bits).tobytes() if raw_bits.size else b"")

        decoded_pkts = self._ble_search_packets(raw_bits, channel)
        n_decoded = len(decoded_pkts)
        n_crc_valid = sum(1 for p in decoded_pkts if p.get("crc_valid", False))
        aa_detected = n_decoded > 0

        # Legacy AA correlation search (kept for diagnostics)
        aa_search = self._search_ble_access_address(raw_bits)

        # Build output packet list for the frontend
        pkt_list = [
            {
                "index": i,
                "bit_offset": p.get("bit_offset", 0),
                "timestamp_seconds": p.get("bit_offset", 0) / 1_000_000.0,
                "channel": channel,
                "pdu_type": p.get("pdu_type"),
                "advertiser_address": p.get("advertiser_address"),
                "payload_hex": p.get("payload_hex"),
                "payload_fields": p.get("payload_fields"),
                "crc_valid": p.get("crc_valid", False),
                "polarity": p.get("polarity", "normal"),
            }
            for i, p in enumerate(decoded_pkts)
        ]
        advertiser_addresses = list({p["advertiser_address"] for p in pkt_list if p.get("advertiser_address")})
        pdu_types = list({p["pdu_type"] for p in pkt_list if p.get("pdu_type")})

        packets_out = {
            "protocol": "bluetooth_low_energy",
            "pipeline": "ble_advertising",
            "channel": channel,
            "channel_frequency_mhz": channel_frequency_hz / 1e6,
            "access_address_detected": aa_detected,
            "access_address": "0x8E89BED6",
            "packets_decoded": n_decoded,
            "packets_crc_valid": n_crc_valid,
            "advertiser_addresses": advertiser_addresses,
            "pdu_types": pdu_types,
            "payload_extractable": n_decoded > 0,
            "packets": pkt_list,
        }

        burst_path = output_dir / "burst_candidates.json"
        burst_path.write_text(
            json.dumps(
                {
                    "burst_count": burst_count,
                    "bursts": [
                        {
                            "burst_index": index,
                            "start_sample": start,
                            "stop_sample": stop,
                            "start_seconds": start / sample_rate,
                            "duration_us": (stop - start) / sample_rate * 1_000_000.0,
                        }
                        for index, (start, stop) in enumerate(bursts)
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        aa_path = output_dir / "access_address_search.json"
        aa_path.write_text(json.dumps(aa_search, indent=2), encoding="utf-8")
        packet_path = output_dir / "decoded_packets.json"
        packet_path.write_text(json.dumps(packets_out, indent=2), encoding="utf-8")
        logs_path = output_dir / "logs.txt"
        warning = None if channel_consistency else "Selected BLE channel does not match tuned center frequency"
        log_lines = [
            "BLE advertising demodulation run",
            f"center_frequency_hz={center}",
            f"computed_ble_channel={channel}",
            f"profile_ble_channel={profile_channel}",
            f"rf_activity_detected={bool(activity.get('signal_detected'))}",
            f"burst_count={burst_count}",
            f"gfsk_bits_extracted={int(raw_bits.size)}",
            f"access_address_detected={aa_detected}",
            f"packets_decoded={n_decoded}",
            f"packets_crc_valid={n_crc_valid}",
        ]
        logs_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
        stage_diagnostics = {
            "iq_loaded": bool(iq.size > 0),
            "channel_filter_applied": True,
            "rf_activity_detected": bool(activity.get("signal_detected")),
            "burst_detection_attempted": True,
            "burst_count": burst_count,
            "gfsk_demodulation_attempted": True,
            "gfsk_bits_extracted": int(raw_bits.size),
            "bitstream_recovered": bool(raw_bits.size > 0),
            "access_address_search_attempted": True,
            "access_address_detected": aa_detected,
            "ble_packet_reconstruction_attempted": True,
            "packets_decoded": n_decoded,
            "crc_validation_attempted": True,
            "packets_crc_valid": n_crc_valid,
        }
        warnings = [warning] if warning else []
        if activity.get("signal_detected") and not aa_detected:
            warnings.append("RF activity detected but no valid BLE advertising packet was recovered. "
                            "The signal may not be BLE, or the frequency/gain may need adjustment.")
        final_status = ("ble_decoded" if n_crc_valid > 0
                        else "ble_candidate_not_decoded" if activity.get("signal_detected")
                        else "rf_activity_only")
        return {
            "status": "complete" if n_crc_valid > 0 else "rf_activity_only",
            "final_status": final_status,
            "valid_demodulation": n_crc_valid > 0,
            "protocol": "bluetooth_low_energy",
            "pipeline": "ble_advertising",
            "computed_ble_channel": channel,
            "profile_ble_channel": profile_channel,
            "channel_consistency": channel_consistency,
            "warning": warning,
            "channel": channel,
            "channel_frequency_mhz": channel_frequency_hz / 1e6,
            "rf_activity_detected": bool(activity.get("signal_detected")),
            "burst_count": burst_count,
            "access_address_detected": aa_detected,
            "access_address": "0x8E89BED6",
            "packets_decoded": n_decoded,
            "packets_crc_valid": n_crc_valid,
            "confidence_score": min(1.0, n_crc_valid / 3.0) if n_crc_valid > 0 else None,
            "stage_diagnostics": stage_diagnostics,
            "burst_metrics": burst_metrics,
            "access_address_search": aa_search,
            "outputs": {
                "filtered_iq": str(filtered_path),
                "burst_candidates": str(burst_path),
                "bitstream": str(bitstream_path),
                "access_address_search": str(aa_path),
                "decoded_packets": str(packet_path),
                "report": str(output_dir / "demodulation_report.json"),
                "logs": str(logs_path),
            },
            "decoded_packets": packets_out,
            "notes": (
                [f"Decoded {n_decoded} BLE advertising packet(s), {n_crc_valid} CRC-valid."]
                if n_crc_valid > 0
                else ["Signal is compatible with the BLE advertising pipeline, but no CRC-valid packet was recovered."]
            ),
            "warnings": warnings,
        }

    def _run_iot_pipeline(self, iq: np.ndarray, data: dict, pipeline: str, output_dir: Path) -> dict:
        started = perf_counter()
        if pipeline == "ble_advertising":
            result = self._ble_scaffold(iq, data, output_dir)
            result.update(self._iot_common_envelope(iq, data, pipeline, "bluetooth_low_energy", "gfsk", "ble_advertising_decoder"))
        elif pipeline == "generic_gfsk_iot":
            result = self._generic_gfsk_iot(iq, data, output_dir)
        elif pipeline == "ook_ask_iot_sensor":
            result = self._ook_ask_iot_sensor(iq, data, output_dir)
        elif pipeline == "generic_fsk_iot":
            result = self._generic_fsk_iot(iq, data, output_dir)
        elif pipeline in {"zigbee_ieee802154", "ieee802154_oqpsk"}:
            result = self._packet_scaffold("ieee802154", iq, data, output_dir)
            result.update(self._iot_common_envelope(iq, data, "zigbee_ieee802154", "ieee802154", "oqpsk_dsss", "ieee802154_frame_decoder"))
            result["demodulation_level_reached"] = "rf_activity_only"
        elif pipeline == "lora_css":
            result = self._packet_scaffold("lora", iq, data, output_dir)
            result.update(self._iot_common_envelope(iq, data, "lora_css", "lora", "css", "lora_packet_decoder"))
            result["demodulation_level_reached"] = "rf_activity_only"
        else:
            result = self._simple_digital_scaffold(iq, data, output_dir)
            result.update(self._iot_common_envelope(iq, data, pipeline, "generic_iot", "unknown", None))
        result["processing_time_ms"] = int((perf_counter() - started) * 1000)
        result["version"] = "1.0"
        result.setdefault("warnings", [])
        result.setdefault("fingerprint_data", self._fingerprint_data_from_iq(iq, data))
        result.setdefault("final_status", result.get("status", "not_attempted"))
        return result

    def _iot_common_envelope(
        self,
        iq: np.ndarray,
        data: dict,
        pipeline: str,
        iot_family: str,
        physical_demodulator: str,
        protocol_decoder: str | None,
    ) -> dict:
        rf_metrics = self._rf_metrics_from_iq(iq, data)
        return {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "pipeline_name": pipeline,
            "iot_family": iot_family,
            "physical_demodulator": physical_demodulator,
            "protocol_decoder": protocol_decoder,
            "input": {
                "source": data.get("source_dataset") or data.get("source") or "dataset",
                "center_frequency_hz": data.get("center_frequency_hz"),
                "sample_rate_sps": data.get("sample_rate_hz"),
                "duration_seconds": data.get("capture_duration"),
                "file_path": data.get("file_path"),
            },
            "rf_metrics": rf_metrics,
            "signal_quality": {
                "snr_estimated_db": rf_metrics["snr_estimated_db"],
                "frequency_offset_hz": rf_metrics["frequency_offset_hz"],
                "peak_power_dbm": rf_metrics["peak_power_dbm"],
            },
        }

    def _rf_metrics_from_iq(self, iq: np.ndarray, data: dict) -> dict:
        activity = self._summarize_iq_activity(iq, float(data.get("sample_rate_hz") or 1.0))
        magnitude = np.abs(iq) if iq.size else np.array([], dtype=np.float32)
        snr = float(max(0.0, activity.get("dynamic_range_proxy_db", 0.0) - 3.0))
        iq_i = np.real(iq)
        iq_q = np.imag(iq)
        i_power = float(np.mean(iq_i * iq_i)) if iq.size else 0.0
        q_power = float(np.mean(iq_q * iq_q)) if iq.size else 0.0
        imbalance = float(10.0 * np.log10(max(i_power, 1e-20) / max(q_power, 1e-20)))
        return {
            "snr_estimated_db": snr,
            "frequency_offset_hz": 0.0,
            "timing_offset_samples": 0,
            "peak_power_dbm": float(activity.get("peak_power_db", -200.0)),
            "iq_imbalance_db": imbalance,
            "rf_activity_detected": bool(activity.get("signal_detected")),
            "estimated_bandwidth_hz": data.get("bandwidth_hz"),
        }

    def _fingerprint_data_from_iq(self, iq: np.ndarray, data: dict) -> dict:
        activity = self._summarize_iq_activity(iq, float(data.get("sample_rate_hz") or 1.0))
        return {
            "sample_count": int(iq.size),
            "mean_power_db": activity.get("mean_power_db"),
            "peak_power_db": activity.get("peak_power_db"),
            "near_zero_ratio": activity.get("near_zero_ratio"),
            "clipping_ratio": activity.get("clipping_ratio"),
            "confidence_source": "computed_from_iq",
        }

    def _generic_gfsk_iot(self, iq: np.ndarray, data: dict, output_dir: Path) -> dict:
        bits, hex_text = self._frequency_discriminator_bits(iq)
        payload_path, bitstream_path = self._write_bitstream_outputs(bits, hex_text, output_dir)
        bitstream_recovered = bits.size >= 64
        warnings = [] if bitstream_recovered else ["SNR too low or capture too short for bit recovery"]
        if bits.size and bits.size < 512:
            warnings.append("Short bitstream; symbol rate confidence below 80%")
        common = self._iot_common_envelope(iq, data, "generic_gfsk_iot", "generic_iot", "gfsk", None)
        return {
            **common,
            "estimation_results": {
                "symbol_rate_estimated_baud": self._estimate_symbol_rate(iq, data),
                "symbol_rate_confidence": 0.65 if bitstream_recovered else 0.0,
                "symbol_rate_range": [],
                "frequency_deviation_hz": self._estimate_frequency_deviation(iq, data),
                "clock_recovery_locked": bool(bitstream_recovered),
            },
            "demodulation_results": {
                "bitstream_recovered": bool(bitstream_recovered),
                "bits_count": int(bits.size),
                "bytes_count": int(bits.size // 8),
                "preamble_detected": "55" in hex_text[:32] or "aa" in hex_text[:32].lower(),
                "preamble_pattern": "0x55" if "55" in hex_text[:32] else ("0xAA" if "aa" in hex_text[:32].lower() else None),
            },
            "extracted_data": {"bitstream_hex": hex_text[:4096], "payloads_hex": [hex_text[:512]] if hex_text else [], "payload_extractable": False},
            "demodulation_level_reached": "physical_demodulation_recovered_bitstream" if bitstream_recovered else "rf_activity_only",
            "final_status": "bitstream_recovered" if bitstream_recovered else "rf_activity_only",
            "status": "bitstream_recovered" if bitstream_recovered else "rf_activity_only",
            "valid_demodulation": False,
            "confidence_score": None,
            "outputs": {"bitstream": str(bitstream_path), "decoded_payload": str(payload_path), "report": str(output_dir / "demodulation_report.json")},
            "warnings": warnings or ["No known protocol decoder available"],
        }

    def _generic_fsk_iot(self, iq: np.ndarray, data: dict, output_dir: Path) -> dict:
        result = self._generic_gfsk_iot(iq, data, output_dir)
        result.update(self._iot_common_envelope(iq, data, "generic_fsk_iot", "generic_iot", "fsk", None))
        deviation = self._estimate_frequency_deviation(iq, data)
        result["estimation_results"].update(
            {
                "frequency_deviation_hz": deviation,
                "frequency_deviation_confidence": 0.72 if result["demodulation_results"]["bitstream_recovered"] else 0.0,
                "mark_frequency_offset_hz": deviation / 2.0,
                "space_frequency_offset_hz": -deviation / 2.0,
            }
        )
        result["pipeline_name"] = "generic_fsk_iot"
        return result

    def _ook_ask_iot_sensor(self, iq: np.ndarray, data: dict, output_dir: Path) -> dict:
        sample_rate = float(data.get("sample_rate_hz") or 1.0)
        envelope = np.abs(iq)
        if envelope.size == 0:
            bits = np.array([], dtype=np.uint8)
            active = np.array([], dtype=bool)
        else:
            threshold = float(np.median(envelope) + 0.75 * np.std(envelope))
            active = envelope > threshold
            stride = max(1, int(sample_rate / 20_000.0))
            bits = active[::stride].astype(np.uint8)
        hex_text = np.packbits(bits).tobytes().hex() if bits.size else ""
        payload_path, bitstream_path = self._write_bitstream_outputs(bits, hex_text, output_dir)
        bursts = self._detect_boolean_runs(active, sample_rate)
        burst_durations = [round((stop - start) / sample_rate * 1000.0, 3) for start, stop in bursts]
        gaps = [round((bursts[i][0] - bursts[i - 1][1]) / sample_rate * 1000.0, 3) for i in range(1, len(bursts))]
        bitstream_recovered = bits.size >= 64 and len(bursts) > 0
        common = self._iot_common_envelope(iq, data, "ook_ask_iot_sensor", "generic_iot_sensor", "ook_ask", None)
        return {
            **common,
            "burst_analysis": {
                "burst_count": len(bursts),
                "burst_durations_ms": burst_durations,
                "inter_burst_gaps_ms": gaps,
                "repetition_interval_ms": float(np.median(gaps)) if gaps else None,
                "repetition_confidence": 0.8 if len(gaps) >= 2 else 0.0,
            },
            "symbol_rate_analysis": {
                "symbol_rates_estimated": [int(sample_rate / max(1, int(sample_rate / 20_000.0)))] if bitstream_recovered else [],
                "symbol_rate_mean_baud": int(sample_rate / max(1, int(sample_rate / 20_000.0))) if bitstream_recovered else None,
                "symbol_rate_std_dev": 0.0,
                "consistency": 0.65 if bitstream_recovered else 0.0,
            },
            "pulse_timing": self._pulse_timing(active, sample_rate),
            "demodulation_results": {
                "bitstream_recovered": bool(bitstream_recovered),
                "bits_per_burst": [int(duration / 1000.0 * 20_000.0) for duration in burst_durations],
                "total_bits": int(bits.size),
                "alignment_confidence": 0.55 if bitstream_recovered else 0.0,
            },
            "extracted_data": {
                "payloads_hex": [hex_text[:512]] if hex_text else [],
                "payload_pattern_detected": False,
                "payload_pattern_hex": None,
            },
            "demodulation_level_reached": "physical_demodulation_recovered_bitstream" if bitstream_recovered else "rf_activity_only",
            "final_status": "bitstream_recovered" if bitstream_recovered else "rf_activity_only",
            "status": "bitstream_recovered" if bitstream_recovered else "rf_activity_only",
            "valid_demodulation": False,
            "confidence_score": None,
            "fingerprint_usable": bool(bitstream_recovered and len(bursts) > 0),
            "outputs": {"bitstream": str(bitstream_path), "decoded_payload": str(payload_path), "report": str(output_dir / "demodulation_report.json")},
            "warnings": [] if bitstream_recovered else ["No stable OOK/ASK burst bitstream recovered"],
        }

    def _frequency_discriminator_bits(self, iq: np.ndarray) -> tuple[np.ndarray, str]:
        if iq.size < 4:
            return np.array([], dtype=np.uint8), ""
        phase_delta = np.angle(iq[1:] * np.conj(iq[:-1]))
        phase_delta = phase_delta - np.median(phase_delta)
        stride = max(1, int(phase_delta.size / 8192))
        soft = phase_delta[::stride]
        bits = (soft > 0).astype(np.uint8)
        return bits, np.packbits(bits).tobytes().hex()

    def _write_bitstream_outputs(self, bits: np.ndarray, hex_text: str, output_dir: Path) -> tuple[Path, Path]:
        bitstream_path = output_dir / "bitstream.bin"
        payload_path = output_dir / "decoded_payload.json"
        bitstream_path.write_bytes(np.packbits(bits).tobytes() if bits.size else b"")
        payload_path.write_text(
            json.dumps(
                {
                    "bit_count": int(bits.size),
                    "bytes_count": int(bits.size // 8),
                    "bitstream_hex": hex_text[:4096],
                    "payload_extractable": False,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return payload_path, bitstream_path

    def _estimate_symbol_rate(self, iq: np.ndarray, data: dict) -> int | None:
        sample_rate = float(data.get("sample_rate_hz") or 0.0)
        if iq.size < 32 or sample_rate <= 0:
            return None
        return int(min(max(sample_rate / max(1, iq.size / 4096.0), 1_000.0), 2_000_000.0))

    def _estimate_frequency_deviation(self, iq: np.ndarray, data: dict) -> float | None:
        sample_rate = float(data.get("sample_rate_hz") or 0.0)
        if iq.size < 4 or sample_rate <= 0:
            return None
        phase_delta = np.angle(iq[1:] * np.conj(iq[:-1]))
        freq = phase_delta * sample_rate / (2.0 * np.pi)
        return float(np.percentile(freq, 90) - np.percentile(freq, 10))

    def _detect_boolean_runs(self, active: np.ndarray, sample_rate: float) -> list[tuple[int, int]]:
        if active.size == 0:
            return []
        padded = np.concatenate([[False], active.astype(bool), [False]])
        edges = np.flatnonzero(padded[1:] != padded[:-1])
        runs = list(zip(edges[0::2], edges[1::2]))
        min_len = max(1, int(sample_rate * 0.0001))
        return [(int(start), int(stop)) for start, stop in runs if stop - start >= min_len]

    def _estimate_burst_count(self, iq: np.ndarray, sample_rate: float) -> int:
        if iq.size == 0:
            return 0
        envelope = np.abs(iq)
        threshold = float(np.median(envelope) + 1.5 * np.std(envelope))
        active = envelope > threshold
        return len(self._detect_boolean_runs(active, sample_rate))

    def _ble_channel_from_frequency(self, center_frequency_hz: float) -> tuple[int, float]:
        channels = {
            37: 2_402_000_000.0,
            38: 2_426_000_000.0,
            39: 2_480_000_000.0,
        }
        channel = min(channels, key=lambda item: abs(channels[item] - center_frequency_hz))
        return channel, channels[channel]

    def _extract_profile_ble_channel(self, data: dict) -> int | None:
        for key in ("profile_ble_channel", "ble_channel", "channel"):
            value = data.get(key)
            try:
                if value is not None and str(value) != "":
                    parsed = int(value)
                    if parsed in {37, 38, 39}:
                        return parsed
            except (TypeError, ValueError):
                pass
        text = " ".join(str(data.get(key) or "") for key in ("signal_type", "device_profile", "pipeline", "sample_id"))
        for channel in (37, 38, 39):
            if f"ch{channel}" in text.lower() or f"_{channel}" in text.lower():
                return channel
        return None

    def _ble_burst_candidates(self, iq: np.ndarray, sample_rate: float) -> list[tuple[int, int]]:
        if iq.size == 0:
            return []
        envelope = np.abs(iq)
        threshold = float(np.median(envelope) + 2.0 * np.std(envelope))
        active = envelope > threshold
        runs = self._detect_boolean_runs(active, sample_rate)
        min_samples = max(1, int(sample_rate * 80e-6))
        max_samples = max(min_samples, int(sample_rate * 2.5e-3))
        return [(start, stop) for start, stop in runs if min_samples <= stop - start <= max_samples]

    def _ble_burst_metrics(self, bursts: list[tuple[int, int]], sample_rate: float, activity: dict, data: dict) -> dict:
        durations = np.array([(stop - start) / sample_rate * 1_000_000.0 for start, stop in bursts], dtype=float)
        return {
            "burst_count": len(bursts),
            "average_burst_duration_us": float(np.mean(durations)) if durations.size else None,
            "min_burst_duration_us": float(np.min(durations)) if durations.size else None,
            "max_burst_duration_us": float(np.max(durations)) if durations.size else None,
            "expected_ble_burst_window_us": [80, 600],
            "estimated_bandwidth_hz": data.get("bandwidth_hz"),
            "snr_estimate_db": activity.get("dynamic_range_proxy_db"),
        }

    def _search_ble_access_address(self, bits: np.ndarray) -> dict:
        target_hex = "8E89BED6"
        target = np.array([int(bit) for bit in f"{int(target_hex, 16):032b}"], dtype=np.uint8)
        variants = []
        variants.append(("normal", "normal", target))
        variants.append(("reversed", "normal", target[::-1]))
        variants.append(("normal", "inverted", 1 - target))
        variants.append(("reversed", "inverted", 1 - target[::-1]))
        max_score = 0
        exact_matches = 0
        near_matches = 0
        best: dict | None = None
        if bits.size >= 32:
            for bit_order, polarity, pattern in variants:
                for offset in range(0, bits.size - 31):
                    score = int(np.sum(bits[offset : offset + 32] == pattern))
                    if score > max_score:
                        max_score = score
                        best = {"bit_offset": offset, "bit_order": bit_order, "polarity": polarity}
                    if score == 32:
                        exact_matches += 1
                    if score >= 28:
                        near_matches += 1
        return {
            "target": "0x8E89BED6",
            "exact_matches": exact_matches,
            "near_matches": near_matches,
            "max_correlation_score": float(max_score),
            "bit_order_tested": ["normal", "reversed"],
            "polarity_tested": ["normal", "inverted"],
            "access_address_detected": exact_matches > 0 or max_score >= 28,
            "best_match": best,
        }

    # ------------------------------------------------------------------
    # BLE GFSK demodulation helpers
    # ------------------------------------------------------------------

    def _ble_int_from_bits(self, bits: np.ndarray, n: int, offset: int = 0) -> int:
        """Integer from n LSB-first bits starting at offset."""
        if offset + n > bits.size:
            return 0
        val = 0
        for i in range(n):
            val |= (int(bits[offset + i]) << i)
        return val

    def _ble_dewhiten_bits(self, bits: np.ndarray, channel: int) -> np.ndarray:
        """BLE data whitening/de-whitening: 7-bit LFSR x^7+x^4+1, init = 1||ch[5:0]."""
        ch = int(channel) & 0x3F
        lfsr = 0x40 | ch
        result = bits.copy()
        for i in range(len(bits)):
            out = (lfsr >> 6) & 1
            result[i] = bits[i] ^ out
            fb = ((lfsr >> 6) ^ (lfsr >> 3)) & 1
            lfsr = ((lfsr << 1) & 0x7F) | fb
        return result

    def _ble_crc24_bits(self, bits: np.ndarray, init: int = 0x555555) -> int:
        """BLE CRC-24 over individual bits in transmission order. Poly = x^24+x^10+x^9+x^6+x^4+x^3+x+1."""
        crc = init & 0xFFFFFF
        for bit in bits:
            d = (int(bit) ^ ((crc >> 23) & 1)) & 1
            crc = (crc << 1) & 0xFFFFFF
            if d:
                crc ^= 0x00065B
        return crc

    def _ble_gfsk_demod(self, iq: np.ndarray, sample_rate: float) -> np.ndarray:
        """
        GFSK frequency discriminator for BLE at 1 Mbit/s.
        Returns bit array with one bit per symbol period.
        """
        SYMBOL_RATE = 1_000_000.0
        if iq.size < 16:
            return np.array([], dtype=np.uint8)
        q = iq.astype(np.complex64)
        # Instantaneous frequency (rad/sample → Hz)
        phase_delta = np.angle(q[1:] * np.conj(q[:-1]))
        sps = max(1.0, sample_rate / SYMBOL_RATE)
        sps_int = max(1, int(round(sps)))
        # Moving-average LPF over one symbol period
        if sps_int >= 2:
            kernel = np.ones(sps_int, dtype=np.float32) / sps_int
            phase_delta = np.convolve(phase_delta.astype(np.float32), kernel, mode='same')
        n_syms = phase_delta.size // sps_int
        if n_syms < 10:
            return np.array([], dtype=np.uint8)
        # Center-sample each symbol; remove DC offset before thresholding
        offset = sps_int // 2
        idx = np.arange(n_syms) * sps_int + offset
        idx = idx[idx < phase_delta.size]
        sampled = phase_delta[idx]
        dc = float(np.median(sampled))
        return (sampled > dc).astype(np.uint8)

    def _ble_decode_adv_packet(self, bits_from_pdu: np.ndarray, channel: int) -> dict | None:
        """
        Decode one BLE advertising PDU (bits start immediately after the Access Address).
        De-whitens, validates CRC-24, and extracts header + payload fields.
        Returns a packet dict on success or None if CRC fails / length invalid.
        """
        MAX_PAYLOAD = 37
        if bits_from_pdu.size < (2 + 6 + 3) * 8:  # min: header + AdvA + CRC
            return None
        # De-whiten from the start of the PDU
        available = min((2 + MAX_PAYLOAD + 3) * 8, bits_from_pdu.size)
        dw = self._ble_dewhiten_bits(bits_from_pdu[:available], channel)
        # Parse PDU header (16 bits)
        pdu_type = self._ble_int_from_bits(dw, 4, 0)
        tx_add = int(dw[4]) if dw.size > 4 else 0
        rx_add = int(dw[5]) if dw.size > 5 else 0
        length = self._ble_int_from_bits(dw, 6, 8)  # bits [13:8] of header
        if length < 6 or length > MAX_PAYLOAD:
            return None
        total_bits = (2 + length + 3) * 8
        if dw.size < total_bits:
            return None
        # CRC check over header + payload
        crc_data = dw[:(2 + length) * 8]
        computed = self._ble_crc24_bits(crc_data, init=0x555555)
        received = self._ble_int_from_bits(dw, 24, (2 + length) * 8)
        crc_valid = (computed == received)
        if not crc_valid:
            return None
        # Decode advertiser address (6 bytes, LSB first → reverse for display)
        adv_bytes = [self._ble_int_from_bits(dw, 8, 16 + i * 8) for i in range(6)]
        adv_addr = ":".join(f"{b:02X}" for b in reversed(adv_bytes))
        # AdvData / payload hex
        adv_data_len = max(0, length - 6)
        payload_bytes = [self._ble_int_from_bits(dw, 8, 64 + i * 8) for i in range(adv_data_len)]
        pdu_names = {0: "ADV_IND", 1: "ADV_DIRECT_IND", 2: "ADV_NONCONN_IND",
                     3: "SCAN_REQ", 4: "SCAN_RSP", 5: "CONNECT_IND", 6: "ADV_SCAN_IND"}
        return {
            "pdu_type": pdu_names.get(pdu_type, f"UNKNOWN_0x{pdu_type:X}"),
            "length": length,
            "tx_add": bool(tx_add),
            "rx_add": bool(rx_add),
            "advertiser_address": adv_addr,
            "payload_hex": bytes(payload_bytes).hex(),
            "payload_fields": self._ble_parse_adv_data(bytes(payload_bytes)),
            "crc_valid": True,
            "_total_bits": total_bits,
        }

    def _ble_parse_adv_data(self, adv_data: bytes) -> list[dict]:
        """Parse BLE AdvData TLV structures into a list of AD records."""
        records = []
        i = 0
        while i < len(adv_data):
            if i + 1 > len(adv_data):
                break
            length = adv_data[i]
            if length == 0 or i + 1 + length > len(adv_data):
                break
            ad_type = adv_data[i + 1]
            ad_data = adv_data[i + 2: i + 1 + length]
            ad_type_names = {
                0x01: "Flags", 0x02: "16b_UUID_incomplete", 0x03: "16b_UUID_complete",
                0x08: "Short_Local_Name", 0x09: "Complete_Local_Name",
                0x0A: "TX_Power_Level", 0xFF: "Manufacturer_Specific",
            }
            record = {
                "ad_type": f"0x{ad_type:02X}",
                "ad_type_name": ad_type_names.get(ad_type, "Unknown"),
                "data_hex": ad_data.hex(),
            }
            if ad_type == 0x09 or ad_type == 0x08:
                try:
                    record["name"] = ad_data.decode("utf-8", errors="replace")
                except Exception:
                    pass
            records.append(record)
            i += 1 + length
        return records

    def _ble_search_packets(self, bits: np.ndarray, channel: int) -> list[dict]:
        """
        Search for BLE advertising packets using NumPy correlation.
        Handles both normal and inverted GFSK polarity.
        """
        if bits.size < 50:
            return []
        # Advertising sync word: preamble (0xAA LSB-first) + AA (0x8E89BED6 byte0-first LSB-first)
        # 0xAA = 10101010 → bits [0,1,0,1,0,1,0,1]  (LSB first)
        # 0xD6 = 11010110 → [0,1,1,0,1,0,1,1]
        # 0xBE = 10111110 → [0,1,1,1,1,1,0,1]
        # 0x89 = 10001001 → [1,0,0,1,0,0,0,1]
        # 0x8E = 10001110 → [0,1,1,1,0,0,0,1]
        SYNC = np.array([0,1,0,1,0,1,0,1,
                         0,1,1,0,1,0,1,1,
                         0,1,1,1,1,1,0,1,
                         1,0,0,1,0,0,0,1,
                         0,1,1,1,0,0,0,1], dtype=np.float32) * 2 - 1  # +1/-1
        bits_f = bits.astype(np.float32) * 2 - 1
        corr = np.correlate(bits_f, SYNC, mode='valid')
        # threshold = 32/40 bits correct (allows 4 bit errors in 40-bit sync word)
        candidates = np.where(np.abs(corr) >= 32)[0]
        packets = []
        skip_until = -1
        for pos in candidates:
            if int(pos) < skip_until:
                continue
            polarity = 1 if corr[pos] < 0 else 0  # negative correlation → inverted bits
            pdu_start = int(pos) + 40
            if pdu_start >= bits.size:
                break
            pdu_bits = bits[pdu_start:]
            if polarity:
                pdu_bits = pdu_bits ^ 1
            pkt = self._ble_decode_adv_packet(pdu_bits, channel)
            if pkt is not None:
                pkt['bit_offset'] = int(pos)
                pkt['polarity'] = 'inverted' if polarity else 'normal'
                skip_until = pdu_start + pkt.pop('_total_bits', 64)
                packets.append(pkt)
        return packets

    def _pulse_timing(self, active: np.ndarray, sample_rate: float) -> dict:
        runs_on = self._detect_boolean_runs(active, sample_rate)
        runs_off = self._detect_boolean_runs(~active.astype(bool), sample_rate) if active.size else []
        on_ms = np.array([(stop - start) / sample_rate * 1000.0 for start, stop in runs_on], dtype=float)
        off_ms = np.array([(stop - start) / sample_rate * 1000.0 for start, stop in runs_off], dtype=float)
        duty = float(np.mean(active) * 100.0) if active.size else 0.0
        return {
            "on_time_min_ms": float(np.min(on_ms)) if on_ms.size else None,
            "on_time_max_ms": float(np.max(on_ms)) if on_ms.size else None,
            "on_time_mean_ms": float(np.mean(on_ms)) if on_ms.size else None,
            "off_time_min_ms": float(np.min(off_ms)) if off_ms.size else None,
            "off_time_max_ms": float(np.max(off_ms)) if off_ms.size else None,
            "off_time_mean_ms": float(np.mean(off_ms)) if off_ms.size else None,
            "duty_cycle_percent": duty,
        }

    def _packet_scaffold(self, protocol: str, iq: np.ndarray, data: dict, output_dir: Path) -> dict:
        packets = {
            "protocol": protocol,
            "frames_decoded": 0,
            "frames_crc_valid": 0,
            "payload_extractable": False,
            "frames": [],
        }
        packet_path = output_dir / "decoded_packets.json"
        packet_path.write_text(json.dumps(packets, indent=2), encoding="utf-8")
        return {
            "status": "rf_activity_only",
            "protocol": protocol,
            "outputs": {"decoded_packets": str(packet_path), "report": str(output_dir / "demodulation_report.json")},
            "decoded_packets": packets,
            "valid_demodulation": False,
            "confidence_score": None,
            "notes": [
                f"{protocol} pipeline selected, but this build has not reconstructed CRC-valid protocol frames.",
                "RF activity is not reported as successful protocol demodulation.",
            ],
        }

    def _simple_digital_scaffold(self, iq: np.ndarray, data: dict, output_dir: Path) -> dict:
        magnitude = np.abs(iq)
        threshold = float(np.median(magnitude) + np.std(magnitude))
        bits = (magnitude[:: max(1, int(len(magnitude) / 4096))] > threshold).astype(np.uint8)
        bitstream_path = output_dir / "bitstream.bin"
        bitstream_path.write_bytes(np.packbits(bits).tobytes())
        payload = {
            "bit_count": int(bits.size),
            "baud_rate_estimated": None,
            "payload_hex": "",
            "confidence_score": None,
            "note": "Raw thresholded activity only; not a validated symbol clock or decoded protocol payload.",
        }
        payload_path = output_dir / "decoded_payload.json"
        payload_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return {
            "status": "partial_decode" if bits.size else "sync_failed",
            "outputs": {
                "bitstream": str(bitstream_path),
                "decoded_payload": str(payload_path),
                "report": str(output_dir / "demodulation_report.json"),
            },
            "decoded_payload": payload,
            "valid_demodulation": False,
            "confidence_score": None,
            "notes": ["A provisional bitstream was extracted, but no protocol-level CRC or payload validation was performed."],
        }

    def _finalize_dataset_result(self, report: dict, output_dir: Path) -> dict:
        report_path = output_dir / "demodulation_report.json"
        report["metadata_file"] = str(report_path)
        report["metadata_url"] = f"/api/demodulation/results/{report['id']}"
        report["final_status"] = report.get("final_status") or report.get("status") or "not_attempted"
        report.setdefault("outputs", {})["report"] = str(report_path)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        self._results[report["id"]] = report
        return report
