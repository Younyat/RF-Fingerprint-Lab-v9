"""Per-model-family representations, all built from the SAME base-preprocessed
evidence window (design correction #10): raw I/Q for CNN1D, a numeric
spectrogram for CNN2D, and a real hand-crafted feature vector for the
classical baselines. None of these silently invents samples -- padding is
zero-padding, explicit and documented, never interpolation presented as data.
"""
from __future__ import annotations

import numpy as np
from scipy import signal as scipy_signal
from scipy import stats as scipy_stats

from .base_preprocessing import estimate_cfo_hz


def raw_iq_representation(window: np.ndarray, target_length: int) -> np.ndarray:
    """[2, target_length]: row 0 = I, row 1 = Q. Truncated or zero-padded to
    a fixed length so a CNN1D can batch examples of different natural
    duration."""
    trimmed = window[:target_length]
    pad = target_length - len(trimmed)
    if pad > 0:
        trimmed = np.concatenate([trimmed, np.zeros(pad, dtype=trimmed.dtype)])
    return np.stack([trimmed.real.astype(np.float32), trimmed.imag.astype(np.float32)], axis=0)


def spectrogram_representation(window: np.ndarray, sample_rate_sps: float, n_fft: int = 64, hop_length: int = 16, target_frames: int = 32) -> np.ndarray:
    """[1, n_fft//2+1, target_frames] magnitude spectrogram in dB, computed
    with scipy's STFT (never a pre-rendered PNG -- always the numeric matrix
    the design requires for CNN2D input)."""
    if len(window) < n_fft:
        window = np.concatenate([window, np.zeros(n_fft - len(window), dtype=window.dtype)])
    _, _, stft_matrix = scipy_signal.stft(window, fs=sample_rate_sps, nperseg=n_fft, noverlap=n_fft - hop_length, return_onesided=False)
    magnitude_db = 20 * np.log10(np.abs(stft_matrix) + 1e-12).astype(np.float32)
    frames = magnitude_db.shape[1]
    if frames < target_frames:
        magnitude_db = np.concatenate([magnitude_db, np.full((magnitude_db.shape[0], target_frames - frames), magnitude_db.min(), dtype=np.float32)], axis=1)
    else:
        magnitude_db = magnitude_db[:, :target_frames]
    return magnitude_db[np.newaxis, :, :]


FEATURE_NAMES = [
    "mean_power_dbfs", "std_power_db", "mean_abs_amplitude", "std_abs_amplitude",
    "spectral_centroid_hz", "spectral_bandwidth_hz", "cfo_estimate_hz", "papr_db",
    "amplitude_kurtosis", "amplitude_skewness",
]


def feature_vector_representation(window: np.ndarray, sample_rate_sps: float, n_fft: int = 128) -> np.ndarray:
    """A real, hand-crafted feature vector -- not a placeholder. Every value
    is computed from the actual I/Q samples, matching FEATURE_NAMES order."""
    amplitude = np.abs(window)
    power = amplitude ** 2
    mean_power = float(np.mean(power)) if len(power) else 0.0
    mean_power_dbfs = 10 * np.log10(mean_power + 1e-12)
    std_power_db = float(np.std(10 * np.log10(power + 1e-12))) if len(power) else 0.0
    mean_abs_amplitude = float(np.mean(amplitude)) if len(amplitude) else 0.0
    std_abs_amplitude = float(np.std(amplitude)) if len(amplitude) else 0.0

    if len(window) >= n_fft:
        freqs = np.fft.fftshift(np.fft.fftfreq(n_fft, d=1.0 / sample_rate_sps))
        spectrum = np.abs(np.fft.fftshift(np.fft.fft(window[:n_fft])))
    else:
        padded = np.concatenate([window, np.zeros(max(0, n_fft - len(window)), dtype=window.dtype)]) if len(window) else np.zeros(n_fft, dtype=np.complex64)
        freqs = np.fft.fftshift(np.fft.fftfreq(n_fft, d=1.0 / sample_rate_sps))
        spectrum = np.abs(np.fft.fftshift(np.fft.fft(padded)))
    spectrum_sum = float(np.sum(spectrum)) or 1.0
    spectral_centroid_hz = float(np.sum(freqs * spectrum) / spectrum_sum)
    spectral_bandwidth_hz = float(np.sqrt(np.sum(((freqs - spectral_centroid_hz) ** 2) * spectrum) / spectrum_sum))

    cfo_estimate_hz = estimate_cfo_hz(window, sample_rate_sps)
    peak_power = float(np.max(power)) if len(power) else 0.0
    papr_db = 10 * np.log10((peak_power + 1e-12) / (mean_power + 1e-12))
    amplitude_kurtosis = float(scipy_stats.kurtosis(amplitude)) if len(amplitude) > 3 else 0.0
    amplitude_skewness = float(scipy_stats.skew(amplitude)) if len(amplitude) > 2 else 0.0

    return np.array([
        mean_power_dbfs, std_power_db, mean_abs_amplitude, std_abs_amplitude,
        spectral_centroid_hz, spectral_bandwidth_hz, cfo_estimate_hz, papr_db,
        amplitude_kurtosis, amplitude_skewness,
    ], dtype=np.float64)
