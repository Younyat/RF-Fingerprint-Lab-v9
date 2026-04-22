#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone

import numpy as np
from gnuradio import blocks
from gnuradio import gr
from gnuradio import uhd


def normalize_device_addr(device_addr: str) -> str:
    return str(device_addr).strip()


class SpectrumStream(gr.top_block):
    def __init__(
        self,
        center_freq_hz: float,
        sample_rate_hz: float,
        gain_db: float,
        antenna: str,
        device_addr: str,
    ):
        gr.top_block.__init__(self, "Spectrum Stream", catch_exceptions=True)
        self.source = uhd.usrp_source(
            normalize_device_addr(device_addr),
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

        self.sink = blocks.vector_sink_c()
        self.connect((self.source, 0), (self.sink, 0))


def next_power_of_two(value: int) -> int:
    return 1 << max(1, int(value - 1).bit_length())


def effective_fft_size(
    sample_rate_hz: float,
    requested_rbw_hz: float,
    fallback_fft_size: int,
    min_fft_size: int,
    max_fft_size: int,
) -> int:
    if requested_rbw_hz <= 0:
        return max(min_fft_size, min(fallback_fft_size, max_fft_size))
    hann_enbw_bins = 1.5
    target_size = math.ceil(sample_rate_hz * hann_enbw_bins / requested_rbw_hz)
    return max(min_fft_size, min(next_power_of_two(target_size), max_fft_size))


def smooth_video_bandwidth(
    levels_db: np.ndarray,
    previous_power: np.ndarray | None,
    vbw_hz: float,
    frame_interval_s: float,
) -> tuple[np.ndarray, np.ndarray]:
    current_power = np.power(10.0, levels_db / 10.0)
    if previous_power is None or previous_power.shape != current_power.shape or vbw_hz <= 0:
        return levels_db, current_power

    alpha = 1.0 - math.exp(-2.0 * math.pi * vbw_hz * frame_interval_s)
    alpha = min(max(alpha, 0.0), 1.0)
    smoothed_power = previous_power + alpha * (current_power - previous_power)
    smoothed_db = 10.0 * np.log10(smoothed_power + 1e-24)
    return smoothed_db, smoothed_power


def build_frame(
    samples: np.ndarray,
    center_freq_hz: float,
    sample_rate_hz: float,
    fft_size: int,
    requested_rbw_hz: float,
    effective_rbw_hz: float,
    requested_vbw_hz: float,
    frame_interval_s: float,
    previous_video_power: np.ndarray | None,
) -> tuple[dict, np.ndarray]:
    samples = samples[-fft_size:]
    window = np.hanning(fft_size).astype(np.float32)
    spectrum = np.fft.fftshift(np.fft.fft(samples * window, n=fft_size))
    magnitudes = np.abs(spectrum) / max(float(np.sum(window)), 1.0)
    levels_db = 20.0 * np.log10(magnitudes + 1e-12)
    levels_db, video_power = smooth_video_bandwidth(
        levels_db,
        previous_video_power,
        requested_vbw_hz,
        frame_interval_s,
    )
    freqs = center_freq_hz + np.fft.fftshift(np.fft.fftfreq(fft_size, d=1.0 / sample_rate_hz))
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "center_frequency_hz": center_freq_hz,
        "span_hz": sample_rate_hz,
        "start_frequency_hz": float(freqs[0]),
        "stop_frequency_hz": float(freqs[-1]),
        "sample_rate_hz": sample_rate_hz,
        "frequencies_hz": freqs.astype(float).tolist(),
        "levels_db": levels_db.astype(float).tolist(),
        "points": fft_size,
        "requested_rbw_hz": requested_rbw_hz,
        "effective_rbw_hz": effective_rbw_hz,
        "requested_vbw_hz": requested_vbw_hz,
        "effective_vbw_hz": min(requested_vbw_hz, 0.5 / frame_interval_s),
        "source": "uhd_gnuradio_live",
    }, video_power


def main() -> None:
    parser = argparse.ArgumentParser(description="Persistent UHD spectrum stream worker.")
    parser.add_argument("--freq", type=float, required=True, help="Center frequency in MHz")
    parser.add_argument("--sample-rate", type=float, default=2e6)
    parser.add_argument("--gain", type=float, default=20.0)
    parser.add_argument("--antenna", type=str, default="RX2")
    parser.add_argument("--device-addr", type=str, default="")
    parser.add_argument("--fft-size", type=int, default=4096)
    parser.add_argument("--min-fft-size", type=int, default=256)
    parser.add_argument("--max-fft-size", type=int, default=65536)
    parser.add_argument("--rbw", type=float, default=10_000.0)
    parser.add_argument("--vbw", type=float, default=3_000.0)
    parser.add_argument("--fps", type=float, default=5.0)
    args = parser.parse_args()

    center_freq_hz = float(args.freq) * 1e6
    sample_rate_hz = float(args.sample_rate)
    interval = 1.0 / max(float(args.fps), 0.1)
    fft_size = effective_fft_size(
        sample_rate_hz=sample_rate_hz,
        requested_rbw_hz=float(args.rbw),
        fallback_fft_size=int(args.fft_size),
        min_fft_size=int(args.min_fft_size),
        max_fft_size=int(args.max_fft_size),
    )
    effective_rbw_hz = sample_rate_hz * 1.5 / float(fft_size)
    previous_video_power: np.ndarray | None = None

    tb = SpectrumStream(
        center_freq_hz=center_freq_hz,
        sample_rate_hz=sample_rate_hz,
        gain_db=float(args.gain),
        antenna=args.antenna,
        device_addr=args.device_addr,
    )

    tb.start()
    try:
        while True:
            time.sleep(interval)
            samples = np.asarray(tb.sink.data(), dtype=np.complex64)
            if samples.size < fft_size:
                continue

            frame, previous_video_power = build_frame(
                samples,
                center_freq_hz,
                sample_rate_hz,
                fft_size,
                float(args.rbw),
                effective_rbw_hz,
                float(args.vbw),
                interval,
                previous_video_power,
            )
            print(json.dumps(frame), flush=True)

            reset = getattr(tb.sink, "reset", None)
            if callable(reset):
                reset()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(json.dumps({"source": "real_sdr_error", "error": str(exc)}), flush=True)
        raise
    finally:
        tb.stop()
        tb.wait()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"spectrum_stream_worker failed: {exc}", file=sys.stderr, flush=True)
        raise
