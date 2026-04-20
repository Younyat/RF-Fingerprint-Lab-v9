import { useEffect, useRef, useState } from 'react';
import { useAppStore, useDeviceStatus, useSpectrumData, useAnalyzerSettings } from '../../app/store/AppStore';
import { ApiService } from '../../app/services/ApiService';

const apiService = new ApiService();

export const useSpectrum = () => {
  const spectrumData = useSpectrumData();
  const settings = useAnalyzerSettings();
  const deviceStatus = useDeviceStatus();
  const setSpectrumData = useAppStore((state) => state.setSpectrumData);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const traceRef = useRef<number[] | null>(null);
  const lastTraceKeyRef = useRef('');

  const getTraceColor = () => {
    switch (settings.colorScheme) {
      case 'green':
        return '#22c55e';
      case 'amber':
        return '#f59e0b';
      case 'magenta':
        return '#d946ef';
      default:
        return '#3b82f6';
    }
  };

  const buildDisplayTrace = (levels: number[]) => {
    const adjusted = levels.map((level) => level + settings.noiseFloorOffset);
    const key = `${settings.centerFrequency}:${settings.span}:${settings.traceMode}:${settings.detectorMode}:${settings.averaging}`;
    if (lastTraceKeyRef.current !== key) {
      traceRef.current = null;
      lastTraceKeyRef.current = key;
    }

    if (!traceRef.current || traceRef.current.length !== adjusted.length || settings.traceMode === 'clear_write') {
      traceRef.current = adjusted;
      return adjusted;
    }

    const previous = traceRef.current;
    let next: number[];
    if (settings.traceMode === 'max_hold' || settings.detectorMode === 'max_hold' || settings.detectorMode === 'peak') {
      next = adjusted.map((level, index) => Math.max(previous[index] ?? level, level));
    } else if (settings.traceMode === 'min_hold' || settings.detectorMode === 'min_hold') {
      next = adjusted.map((level, index) => Math.min(previous[index] ?? level, level));
    } else {
      const alpha = settings.traceMode === 'video_average'
        ? 1 / Math.max(settings.averaging * 2, 2)
        : 1 / Math.max(settings.averaging, 1);
      next = adjusted.map((level, index) => {
        const oldLevel = previous[index] ?? level;
        return oldLevel * (1 - alpha) + level * alpha;
      });
    }

    traceRef.current = next;
    return next;
  };

  // Draw spectrum on canvas
  useEffect(() => {
    if (!canvasRef.current || !spectrumData) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const animationFrame = requestAnimationFrame(() => {
      const { width, height } = canvas;

      // Clear canvas
      ctx.clearRect(0, 0, width, height);

      // Set up coordinate system
      const padding = 40;
      const plotWidth = width - 2 * padding;
      const plotHeight = height - 2 * padding;

      ctx.fillStyle = '#020617';
      ctx.fillRect(0, 0, width, height);

      // Vertical grid lines (frequency)
      const freqRange = settings.span;
      const freqStart = settings.centerFrequency - freqRange / 2;

      for (let i = 0; i <= 50; i++) {
        const x = padding + (i / 50) * plotWidth;
        const isMajor = i % 5 === 0;
        const majorIndex = i / 5;
        ctx.beginPath();
        ctx.moveTo(x, padding);
        ctx.lineTo(x, height - padding);
        ctx.strokeStyle = isMajor ? '#334155' : '#1e293b';
        ctx.lineWidth = isMajor ? 1.2 : 0.6;
        ctx.stroke();

        if (isMajor) {
          const freq = freqStart + (majorIndex / 10) * freqRange;
          ctx.fillStyle = '#94a3b8';
          ctx.font = '12px sans-serif';
          ctx.textAlign = 'center';
          ctx.fillText(`${(freq / 1000000).toFixed(3)}M`, x, height - 10);
        }
      }

      // Horizontal grid lines (power)
      const powerRange = Math.max(settings.dbPerDiv, 1) * 10;
      const powerTop = settings.referenceLevel;
      const powerBottom = powerTop - powerRange;

      for (let i = 0; i <= 50; i++) {
        const y = padding + (i / 50) * plotHeight;
        const isMajor = i % 5 === 0;
        ctx.beginPath();
        ctx.moveTo(padding, y);
        ctx.lineTo(width - padding, y);
        ctx.strokeStyle = isMajor ? '#334155' : '#1e293b';
        ctx.lineWidth = isMajor ? 1.2 : 0.6;
        ctx.stroke();

        if (isMajor) {
          const power = powerTop - (i / 5) * settings.dbPerDiv;
          ctx.fillStyle = '#94a3b8';
          ctx.font = '12px sans-serif';
          ctx.textAlign = 'right';
          ctx.fillText(`${power.toFixed(0)}`, padding - 5, y + 4);
        }
      }

      // Draw spectrum trace
      if (spectrumData.powerLevels.length > 0) {
        const displayTrace = buildDisplayTrace(spectrumData.powerLevels);
        ctx.strokeStyle = getTraceColor();
        ctx.lineWidth = 2;
        ctx.beginPath();

        displayTrace.forEach((level, index) => {
          const x = padding + (index / Math.max(displayTrace.length - 1, 1)) * plotWidth;
          const normalizedLevel = (level - powerBottom) / powerRange;
          const y = padding + (1 - normalizedLevel) * plotHeight;

          if (index === 0) {
            ctx.moveTo(x, y);
          } else {
            ctx.lineTo(x, y);
          }
        });

        ctx.stroke();
      }

      ctx.fillStyle = '#cbd5e1';
      ctx.font = '12px sans-serif';
      ctx.textAlign = 'left';
      ctx.fillText(`${settings.dbPerDiv} dB/div | ${settings.traceMode} | ${settings.detectorMode}`, padding, 18);
    });

    return () => cancelAnimationFrame(animationFrame);
  }, [spectrumData, settings]);

  // Auto-refresh spectrum
  useEffect(() => {
    let cancelled = false;

    const refresh = async () => {
      if (!deviceStatus.isConnected) {
        return;
      }

      try {
        setIsLoading(true);
        const data = await apiService.getLiveSpectrum();
        if (!cancelled) {
          setSpectrumData(data);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to refresh spectrum');
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };

    refresh();
    const interval = setInterval(refresh, 200);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [deviceStatus.isConnected, setSpectrumData]);

  return {
    spectrumData,
    settings,
    isLoading,
    error,
    canvasRef,
  };
};
