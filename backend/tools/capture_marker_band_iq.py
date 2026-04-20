#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from gnuradio import blocks
from gnuradio import gr
from gnuradio import uhd


def safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]+', "_", name)
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("._")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class FiniteMarkerBandCapture(gr.top_block):
    def __init__(
        self,
        center_freq_hz: float,
        iq_output_path: str,
        duration_s: float,
        sample_rate_hz: float,
        gain_db: float,
        antenna: str,
        device_addr: str,
    ):
        gr.top_block.__init__(self, "Finite Marker Band IQ Capture", catch_exceptions=True)
        sample_count = int(duration_s * sample_rate_hz)
        self.source = uhd.usrp_source(
            ",".join((device_addr, "")),
            uhd.stream_args(cpu_format="fc32", args="", channels=[0]),
        )
        self.source.set_samp_rate(float(sample_rate_hz))
        self.source.set_time_unknown_pps(uhd.time_spec(0))
        self.source.set_center_freq(float(center_freq_hz), 0)
        self.source.set_antenna(str(antenna), 0)
        try:
            self.source.set_gain(float(gain_db), 0)
        except TypeError:
            self.source.set_gain(float(gain_db))

        self.head = blocks.head(gr.sizeof_gr_complex, sample_count)
        self.sink = blocks.file_sink(gr.sizeof_gr_complex, iq_output_path, False)
        self.sink.set_unbuffered(False)
        self.connect((self.source, 0), (self.head, 0))
        self.connect((self.head, 0), (self.sink, 0))


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture marker-limited IQ from UHD for modulation analysis.")
    parser.add_argument("--capture-id", type=str, required=True)
    parser.add_argument("--start-hz", type=float, required=True)
    parser.add_argument("--stop-hz", type=float, required=True)
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--sample-rate", type=float, default=2e6)
    parser.add_argument("--gain", type=float, default=20.0)
    parser.add_argument("--antenna", type=str, default="RX2")
    parser.add_argument("--device-addr", type=str, default="")
    parser.add_argument("--output-dir", type=str, required=True)
    parser.add_argument("--base-name", type=str, default=None)
    parser.add_argument("--label", type=str, default="")
    parser.add_argument("--modulation-hint", type=str, default="unknown")
    parser.add_argument("--notes", type=str, default="")
    parser.add_argument("--settle-ms", type=int, default=300)
    args = parser.parse_args()

    if args.stop_hz <= args.start_hz:
        raise ValueError("stop-hz must be greater than start-hz")
    if args.duration <= 0:
        raise ValueError("duration must be greater than zero")

    bandwidth_hz = args.stop_hz - args.start_hz
    center_freq_hz = args.start_hz + bandwidth_hz / 2.0
    sample_rate_hz = float(args.sample_rate)

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    base_name = safe_filename(args.base_name or f"iq_{args.capture_id}_{center_freq_hz / 1e6:.6f}MHz")
    iq_path = output_dir / f"{base_name}.cfile"
    meta_path = output_dir / f"{base_name}.json"

    tb = FiniteMarkerBandCapture(
        center_freq_hz=center_freq_hz,
        iq_output_path=str(iq_path),
        duration_s=float(args.duration),
        sample_rate_hz=sample_rate_hz,
        gain_db=float(args.gain),
        antenna=args.antenna,
        device_addr=args.device_addr,
    )

    time.sleep(args.settle_ms / 1000.0)
    tb.start()
    tb.wait()
    tb.stop()

    sample_count = int(float(args.duration) * sample_rate_hz)
    metadata = {
        "id": args.capture_id,
        "generated_at_utc": utc_now_iso(),
        "capture_type": "marker_band_iq",
        "source_device": "USRP-B200 from Ettus Research",
        "driver": "uhd_gnuradio",
        "label": args.label,
        "modulation_hint": args.modulation_hint,
        "notes": args.notes,
        "start_frequency_hz": args.start_hz,
        "stop_frequency_hz": args.stop_hz,
        "center_frequency_hz": center_freq_hz,
        "bandwidth_hz": bandwidth_hz,
        "duration_seconds": args.duration,
        "sample_rate_hz": sample_rate_hz,
        "sample_count": sample_count,
        "gain_db": args.gain,
        "antenna": args.antenna,
        "device_addr": args.device_addr,
        "channel_index": 0,
        "iq_file": str(iq_path),
        "metadata_file": str(meta_path),
        "iq_format": "complex64_fc32_interleaved",
        "iq_dtype": "complex64",
        "byte_order": "native",
        "file_size_bytes": iq_path.stat().st_size,
        "sha256": sha256_file(iq_path),
        "replay_parameters": {
            "center_frequency_hz": center_freq_hz,
            "sample_rate_hz": sample_rate_hz,
            "gain_db": args.gain,
            "antenna": args.antenna,
            "iq_format": "complex64_fc32_interleaved",
        },
        "ai_dataset_fields": [
            "label",
            "modulation_hint",
            "center_frequency_hz",
            "bandwidth_hz",
            "sample_rate_hz",
            "duration_seconds",
            "iq_file",
            "sha256",
        ],
    }

    with meta_path.open("w", encoding="utf-8") as file:
        json.dump(metadata, file, indent=2, ensure_ascii=False)

    print(json.dumps(metadata), flush=True)


if __name__ == "__main__":
    main()
