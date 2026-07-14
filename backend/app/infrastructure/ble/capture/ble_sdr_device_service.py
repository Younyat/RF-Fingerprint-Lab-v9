from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SdrProbeConfig:
    python_executable: Path
    tool_path: Path
    runtime_root: Path | None = None
    timeout_seconds: float = 15.0


class BleSdrDeviceService:
    def __init__(self, config: SdrProbeConfig) -> None:
        self.config = config
        self._private_args: dict[str, dict[str, str]] = {}
        self.last_diagnostics: dict[str, Any] = {}

    def _environment(self) -> dict[str, str]:
        environment = dict(os.environ)
        root = self.config.runtime_root
        if root:
            system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
            environment["PATH"] = os.pathsep.join(str(path) for path in (root / "Library" / "bin", root / "Scripts", root, system32))
            environment["SOAPY_SDR_PLUGIN_PATH"] = str(root / "Library" / "lib" / "SoapySDR" / "modules0.8")
        return environment

    def list_devices(self) -> dict[str, Any]:
        if not self.config.python_executable.is_file() or not self.config.tool_path.is_file():
            return self._unavailable("SDR_RUNTIME_UNAVAILABLE", "The configured SDR runtime is unavailable.")
        try:
            result = subprocess.run(
                [str(self.config.python_executable), str(self.config.tool_path), "devices"],
                capture_output=True, text=True, timeout=self.config.timeout_seconds, check=False, env=self._environment(),
            )
        except Exception:
            return self._unavailable("SDR_PROBE_FAILED", "The SDR probe could not be executed.")
        if result.returncode != 0:
            return self._unavailable("SDR_PROBE_FAILED", "The SDR probe did not complete successfully.")
        try:
            response = json.loads(result.stdout); raw_devices = response.get("devices", [])
            self.last_diagnostics = {"classification": "SOAPY_DEVICE_ENUMERATION_EMPTY" if not raw_devices else "OK",
                                     "runtime": response.get("runtime", {}), "stderr": result.stderr[-8192:]}
            if result.stderr: logging.getLogger(__name__).warning("SoapySDR probe diagnostics: %s", result.stderr[-8192:])
        except Exception:
            return self._unavailable("SDR_PROBE_INVALID_RESPONSE", "The SDR probe returned invalid data.")
        devices = []
        self._private_args.clear()
        for raw in raw_devices:
            args = {str(k): str(v) for k, v in raw.pop("device_args", {}).items()}
            identity = json.dumps(args, sort_keys=True, separators=(",", ":"))
            device_id = "sdr-" + hashlib.sha256(identity.encode()).hexdigest()[:16]
            # Enumeration metadata such as label/name/product is descriptive,
            # not a stable set of constructor arguments. UHD reliably reopens
            # the same physical receiver using its driver and serial.
            connection_args = {"driver": args["driver"]} if args.get("driver") else {}
            self._private_args[device_id] = connection_args or args
            raw["device_id"] = device_id
            raw["serial_masked"] = self._mask(raw.get("serial"))
            raw.pop("serial", None)
            raw["available"] = True
            devices.append(raw)
        if not devices:
            return self._unavailable("NO_COMPATIBLE_SDR", "No compatible SDR receiver was detected.")
        return {"available": True, "devices": devices}

    def private_args(self, device_id: str) -> dict[str, str]:
        if device_id not in self._private_args:
            self.list_devices()
        if device_id not in self._private_args:
            raise ValueError("UNKNOWN_SDR_DEVICE")
        return dict(self._private_args[device_id])

    @staticmethod
    def _mask(serial: Any) -> str | None:
        value = str(serial or "").strip()
        return None if not value else ("*" * max(0, len(value) - 4) + value[-4:])

    @staticmethod
    def _unavailable(code: str, message: str) -> dict[str, Any]:
        return {"available": False, "reason_code": code, "message": message, "devices": []}
