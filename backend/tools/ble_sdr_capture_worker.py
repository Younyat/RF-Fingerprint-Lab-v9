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
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True); handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
    # On Windows a browser/API reader can briefly hold live.json without
    # delete sharing. Retry the atomic swap instead of aborting the RF stream.
    for attempt in range(40):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == 39:
                raise
            time.sleep(0.01)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()


def write_jsonl(path: Path, rows) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows: handle.write(json.dumps(row, sort_keys=True) + "\n")


def detect_bursts(data_path: Path, sample_format: str, sample_rate: float, output: Path) -> list[dict]:
    dtype = {"cf32_le": "<c8", "ci16_le": "<i2", "ci8": "i1"}[sample_format]
    raw = np.memmap(data_path, dtype=dtype, mode="r")
    if sample_format == "cf32_le": values = raw
    else:
        scale = 32768.0 if sample_format == "ci16_le" else 128.0
        values = (raw[0::2].astype(np.float32) + 1j * raw[1::2].astype(np.float32)) / scale
    block = max(64, int(sample_rate / 100_000))
    count = len(values) // block
    if count < 4: return []
    power = np.mean(np.abs(np.asarray(values[:count * block]).reshape(count, block)) ** 2, axis=1)
    noise = float(np.median(power)); mad = float(np.median(np.abs(power - noise)))
    threshold = max(noise * 4.0, noise + 8.0 * mad, 1e-12)
    active = np.flatnonzero(power > threshold)
    groups = np.split(active, np.where(np.diff(active) > 2)[0] + 1) if active.size else []
    segment_dir = output / "iq_bursts"; segment_dir.mkdir(exist_ok=True)
    bursts = []
    bytes_per_sample = {"cf32_le": 8, "ci16_le": 4, "ci8": 2}[sample_format]
    with data_path.open("rb") as source:
        for index, group in enumerate(groups, 1):
            if not len(group): continue
            start = max(0, (int(group[0]) - 2) * block); end = min(len(values), (int(group[-1]) + 3) * block)
            source.seek(start * bytes_per_sample); payload = source.read((end - start) * bytes_per_sample)
            segment = segment_dir / f"burst-{index:06d}.cf32" if sample_format == "cf32_le" else segment_dir / f"burst-{index:06d}.iq"
            segment.write_bytes(payload)
            bursts.append({"burst_id": f"burst-{index:06d}", "sample_start": start, "sample_end": end,
                           "sample_count": end-start, "power_dbfs": float(10*np.log10(max(float(np.max(power[group])), 1e-12))),
                           "noise_power_dbfs": float(10*np.log10(max(noise, 1e-12))), "threshold_dbfs": float(10*np.log10(threshold)),
                           "iq_segment_path": str(segment.relative_to(output)), "iq_segment_sha256": sha256(segment),
                           "classification": "energy_burst_candidate", "ble_packet_confirmed": False})
    return bursts


def ranges(values):
    result = []
    for value in values:
        minimum = float(value.minimum()); maximum = float(value.maximum())
        result.append({"minimum": minimum, "maximum": maximum})
    return result


