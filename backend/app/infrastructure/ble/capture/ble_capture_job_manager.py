from __future__ import annotations

import json
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .ble_capture_metadata import atomic_json, sha256_file, validate_sigmf

CHANNELS = {37: 2_402_000_000, 38: 2_426_000_000, 39: 2_480_000_000}
FORMATS = {"ci8": 2, "ci16_le": 4, "cf32_le": 8}
TERMINAL = {"completed", "failed", "cancelled", "timed_out"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class BleCaptureJobManager:
    def __init__(self, root: Path, devices, capture_service, enabled: bool = False,
                 max_duration_seconds: float = 60.0, minimum_free_bytes: int = 256 * 1024 * 1024) -> None:
        self.root, self.devices, self.capture_service, self.enabled = root, devices, capture_service, enabled
        self.max_duration_seconds, self.minimum_free_bytes = max_duration_seconds, minimum_free_bytes
        root.mkdir(parents=True, exist_ok=True)
        self._lock, self._active, self._cancel = threading.RLock(), None, set()

    def capabilities(self, force_probe: bool = False) -> dict[str, Any]:
        try:
            probe = self.devices.list_devices(force_probe=force_probe)
        except TypeError:
            # Test and third-party adapters may still implement the original
            # zero-argument device enumeration protocol.
            probe = self.devices.list_devices()
        return {**probe, "capture_enabled": self.enabled, "capture_and_decode_enabled": False,
                "default_duration_seconds": 10, "maximum_duration_seconds": self.max_duration_seconds,
                "supported_formats": list(FORMATS), "ble_channels": CHANNELS}

    def resolve_device_id(self, requested_device_id: str | None = None) -> str:
        if hasattr(self.devices, "resolve_device"):
            return str(self.devices.resolve_device(requested_device_id)["device_id"])
        cached = self.devices.cached_device(requested_device_id) if hasattr(self.devices, "cached_device") else None
        if cached: return str(cached["device_id"])
        probe = self.devices.list_devices()
        devices = probe.get("devices", [])
        exact = next((item for item in devices if item.get("device_id") == requested_device_id), None)
        if exact: return str(exact["device_id"])
        if len(devices) == 1: return str(devices[0]["device_id"])
        raise ValueError(f"UNKNOWN_OR_UNAVAILABLE_SDR_DEVICE:{probe.get('reason_code','NO_COMPATIBLE_SDR')}")

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled: raise PermissionError("BLE_IQ_CAPTURE_EXPERIMENTAL_DISABLED")
        request = self._validate(payload)
        with self._lock:
            if self._active: raise RuntimeError("CAPTURE_ALREADY_RUNNING")
            capture_id = "BLE-IQ-" + uuid.uuid4().hex[:12]
            job_dir = self.root / capture_id
            job_dir.mkdir()
            request.update(capture_id=capture_id, created_at_utc=utc_now(),
                           device_args=self.devices.private_args(request["device_id"]))
            atomic_json(job_dir / "request.json", request)
            self._write_job(job_dir, "queued", request=request)
            self._active = capture_id
        threading.Thread(target=self._execute, args=(capture_id,), daemon=True).start()
        return self.get(capture_id)

    def _validate(self, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {"device_id", "ble_channel", "center_frequency_hz", "sample_rate_sps", "bandwidth_hz",
                   "gain_mode", "gain_db", "antenna", "duration_seconds", "sample_format", "description", "purpose",
                   "controlled_transmitter_state", "operator_confirmed", "confirmation_method", "capture_role"}
        unknown = set(payload) - allowed
        if unknown: raise ValueError("UNSUPPORTED_CAPTURE_FIELDS")
        channel = payload.get("ble_channel")
        center = int(payload.get("center_frequency_hz") or CHANNELS.get(channel, 0))
        rate, bandwidth = int(payload.get("sample_rate_sps", 0)), int(payload.get("bandwidth_hz", 0))
        duration, fmt = float(payload.get("duration_seconds", 0)), payload.get("sample_format", "ci8")
        resolved_id = self.resolve_device_id(payload.get("device_id"))
        payload = {**payload, "device_id": resolved_id}
        if hasattr(self.devices, "resolve_device"):
            device = self.devices.resolve_device(resolved_id)
        else:
            device = self.devices.cached_device(resolved_id) if hasattr(self.devices, "cached_device") else None
            if not device:
                probe = self.devices.list_devices()
                device = next(item for item in probe.get("devices", []) if item.get("device_id") == resolved_id)
        if channel not in (*CHANNELS, None) or not 70_000_000 <= center <= 6_000_000_000: raise ValueError("INVALID_FREQUENCY")
        if rate < 1_000_000 or rate > 20_000_000: raise ValueError("UNSUPPORTED_SAMPLE_RATE")
        if bandwidth <= 0 or bandwidth > rate: raise ValueError("UNSUPPORTED_BANDWIDTH")
        if duration <= 0 or duration > self.max_duration_seconds: raise ValueError("INVALID_CAPTURE_DURATION")
        if fmt not in FORMATS: raise ValueError("UNSUPPORTED_SAMPLE_FORMAT")
        if payload.get("controlled_transmitter_state") not in {None, "off", "on", "unknown"}: raise ValueError("INVALID_CONTROLLED_TRANSMITTER_STATE")
        if "operator_confirmed" in payload and not isinstance(payload["operator_confirmed"], bool): raise ValueError("INVALID_OPERATOR_CONFIRMATION")
        if payload.get("confirmation_method") not in {None, "physical_manual_verification"}: raise ValueError("INVALID_CONFIRMATION_METHOD")
        if payload.get("capture_role") not in {None, "background_control_A", "controlled_transmitter_active_B"}: raise ValueError("INVALID_CAPTURE_ROLE")
        antenna = payload.get("antenna")
        if antenna and antenna not in (device.get("antenna_options") or []): raise ValueError("UNSUPPORTED_ANTENNA")
        def supported(value, capability):
            ranges = device.get(capability) or []
            return not ranges or any(float(item["minimum"]) <= value <= float(item["maximum"]) for item in ranges)
        if not supported(center, "frequency_ranges_hz"): raise ValueError("UNSUPPORTED_FREQUENCY")
        if not supported(rate, "sample_rate_ranges_sps"): raise ValueError("UNSUPPORTED_SAMPLE_RATE")
        if not supported(bandwidth, "bandwidth_ranges_hz"): raise ValueError("UNSUPPORTED_BANDWIDTH")
        gain = float(payload.get("gain_db", 0));
        if payload.get("gain_mode", "manual") not in {"manual", "automatic"} or not -20 <= gain <= 100: raise ValueError("INVALID_GAIN")
        expected = int(rate * duration * FORMATS[fmt])
        free = shutil.disk_usage(self.root).free
        if free < expected + self.minimum_free_bytes: raise OSError("INSUFFICIENT_DISK_SPACE")
        return {**payload, "center_frequency_hz": center, "sample_rate_sps": rate, "bandwidth_hz": bandwidth,
                "duration_seconds": duration, "sample_format": fmt, "gain_db": gain,
                "device_serial_masked": device.get("serial_masked"),
                "expected_size_bytes": expected, "purpose": payload.get("purpose", "interactive_experimental_capture")}

    def _execute(self, capture_id: str) -> None:
        job_dir = self.root / capture_id
        try:
            self._write_job(job_dir, "running")
            result = self.capture_service.capture(job_dir / "request.json", job_dir, lambda: capture_id in self._cancel)
            if result.get("cancelled"):
                self._write_job(job_dir, "cancelled", capture_complete=False, partial_artifact_preserved=True); return
            self._verify_completed(job_dir)
            self._write_job(job_dir, "completed", capture_complete=True)
        except TimeoutError as error:
            if self._recover_completed_capture(job_dir, f"{type(error).__name__}:{error}"):
                self._write_job(job_dir, "completed", capture_complete=True, completion_diagnostic="CAPTURE_TIMEOUT_AFTER_IQ_COMPLETE_RECOVERED")
            else:
                self._write_job(job_dir, "timed_out", error=str(error), failure_code="CAPTURE_TIMEOUT", capture_complete=False, partial_artifact_preserved=any(job_dir.glob("*.partial")))
        except Exception as error: self._write_job(job_dir, "failed", error=str(error), failure_code=str(error).split(":",1)[0], capture_complete=False, partial_artifact_preserved=any(job_dir.glob("*.partial")))
        finally:
            with self._lock:
                if self._active == capture_id: self._active = None

    def _verify_completed(self, job_dir: Path) -> None:
        capture_id = job_dir.name
        data, meta, manifest = job_dir / f"{capture_id}.sigmf-data", job_dir / f"{capture_id}.sigmf-meta", job_dir / "capture_manifest.json"
        if not data.is_file() or not meta.is_file() or not manifest.is_file(): raise ValueError("INCOMPLETE_CAPTURE_ARTIFACTS")
        metadata, record = json.loads(meta.read_text(encoding="utf-8")), json.loads(manifest.read_text(encoding="utf-8"))
        validate_sigmf(metadata)
        if sha256_file(data) != record.get("data_sha256"): raise ValueError("CAPTURE_DATA_HASH_MISMATCH")
        if sha256_file(meta) != record.get("metadata_sha256"): raise ValueError("CAPTURE_METADATA_HASH_MISMATCH")

    def _recover_completed_capture(self, job_dir: Path, diagnostic: str) -> bool:
        capture_id = job_dir.name
        request_path = job_dir / "request.json"
        data, meta, manifest_path = job_dir / f"{capture_id}.sigmf-data", job_dir / f"{capture_id}.sigmf-meta", job_dir / "capture_manifest.json"
        if not request_path.is_file() or not data.is_file() or not meta.is_file(): return False
        request = json.loads(request_path.read_text(encoding="utf-8"))
        fmt = request.get("sample_format")
        if fmt not in FORMATS: return False
        expected_size = int(request.get("expected_size_bytes") or 0)
        if expected_size <= 0:
            expected_size = int(float(request["sample_rate_sps"]) * float(request["duration_seconds"]) * FORMATS[fmt])
        if data.stat().st_size != expected_size: return False
        metadata = json.loads(meta.read_text(encoding="utf-8"))
        validate_sigmf(metadata)
        if manifest_path.is_file():
            self._verify_completed(job_dir)
            return True
        data_hash, meta_hash = sha256_file(data), sha256_file(meta)
        samples = expected_size // FORMATS[fmt]
        live_path = job_dir / "live.json"
        live = json.loads(live_path.read_text(encoding="utf-8")) if live_path.is_file() else {}
        started_at = ((metadata.get("captures") or [{}])[0].get("core:datetime") or request.get("created_at_utc") or utc_now())
        manifest = {
            "schema_version": "ble-sdr-capture-manifest-v1", "capture_id": capture_id,
            "created_at_utc": started_at, "device_driver": request.get("device_args", {}).get("driver", "unknown"),
            "device_serial": request.get("device_args", {}).get("serial"), "device_serial_masked": request.get("device_serial_masked"),
            "hardware": metadata.get("global", {}).get("core:hw"), "uhd_version": None,
            "capture_software_version": "ble-sdr-capture-v2", "center_frequency_hz": request["center_frequency_hz"],
            "ble_channel": request.get("ble_channel"), "sample_rate_sps": request["sample_rate_sps"],
            "bandwidth_hz": request["bandwidth_hz"], "sample_format": fmt,
            "gain_configuration": {"mode": request.get("gain_mode"), "gain_db": request.get("gain_db")},
            "antenna": request.get("antenna"), "requested_duration_seconds": request["duration_seconds"],
            "actual_samples": samples, "actual_duration_seconds": samples / request["sample_rate_sps"],
            "expected_size_bytes": expected_size, "actual_size_bytes": data.stat().st_size,
            "dropped_samples": None, "overflow_count": live.get("stream_overflows"),
            "input_discontinuities": live.get("input_discontinuities"),
            "data_path": data.name, "metadata_path": meta.name, "data_sha256": data_hash, "metadata_sha256": meta_hash,
            "capture_complete": True, "scientific_corpus_membership": "none", "eligible_for_holdout": False,
            "purpose": request.get("purpose", "interactive_experimental_capture"),
            "controlled_transmitter_state": request.get("controlled_transmitter_state", "unknown"),
            "operator_confirmed": bool(request.get("operator_confirmed", False)),
            "confirmation_method": request.get("confirmation_method"), "capture_role": request.get("capture_role"),
            "analysis_status": "postprocessing_timeout_recovered", "iq_recovery_validated": True,
            "ota_validated": False, "recovery_diagnostic": diagnostic,
        }
        atomic_json(manifest_path, manifest)
        (job_dir / "capture.sha256").write_text(f"{data_hash}  {data.name}\n{meta_hash}  {meta.name}\n", encoding="ascii")
        return True

    def _write_job(self, job_dir: Path, state: str, **fields: Any) -> None:
        with self._lock:
            previous = {}
            path = job_dir / "job.json"
            if path.exists(): previous = json.loads(path.read_text(encoding="utf-8"))
            next_job = {**previous, **fields, "capture_id": job_dir.name, "state": state, "updated_at_utc": utc_now()}
            if state == "completed":
                for key in ("error", "failure_code", "partial_artifact_preserved"):
                    next_job.pop(key, None)
            atomic_json(path, next_job)

    def get(self, capture_id: str) -> dict[str, Any]:
        return json.loads((self._job_dir(capture_id) / "job.json").read_text(encoding="utf-8"))

    def cancel(self, capture_id: str) -> dict[str, Any]:
        job = self.get(capture_id)
        if job["state"] not in TERMINAL: self._cancel.add(capture_id); self._write_job(self._job_dir(capture_id), "cancel_requested")
        return self.get(capture_id)

    def list_captures(self) -> list[dict[str, Any]]:
        records = []
        for manifest in self.root.glob("BLE-IQ-*/capture_manifest.json"):
            try:
                value = json.loads(manifest.read_text(encoding="utf-8"))
                if value.get("capture_complete") is True: records.append(value)
            except Exception: continue
        return sorted(records, key=lambda item: item.get("created_at_utc", ""), reverse=True)

    def metadata(self, capture_id: str) -> dict[str, Any]:
        root = self._job_dir(capture_id); return json.loads((root / "capture_manifest.json").read_text(encoding="utf-8"))

    def live_frame(self, capture_id: str) -> dict[str, Any]:
        path = self._job_dir(capture_id) / "live.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"available": False}

    def verify(self, capture_id: str) -> dict[str, Any]:
        root = self._job_dir(capture_id); record = self.metadata(capture_id)
        data, meta = root / record["data_path"], root / record["metadata_path"]
        return {"data_valid": sha256_file(data) == record["data_sha256"],
                "metadata_valid": sha256_file(meta) == record["metadata_sha256"]}

    def data_path(self, capture_id: str) -> Path:
        root = self._job_dir(capture_id); return root / self.metadata(capture_id)["data_path"]

    def meta_path(self, capture_id: str) -> Path:
        root = self._job_dir(capture_id); return root / self.metadata(capture_id)["metadata_path"]

    def _job_dir(self, capture_id: str) -> Path:
        if not capture_id.startswith("BLE-IQ-") or any(x in capture_id for x in ("/", "\\", "..")): raise ValueError("INVALID_CAPTURE_ID")
        path = (self.root / capture_id).resolve()
        if path.parent != self.root.resolve() or path.is_symlink(): raise ValueError("INVALID_CAPTURE_PATH")
        if not path.is_dir(): raise FileNotFoundError(capture_id)
        return path
