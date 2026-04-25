import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

// Utility for combining Tailwind classes
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// Frequency formatting utilities
export function formatFrequency(hz: number | null | undefined): string {
  if (!Number.isFinite(hz)) {
    return 'n/a';
  }
  const safeHz = Number(hz);
  if (safeHz >= 1e9) {
    return `${(safeHz / 1e9).toFixed(2)} GHz`;
  } else if (safeHz >= 1e6) {
    return `${(safeHz / 1e6).toFixed(2)} MHz`;
  } else if (safeHz >= 1e3) {
    return `${(safeHz / 1e3).toFixed(2)} kHz`;
  } else {
    return `${safeHz.toFixed(0)} Hz`;
  }
}

export function parseFrequency(value: number, unit: 'Hz' | 'kHz' | 'MHz' | 'GHz'): number {
  const multipliers = {
    Hz: 1,
    kHz: 1000,
    MHz: 1000000,
    GHz: 1000000000,
  };
  return value * multipliers[unit];
}

// Power level formatting
export function formatPowerLevel(db: number | null | undefined): string {
  if (!Number.isFinite(db)) {
    return 'n/a';
  }
  const safeDb = Number(db);
  return `${safeDb >= 0 ? '+' : ''}${safeDb.toFixed(1)} dB`;
}

export interface BandQualityEstimate {
  peakLevelDb: number;
  peakFrequencyHz: number;
  noiseFloorDb: number;
  snrDb: number;
}

export function estimateBandQuality(
  frequencies: number[],
  levelsDb: number[],
  startFrequencyHz: number,
  stopFrequencyHz: number,
): BandQualityEstimate | null {
  if (
    frequencies.length === 0 ||
    levelsDb.length === 0 ||
    frequencies.length !== levelsDb.length ||
    !Number.isFinite(startFrequencyHz) ||
    !Number.isFinite(stopFrequencyHz) ||
    stopFrequencyHz <= startFrequencyHz
  ) {
    return null;
  }

  const inBandLevels: number[] = [];
  const inBandFrequencies: number[] = [];
  const outOfBandLevels: number[] = [];

  for (let index = 0; index < frequencies.length; index += 1) {
    const frequency = frequencies[index];
    const level = levelsDb[index];
    if (!Number.isFinite(frequency) || !Number.isFinite(level)) continue;
    if (frequency >= startFrequencyHz && frequency <= stopFrequencyHz) {
      inBandLevels.push(level);
      inBandFrequencies.push(frequency);
    } else {
      outOfBandLevels.push(level);
    }
  }

  if (inBandLevels.length === 0) return null;

  let peakIndex = 0;
  let peakLevelDb = -Infinity;
  inBandLevels.forEach((level, index) => {
    if (level > peakLevelDb) {
      peakLevelDb = level;
      peakIndex = index;
    }
  });

  const noiseCandidates = outOfBandLevels.length >= 8 ? outOfBandLevels : levelsDb.filter(Number.isFinite);
  if (noiseCandidates.length === 0) return null;
  const sortedNoise = [...noiseCandidates].sort((a, b) => a - b);
  const noiseIndex = Math.min(sortedNoise.length - 1, Math.max(0, Math.floor(sortedNoise.length * 0.2)));
  const noiseFloorDb = sortedNoise[noiseIndex];

  return {
    peakLevelDb,
    peakFrequencyHz: inBandFrequencies[peakIndex],
    noiseFloorDb,
    snrDb: peakLevelDb - noiseFloorDb,
  };
}

// Time formatting
export function formatDuration(seconds: number | null | undefined): string {
  if (!Number.isFinite(seconds)) {
    return 'n/a';
  }
  const safeSeconds = Number(seconds);
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const secs = Math.floor(safeSeconds % 60);

  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  } else {
    return `${minutes}:${secs.toString().padStart(2, '0')}`;
  }
}

// File size formatting
export function formatFileSize(bytes: number | null | undefined): string {
  if (!Number.isFinite(bytes) || (bytes ?? 0) < 0) {
    return 'n/a';
  }
  const safeBytes = Number(bytes);
  const units = ['B', 'KB', 'MB', 'GB'];
  let size = safeBytes;
  let unitIndex = 0;

  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex++;
  }

  return `${size.toFixed(1)} ${units[unitIndex]}`;
}

// Debounce utility
export function debounce<T extends (...args: any[]) => any>(
  func: T,
  wait: number
): (...args: Parameters<T>) => void {
  let timeout: ReturnType<typeof setTimeout>;
  return (...args: Parameters<T>) => {
    clearTimeout(timeout);
    timeout = setTimeout(() => func(...args), wait);
  };
}

// Throttle utility
export function throttle<T extends (...args: any[]) => any>(
  func: T,
  limit: number
): (...args: Parameters<T>) => void {
  let inThrottle: boolean;
  return (...args: Parameters<T>) => {
    if (!inThrottle) {
      func(...args);
      inThrottle = true;
      setTimeout(() => (inThrottle = false), limit);
    }
  };
}

// Generate unique ID
export function generateId(): string {
  return Math.random().toString(36).substr(2, 9);
}

// Clamp value between min and max
export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

// Linear interpolation
export function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

// Color utilities for spectrum visualization
export function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  h /= 360;
  s /= 100;
  l /= 100;

  const hue2rgb = (p: number, q: number, t: number) => {
    if (t < 0) t += 1;
    if (t > 1) t -= 1;
    if (t < 1/6) return p + (q - p) * 6 * t;
    if (t < 1/2) return q;
    if (t < 2/3) return p + (q - p) * (2/3 - t) * 6;
    return p;
  };

  let r, g, b;
  if (s === 0) {
    r = g = b = l;
  } else {
    const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
    const p = 2 * l - q;
    r = hue2rgb(p, q, h + 1/3);
    g = hue2rgb(p, q, h);
    b = hue2rgb(p, q, h - 1/3);
  }

  return [Math.round(r * 255), Math.round(g * 255), Math.round(b * 255)];
}

// Turbo colormap implementation
export function turboColormap(t: number): [number, number, number] {
  // Turbo colormap approximation
  const r = Math.max(0, Math.min(255,
    34.61 + t * (1172.33 - t * (10793.56 - t * (33300.12 - t * (38394.49 - t * 14825.05))))
  ));
  const g = Math.max(0, Math.min(255,
    23.31 + t * (557.33 + t * (1225.33 - t * (3574.96 - t * (1073.77 + t * 707.56))))
  ));
  const b = Math.max(0, Math.min(255,
    27.2 + t * (3211.1 - t * (15327.97 - t * (27814 - t * (22569.18 - t * 6838.66))))
  ));

  return [r, g, b];
}