def uhd_version() -> str | None:
    try:
        result = subprocess.run(["uhd_config_info", "--version"], capture_output=True, text=True, timeout=10, check=True)
        return result.stdout.strip().splitlines()[-1] or None
    except Exception:
        return None


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
                "clock_sources": list(device.listClockSources()),
                "time_sources": list(device.listTimeSources()),
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
    matches = list(SoapySDR.Device.enumerate(request["device_args"]))
    if not matches:
        raise RuntimeError("SDR_DEVICE_NOT_FOUND_DURING_CAPTURE")
    device = SoapySDR.Device(matches[0]); stream = None
    received = overflows = discontinuities = telemetry_publish_failures = chunks = 0; started_at = utc_now()
    try:
        device.setSampleRate(SoapySDR.SOAPY_SDR_RX, 0, request["sample_rate_sps"])
        device.setFrequency(SoapySDR.SOAPY_SDR_RX, 0, request["center_frequency_hz"])
        device.setBandwidth(SoapySDR.SOAPY_SDR_RX, 0, request["bandwidth_hz"])
        if request.get("antenna"): device.setAntenna(SoapySDR.SOAPY_SDR_RX, 0, request["antenna"])
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
                handle.write(payload); received += samples; chunks += 1
                if chunks % 5 == 0 or received == target_samples:
                    try:
                        atomic_json(output / "live.json", live_metrics(complex_view(buffer, fmt, samples), request, received, handle.tell(), overflows, discontinuities))
                    except PermissionError:
                        # Telemetry is best-effort and must never terminate the
                        # authoritative IQ recording when Windows has a reader open.
                        telemetry_publish_failures += 1
            handle.flush(); os.fsync(handle.fileno())
        expected = received * {"ci8": 2, "ci16_le": 4, "cf32_le": 8}[fmt]
        if partial.stat().st_size != expected: raise RuntimeError("CAPTURE_SIZE_MISMATCH")
        os.replace(partial, final)
        hw = str(device.getHardwareKey()); hw_info = {str(k): str(v) for k, v in dict(device.getHardwareInfo()).items()}
        metadata = {"global": {"core:version": "1.2.6", "core:datatype": fmt, "core:sample_rate": request["sample_rate_sps"],
                    "core:hw": hw, "core:recorder": "RF-Fingerprint-Lab BLE Capture", "core:description": request.get("description", "Experimental BLE-channel IQ capture")},
                    "captures": [{"core:sample_start": 0, "core:frequency": request["center_frequency_hz"], "core:datetime": started_at}], "annotations": []}
        atomic_json(meta_path, metadata)
        bursts = detect_bursts(final, fmt, request["sample_rate_sps"], output)
        write_jsonl(output / "burst_candidates.jsonl", bursts)
        receiver_events = [{"event": "capture_started", "timestamp_utc": started_at, "sample_index": 0},
                           {"event": "capture_finished", "timestamp_utc": utc_now(), "sample_index": received,
                            "overflow_count": overflows, "discontinuity_count": discontinuities}]
        write_jsonl(output / "receiver_events.jsonl", receiver_events)
        quality = {"schema_version": "ble-sdr-quality-v1", "capture_id": capture_id,
                   "capture_complete": True, "overflow_count": overflows, "discontinuity_count": discontinuities,
                   "burst_candidate_count": len(bursts), "silent_sample_loss_detected": discontinuities > 0,
                   "fingerprinting_eligible": discontinuities == 0, "limitations": ["Energy bursts are candidates, not CRC-valid BLE packets."]}
        atomic_json(output / "quality_report.json", quality)
        manifest = {"schema_version": "ble-sdr-capture-manifest-v1", "capture_id": capture_id, "created_at_utc": started_at,
                    "device_driver": request["device_args"].get("driver", "unknown"),
                    "device_serial": hw_info.get("serial") or request["device_args"].get("serial"),
                    "device_serial_masked": request.get("device_serial_masked"), "hardware": hw,
                    "uhd_version": hw_info.get("uhd_version") or hw_info.get("version") or uhd_version(), "capture_software_version": "ble-sdr-capture-v2",
                    "center_frequency_hz": request["center_frequency_hz"], "ble_channel": request.get("ble_channel"),
                    "sample_rate_sps": request["sample_rate_sps"], "bandwidth_hz": request["bandwidth_hz"], "sample_format": fmt,
                    "gain_configuration": {"mode": request.get("gain_mode"), "gain_db": request.get("gain_db")},
                    "antenna": request.get("antenna"),
                    "requested_duration_seconds": request["duration_seconds"], "actual_samples": received,
                    "actual_duration_seconds": received/request["sample_rate_sps"], "expected_size_bytes": request["expected_size_bytes"],
                    "actual_size_bytes": final.stat().st_size, "dropped_samples": None, "overflow_count": overflows,
                    "input_discontinuities": discontinuities, "telemetry_publish_failures": telemetry_publish_failures,
                    "data_path": final.name, "metadata_path": meta_path.name,
                    "data_sha256": sha256(final), "metadata_sha256": sha256(meta_path), "capture_complete": True,
                    "scientific_corpus_membership": "none", "eligible_for_holdout": False, "purpose": request["purpose"],
                    "controlled_transmitter_state": request.get("controlled_transmitter_state", "unknown"),
                    "operator_confirmed": bool(request.get("operator_confirmed", False)),
                    "confirmation_method": request.get("confirmation_method"),
                    "capture_role": request.get("capture_role"),
                    "analysis_status": "not_requested", "iq_recovery_validated": False, "ota_validated": False}
        atomic_json(output / "capture_manifest.json", manifest)
        (output / "capture.sha256").write_text(f"{manifest['data_sha256']}  {final.name}\n{manifest['metadata_sha256']}  {meta_path.name}\n", encoding="ascii")
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
