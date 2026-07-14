"""Real SoapySDR probe/capture worker for BLE Lab.

This process never synthesizes IQ. Test fakes live in backend tests and do not
invoke this entry point.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True); handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
    os.replace(temporary, path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()


def ranges(values):
    result = []
    for value in values:
        minimum = float(value.minimum()); maximum = float(value.maximum())
        result.append({"minimum": minimum, "maximum": maximum})
    return result


def probe() -> int:
    import SoapySDR
    devices = []
    for args in SoapySDR.Device.enumerate():
        private = {str(k): str(v) for k, v in dict(args).items()}
        device = None
        try:
            device = SoapySDR.Device(args)
            info = device.getHardwareInfo()
            driver = str(private.get("driver") or device.getDriverKey())
            devices.append({
                "device_args": private,
                "driver": driver,
                "label": str(private.get("label") or info.get("hardware") or device.getHardwareKey() or driver),
                "serial": str(private.get("serial") or info.get("serial") or ""),
                "rx_channels": int(device.getNumChannels(SoapySDR.SOAPY_SDR_RX)),
                "frequency_ranges_hz": ranges(device.getFrequencyRange(SoapySDR.SOAPY_SDR_RX, 0)),
                "sample_rate_ranges_sps": ranges(device.getSampleRateRange(SoapySDR.SOAPY_SDR_RX, 0)),
                "bandwidth_ranges_hz": ranges(device.getBandwidthRange(SoapySDR.SOAPY_SDR_RX, 0)),
                "gain_elements": list(device.listGains(SoapySDR.SOAPY_SDR_RX, 0)),
                "antenna_options": list(device.listAntennas(SoapySDR.SOAPY_SDR_RX, 0)),
                "stream_formats": list(device.getStreamFormats(SoapySDR.SOAPY_SDR_RX, 0)),
            })
        except Exception:
            continue
        finally:
            if device is not None:
                try: device = None
                except Exception: pass
    runtime = {"sdr_runtime":"radioconda-or-configured-runtime",
               "soapysdr_library_version":getattr(SoapySDR,"getLibVersion",lambda:"unknown")(),
               "soapysdr_api_version":getattr(SoapySDR,"getAPIVersion",lambda:"unknown")(),
               "soapysdr_abi_version":getattr(SoapySDR,"getABIVersion",lambda:"unknown")(),
               "device_probe_succeeded":bool(devices)}
    print(json.dumps({"devices": devices,"runtime":runtime}, separators=(",", ":")))
    return 0


def output_buffer(sample_format: str, count: int):
    if sample_format == "ci8": return np.empty(count * 2, dtype=np.int8), "CS8"
    if sample_format == "ci16_le": return np.empty(count * 2, dtype="<i2"), "CS16"
    if sample_format == "cf32_le": return np.empty(count, dtype="<c8"), "CF32"
    raise ValueError("UNSUPPORTED_SAMPLE_FORMAT")


def complex_view(buffer, sample_format: str, samples: int):
    if sample_format == "cf32_le": return buffer[:samples].astype(np.complex64, copy=False)
    raw = buffer[:samples * 2].reshape(-1, 2).astype(np.float32)
    scale = 128.0 if sample_format == "ci8" else 32768.0
    return (raw[:, 0] + 1j * raw[:, 1]) / scale


def live_metrics(values, request, received, written, overflows, discontinuities):
    if len(values) == 0: return {"available": False}
    subset = values[-min(len(values), 8192):]
    nfft = min(2048, len(subset)); windowed = subset[-nfft:] * np.hanning(nfft)
    spectrum = 20 * np.log10(np.maximum(np.abs(np.fft.fftshift(np.fft.fft(windowed))) / max(1, nfft), 1e-12))
    frequencies = np.linspace(request["center_frequency_hz"] - request["sample_rate_sps"] / 2,
                              request["center_frequency_hz"] + request["sample_rate_sps"] / 2, nfft, endpoint=False)
    stride = max(1, nfft // 256)
    power = np.abs(subset) ** 2
    return {"available": True, "timestamp_utc": utc_now(), "samples_received": received, "bytes_written": written,
            "stream_overflows": overflows, "input_discontinuities": discontinuities,
            "average_power_dbfs": float(10 * np.log10(max(float(np.mean(power)), 1e-12))),
            "peak_power_dbfs": float(20 * np.log10(max(float(np.max(np.abs(subset))), 1e-12))),
            "clipping_percentage": float(100 * np.mean(np.abs(subset) >= 0.999)),
            "frequencies_hz": frequencies[::stride].tolist(), "spectrum_dbfs": spectrum[::stride].tolist(),
            "i_preview": subset.real[::max(1, len(subset)//512)].tolist(),
            "q_preview": subset.imag[::max(1, len(subset)//512)].tolist()}


def capture(request_path: Path, output: Path) -> int:
    import SoapySDR
    request = json.loads(request_path.read_text(encoding="utf-8")); output.mkdir(parents=True, exist_ok=True)
    capture_id, fmt = request["capture_id"], request["sample_format"]
    partial = output / f"{capture_id}.partial"; final = output / f"{capture_id}.sigmf-data"
    meta_path = output / f"{capture_id}.sigmf-meta"
    target_samples = int(request["sample_rate_sps"] * request["duration_seconds"])
    device = SoapySDR.Device(request["device_args"]); stream = None
    received = overflows = discontinuities = 0; started_at = utc_now()
    try:
        device.setSampleRate(SoapySDR.SOAPY_SDR_RX, 0, request["sample_rate_sps"])
        device.setFrequency(SoapySDR.SOAPY_SDR_RX, 0, request["center_frequency_hz"])
        device.setBandwidth(SoapySDR.SOAPY_SDR_RX, 0, request["bandwidth_hz"])
        if request.get("gain_mode") == "automatic": device.setGainMode(SoapySDR.SOAPY_SDR_RX, 0, True)
        else: device.setGainMode(SoapySDR.SOAPY_SDR_RX, 0, False); device.setGain(SoapySDR.SOAPY_SDR_RX, 0, request["gain_db"])
        buffer, wire_format = output_buffer(fmt, min(262144, max(16384, int(request["sample_rate_sps"] // 20))))
        stream = device.setupStream(SoapySDR.SOAPY_SDR_RX, wire_format, [0]); device.activateStream(stream)
        with partial.open("wb") as handle:
            while received < target_samples:
                wanted = min(len(buffer) if fmt == "cf32_le" else len(buffer)//2, target_samples - received)
                result = device.readStream(stream, [buffer], wanted, timeoutUs=1_000_000)
                if result.ret == SoapySDR.SOAPY_SDR_OVERFLOW: overflows += 1; discontinuities += 1; continue
                if result.ret <= 0: raise RuntimeError(f"SDR_STREAM_READ_ERROR:{result.ret}")
                samples = int(result.ret); payload = buffer[:samples if fmt == "cf32_le" else samples*2].tobytes(order="C")
                handle.write(payload); received += samples
                atomic_json(output / "live.json", live_metrics(complex_view(buffer, fmt, samples), request, received, handle.tell(), overflows, discontinuities))
            handle.flush(); os.fsync(handle.fileno())
        expected = received * {"ci8": 2, "ci16_le": 4, "cf32_le": 8}[fmt]
        if partial.stat().st_size != expected: raise RuntimeError("CAPTURE_SIZE_MISMATCH")
        os.replace(partial, final)
        hw = str(device.getHardwareKey())
        metadata = {"global": {"core:version": "1.2.6", "core:datatype": fmt, "core:sample_rate": request["sample_rate_sps"],
                    "core:hw": hw, "core:recorder": "RF-Fingerprint-Lab BLE Capture", "core:description": request.get("description", "Experimental BLE-channel IQ capture")},
                    "captures": [{"core:sample_start": 0, "core:frequency": request["center_frequency_hz"], "core:datetime": started_at}], "annotations": []}
        atomic_json(meta_path, metadata)
        manifest = {"schema_version": "1.0", "capture_id": capture_id, "created_at_utc": started_at,
                    "device_driver": request["device_args"].get("driver", "unknown"), "device_serial_masked": None,
                    "center_frequency_hz": request["center_frequency_hz"], "ble_channel": request.get("ble_channel"),
                    "sample_rate_sps": request["sample_rate_sps"], "bandwidth_hz": request["bandwidth_hz"], "sample_format": fmt,
                    "gain_configuration": {"mode": request.get("gain_mode"), "gain_db": request.get("gain_db")},
                    "requested_duration_seconds": request["duration_seconds"], "actual_samples": received,
                    "actual_duration_seconds": received/request["sample_rate_sps"], "expected_size_bytes": request["expected_size_bytes"],
                    "actual_size_bytes": final.stat().st_size, "dropped_samples": None, "overflow_count": overflows,
                    "input_discontinuities": discontinuities, "data_path": final.name, "metadata_path": meta_path.name,
                    "data_sha256": sha256(final), "metadata_sha256": sha256(meta_path), "capture_complete": True,
                    "scientific_corpus_membership": "none", "eligible_for_holdout": False, "purpose": request["purpose"],
                    "analysis_status": "not_requested", "iq_recovery_validated": False, "ota_validated": False}
        atomic_json(output / "capture_manifest.json", manifest)
        return 0
    finally:
        if stream is not None:
            try: device.deactivateStream(stream); device.closeStream(stream)
            except Exception: pass


def main() -> int:
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("devices")
    capture_parser = sub.add_parser("capture"); capture_parser.add_argument("--request", type=Path, required=True); capture_parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try: return probe() if args.action == "devices" else capture(args.request, args.output_dir)
    except Exception as error: print(f"{type(error).__name__}:{error}", file=sys.stderr); return 2


if __name__ == "__main__": raise SystemExit(main())
