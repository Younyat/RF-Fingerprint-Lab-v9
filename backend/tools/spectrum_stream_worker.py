#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
import threading
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

    def set_center_frequency(self, center_freq_hz: float) -> None:
        self.source.set_center_freq(float(center_freq_hz), 0)

    def set_sample_rate(self, sample_rate_hz: float) -> None:
        self.source.set_samp_rate(float(sample_rate_hz))

    def set_gain(self, gain_db: float) -> None:
        try:
            self.source.set_gain(float(gain_db), 0)
        except TypeError:
            self.source.set_gain(float(gain_db))


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


class RuntimeConfig:
    def __init__(
        self,
        center_freq_hz: float,
        sample_rate_hz: float,
        gain_db: float,
        fft_size: int,
        requested_rbw_hz: float,
        requested_vbw_hz: float,
    ) -> None:
        self._lock = threading.Lock()
        self.center_freq_hz = center_freq_hz
        self.sample_rate_hz = sample_rate_hz
        self.gain_db = gain_db
        self.fft_size = fft_size
        self.requested_rbw_hz = requested_rbw_hz
        self.requested_vbw_hz = requested_vbw_hz

    def snapshot(self) -> tuple[float, float, float, int, float, float]:
        with self._lock:
            return (
                self.center_freq_hz,
                self.sample_rate_hz,
                self.gain_db,
                self.fft_size,
                self.requested_rbw_hz,
                self.requested_vbw_hz,
            )

    def apply(self, update: dict) -> tuple[bool, str | None]:
        changed = False
        with self._lock:
            if "center_freq_hz" in update:
                value = float(update["center_freq_hz"])
                if value != self.center_freq_hz:
                    self.center_freq_hz = value
                    changed = True
            if "sample_rate_hz" in update:
                value = float(update["sample_rate_hz"])
                if value != self.sample_rate_hz:
                    self.sample_rate_hz = value
                    changed = True
            if "gain_db" in update:
                value = float(update["gain_db"])
                if value != self.gain_db:
                    self.gain_db = value
                    changed = True
            if "fft_size" in update:
                value = int(update["fft_size"])
                if value != self.fft_size:
                    self.fft_size = value
                    changed = True
            if "rbw_hz" in update:
                value = float(update["rbw_hz"])
                if value != self.requested_rbw_hz:
                    self.requested_rbw_hz = value
                    changed = True
            if "vbw_hz" in update:
                value = float(update["vbw_hz"])
                if value != self.requested_vbw_hz:
                    self.requested_vbw_hz = value
                    changed = True
        return changed, None


def stdin_control_loop(config: RuntimeConfig) -> None:
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue

        if message.get("command") != "update":
            continue

        _, error = config.apply(message)
        if error:
            print(json.dumps({"source": "real_sdr_error", "error": error}), flush=True)


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
    runtime = RuntimeConfig(
        center_freq_hz=center_freq_hz,
        sample_rate_hz=sample_rate_hz,
        gain_db=float(args.gain),
        fft_size=fft_size,
        requested_rbw_hz=float(args.rbw),
        requested_vbw_hz=float(args.vbw),
    )

    tb = SpectrumStream(
        center_freq_hz=center_freq_hz,
        sample_rate_hz=sample_rate_hz,
        gain_db=float(args.gain),
        antenna=args.antenna,
        device_addr=args.device_addr,
    )

    tb.start()
    threading.Thread(target=stdin_control_loop, args=(runtime,), daemon=True).start()
    try:
        while True:
            time.sleep(interval)
            (
                center_freq_hz,
                sample_rate_hz,
                gain_db,
                fft_size,
                requested_rbw_hz,
                requested_vbw_hz,
            ) = runtime.snapshot()

            tb.set_center_frequency(center_freq_hz)
            tb.set_sample_rate(sample_rate_hz)
            tb.set_gain(gain_db)

            fft_size = effective_fft_size(
                sample_rate_hz=sample_rate_hz,
                requested_rbw_hz=requested_rbw_hz,
                fallback_fft_size=fft_size,
                min_fft_size=int(args.min_fft_size),
                max_fft_size=int(args.max_fft_size),
            )
            effective_rbw_hz = sample_rate_hz * 1.5 / float(fft_size)
            samples = np.asarray(tb.sink.data(), dtype=np.complex64)
            if samples.size < fft_size:
                continue

            frame, previous_video_power = build_frame(
                samples,
                center_freq_hz,
                sample_rate_hz,
                fft_size,
                requested_rbw_hz,
                effective_rbw_hz,
                requested_vbw_hz,
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
