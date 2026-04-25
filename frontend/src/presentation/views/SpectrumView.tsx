import React, { useEffect, useMemo, useRef, useState } from 'react';
import { BarChart3, ChevronLeft, ChevronRight, Download, Eye, EyeOff, Image, Move, Play, Square, RotateCcw, Target, Usb, Unplug, Radio, Trash2, SlidersHorizontal, X } from 'lucide-react';
import { useSpectrum } from '../hooks/useSpectrum';
import { useWaterfall } from '../hooks/useWaterfall';
import { useSpectrumController } from '../controllers/SpectrumController';
import { getLevelAtFrequency, useMarkerController } from '../controllers/MarkerController';
import { useAnalyzerSettings, useAppActions, useDeviceStatus, useMarkers, useSpectrumData } from '../../app/store/AppStore';
import { estimateBandQuality, formatFrequency, formatPowerLevel } from '../../shared/utils';
import { cn } from '../../shared/utils';
import { DETECTOR_MODES, SPECTRUM_COLOR_SCHEMES, TRACE_MODES } from '../../shared/constants';
import type { AnalyzerSettings } from '../../shared/types';

const hzToMhz = (hz: number) => Number.isFinite(hz) ? hz / 1e6 : 0;
const mhzToHz = (mhz: string) => Number(mhz) * 1e6;
const khzToHz = (khz: string) => Number(khz) * 1e3;
const spectrumOverlayStorageKey = 'spectrum-view-overlay-preferences';

const formatInput = (value: number, digits = 6) => {
  if (!Number.isFinite(value)) return '';
  return Number(value.toFixed(digits)).toString();
};

const computeStats = (levels: number[]) => {
  const finite = levels.filter(Number.isFinite);
  if (finite.length === 0) {
    return { min: Number.NaN, max: Number.NaN, mean: Number.NaN, std: Number.NaN };
  }
  const min = Math.min(...finite);
  const max = Math.max(...finite);
  const mean = finite.reduce((sum, value) => sum + value, 0) / finite.length;
  const variance = finite.reduce((sum, value) => sum + (value - mean) ** 2, 0) / finite.length;
  return { min, max, mean, std: Math.sqrt(variance) };
};

const findLocalPeaks = (frequencies: number[], levels: number[], count = 3) => {
  const peaks: Array<{ frequency: number; level: number }> = [];
  for (let index = 1; index < levels.length - 1; index += 1) {
    const level = levels[index];
    if (Number.isFinite(level) && level >= levels[index - 1] && level >= levels[index + 1]) {
      peaks.push({ frequency: frequencies[index], level });
    }
  }
  return peaks.sort((a, b) => b.level - a.level).slice(0, count);
};

const getErrorMessage = (error: unknown) => {
  if (typeof error === 'object' && error !== null && 'response' in error) {
    const response = (error as { response?: { data?: { detail?: string } } }).response;
    if (response?.data?.detail) return response.data.detail;
  }
  return error instanceof Error ? error.message : 'Operation failed';
};

const findStrongestPeak = (frequencies: number[], levels: number[]) => {
  if (frequencies.length === 0 || levels.length === 0 || frequencies.length !== levels.length) {
    return null;
  }
  let peakIndex = 0;
  let peakLevel = -Infinity;
  for (let index = 0; index < levels.length; index += 1) {
    const level = levels[index];
    if (Number.isFinite(level) && level > peakLevel) {
      peakLevel = level;
      peakIndex = index;
    }
  }
  const peakFrequency = frequencies[peakIndex];
  if (!Number.isFinite(peakFrequency) || !Number.isFinite(peakLevel)) {
    return null;
  }
  return {
    frequency: peakFrequency,
    level: peakLevel,
  };
};

export const SpectrumView: React.FC = () => {
  const { canvasRef } = useSpectrum();
  const [showWaterfallSplit, setShowWaterfallSplit] = useState(false);
  const { canvasRef: waterfallCanvasRef, error: waterfallError } = useWaterfall(showWaterfallSplit);
  const spectrumData = useSpectrumData();
  const deviceStatus = useDeviceStatus();
  const settings = useAnalyzerSettings();
  const markers = useMarkers();
  const { setGlobalActivity, clearGlobalActivity } = useAppActions();
  const spectrumController = useSpectrumController();
  const markerController = useMarkerController();

  const [isStreaming, setIsStreaming] = useState(false);
  const [centerMHz, setCenterMHz] = useState(formatInput(hzToMhz(settings.centerFrequency)));
  const [spanMHz, setSpanMHz] = useState(formatInput(hzToMhz(settings.span), 3));
  const [panStepMHz, setPanStepMHz] = useState(formatInput(hzToMhz(settings.span) / 10, 3));
  const [startMHz, setStartMHz] = useState(formatInput(hzToMhz(settings.centerFrequency - settings.span / 2)));
  const [stopMHz, setStopMHz] = useState(formatInput(hzToMhz(settings.centerFrequency + settings.span / 2)));
  const [rbwKHz, setRbwKHz] = useState(formatInput(settings.rbw / 1e3, 2));
  const [vbwKHz, setVbwKHz] = useState(formatInput(settings.vbw / 1e3, 2));
  const [refLevel, setRefLevel] = useState(formatInput(settings.referenceLevel, 1));
  const [noiseOffset, setNoiseOffset] = useState(formatInput(settings.noiseFloorOffset, 1));
  const [detectorMode, setDetectorMode] = useState<AnalyzerSettings['detectorMode']>(settings.detectorMode);
  const [traceMode, setTraceMode] = useState<AnalyzerSettings['traceMode']>(settings.traceMode);
  const [dbPerDiv, setDbPerDiv] = useState(formatInput(settings.dbPerDiv, 1));
  const [colorScheme, setColorScheme] = useState<AnalyzerSettings['colorScheme']>(settings.colorScheme);
  const [averaging, setAveraging] = useState(formatInput(settings.averaging, 0));
  const [gainDb, setGainDb] = useState(formatInput(deviceStatus.gain, 1));
  const [controlError, setControlError] = useState<string | null>(null);
  const [cursor, setCursor] = useState<{ frequency: number; level: number } | null>(null);
  const [draggingMarkerId, setDraggingMarkerId] = useState<string | null>(null);
  const [showPanOverlay, setShowPanOverlay] = useState(true);
  const [showMarkerBadges, setShowMarkerBadges] = useState(true);
  const [showCursorBadge, setShowCursorBadge] = useState(true);
  const [panOverlayPosition, setPanOverlayPosition] = useState({ x: 16, y: 16 });
  const dragStateRef = useRef<{ type: 'pan' | null; offsetX: number; offsetY: number }>({ type: null, offsetX: 0, offsetY: 0 });
  const suppressNextClickRef = useRef(false);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(spectrumOverlayStorageKey);
      if (!raw) return;
      const parsed = JSON.parse(raw) as {
        showPanOverlay?: boolean;
        showMarkerBadges?: boolean;
        showCursorBadge?: boolean;
        panOverlayPosition?: { x?: number; y?: number };
      };
      if (typeof parsed.showPanOverlay === 'boolean') setShowPanOverlay(parsed.showPanOverlay);
      if (typeof parsed.showMarkerBadges === 'boolean') setShowMarkerBadges(parsed.showMarkerBadges);
      if (typeof parsed.showCursorBadge === 'boolean') setShowCursorBadge(parsed.showCursorBadge);
      if (
        parsed.panOverlayPosition &&
        Number.isFinite(parsed.panOverlayPosition.x) &&
        Number.isFinite(parsed.panOverlayPosition.y)
      ) {
        setPanOverlayPosition({
          x: Number(parsed.panOverlayPosition.x),
          y: Number(parsed.panOverlayPosition.y),
        });
      }
    } catch {
      // Ignore invalid persisted UI state.
    }
  }, []);

  useEffect(() => {
    try {
      window.localStorage.setItem(
        spectrumOverlayStorageKey,
        JSON.stringify({
          showPanOverlay,
          showMarkerBadges,
          showCursorBadge,
          panOverlayPosition,
        }),
      );
    } catch {
      // Ignore storage failures.
    }
  }, [showPanOverlay, showMarkerBadges, showCursorBadge, panOverlayPosition]);

  useEffect(() => {
    setCenterMHz(formatInput(hzToMhz(settings.centerFrequency)));
    setSpanMHz(formatInput(hzToMhz(settings.span), 3));
    setStartMHz(formatInput(hzToMhz(settings.centerFrequency - settings.span / 2)));
    setStopMHz(formatInput(hzToMhz(settings.centerFrequency + settings.span / 2)));
    setRbwKHz(formatInput(settings.rbw / 1e3, 2));
    setVbwKHz(formatInput(settings.vbw / 1e3, 2));
    setRefLevel(formatInput(settings.referenceLevel, 1));
    setNoiseOffset(formatInput(settings.noiseFloorOffset, 1));
    setDetectorMode(settings.detectorMode);
    setTraceMode(settings.traceMode);
    setDbPerDiv(formatInput(settings.dbPerDiv, 1));
    setColorScheme(settings.colorScheme);
    setAveraging(formatInput(settings.averaging, 0));
  }, [
    settings.centerFrequency,
    settings.span,
    settings.rbw,
    settings.vbw,
    settings.referenceLevel,
    settings.noiseFloorOffset,
    settings.detectorMode,
    settings.traceMode,
    settings.dbPerDiv,
    settings.colorScheme,
    settings.averaging,
  ]);

  useEffect(() => {
    setPanStepMHz(formatInput(hzToMhz(settings.span) / 10, 3));
  }, [settings.span]);

  useEffect(() => {
    setGainDb(formatInput(deviceStatus.gain, 1));
  }, [deviceStatus.gain]);

  const markerRows = useMemo(() => {
    return markers.map((marker) => {
      const liveLevel = spectrumData
        ? getLevelAtFrequency(marker.frequency, spectrumData.frequencyArray, spectrumData.powerLevels)
        : marker.level;
      return {
        ...marker,
        level: Number.isFinite(liveLevel) ? liveLevel : marker.level,
      };
    });
  }, [markers, spectrumData]);

  const traceStats = useMemo(() => computeStats(spectrumData?.powerLevels ?? []), [spectrumData]);

  const deltaMarker = useMemo(() => {
    if (markerRows.length < 2) return null;
    const first = markerRows[0];
    const second = markerRows[1];
    return {
      frequencyDelta: second.frequency - first.frequency,
      levelDelta: second.level - first.level,
    };
  }, [markerRows]);

  const liveMarkerBandQuality = useMemo(() => {
    if (!spectrumData || markerRows.length < 2) return null;
    const first = markerRows[0];
    const second = markerRows[1];
    const start = Math.min(first.frequency, second.frequency);
    const stop = Math.max(first.frequency, second.frequency);
    return estimateBandQuality(spectrumData.frequencyArray, spectrumData.powerLevels, start, stop);
  }, [markerRows, spectrumData]);

  const applyCenterSpan = async () => {
    const center = mhzToHz(centerMHz);
    const span = mhzToHz(spanMHz);
    if (!Number.isFinite(center) || center <= 0 || !Number.isFinite(span) || span <= 0) {
      setControlError('Center and span must be positive numeric values.');
      return;
    }
    setControlError(null);
    try {
      await spectrumController.setCenterFrequency(center);
      await spectrumController.setSpan(span);
    } catch (error) {
      setControlError(getErrorMessage(error));
    }
  };

  const applyStartStop = async () => {
    const start = mhzToHz(startMHz);
    const stop = mhzToHz(stopMHz);
    if (!Number.isFinite(start) || !Number.isFinite(stop) || start <= 0 || stop <= start) {
      setControlError('Start must be positive and lower than stop.');
      return;
    }
    setControlError(null);
    try {
      await spectrumController.setStartStop(start, stop);
    } catch (error) {
      setControlError(getErrorMessage(error));
    }
  };

  const panFrequencyWindow = async (direction: -1 | 1) => {
    const step = mhzToHz(panStepMHz);
    if (!Number.isFinite(step) || step <= 0) {
      setControlError('Step must be a positive numeric value.');
      return;
    }

    const nextCenter = settings.centerFrequency + direction * step;
    if (!Number.isFinite(nextCenter) || nextCenter <= 0) {
      setControlError('Center frequency must stay above 0 Hz.');
      return;
    }

    setControlError(null);
    try {
      await spectrumController.setCenterFrequency(nextCenter);
      await spectrumController.refreshSpectrum();
    } catch (error) {
      setControlError(getErrorMessage(error));
    }
  };

  const applyResolution = async () => {
    const rbw = khzToHz(rbwKHz);
    const vbw = khzToHz(vbwKHz);
    const ref = Number(refLevel);
    const offset = Number(noiseOffset);
    const avg = Number(averaging);
    const div = Number(dbPerDiv);
    if (
      !Number.isFinite(rbw) || rbw <= 0 ||
      !Number.isFinite(vbw) || vbw <= 0 ||
      !Number.isFinite(ref) ||
      !Number.isFinite(offset) ||
      !Number.isFinite(avg) || avg < 1 ||
      !Number.isFinite(div) || div <= 0
    ) {
      setControlError('RBW, VBW, dB/div and averaging must be positive. Ref and offset must be numeric.');
      return;
    }
    setControlError(null);
    try {
      await spectrumController.setRbw(rbw);
      await spectrumController.setVbw(vbw);
      await spectrumController.setReferenceLevel(ref);
      await spectrumController.setNoiseFloorOffset(offset);
      await spectrumController.setDetectorMode(detectorMode);
      await spectrumController.setAveraging(avg);
      spectrumController.setTraceDisplay({ traceMode, dbPerDiv: div, colorScheme });
    } catch (error) {
      setControlError(getErrorMessage(error));
    }
  };

  const applyGain = async () => {
    const gain = Number(gainDb);
    if (!Number.isFinite(gain)) {
      setControlError('Gain must be numeric.');
      return;
    }
    setControlError(null);
    try {
      await spectrumController.setGain(gain);
    } catch (error) {
      setControlError(getErrorMessage(error));
    }
  };

  const handleStartStop = async () => {
    if (isStreaming) {
      try {
        await spectrumController.stopDeviceStream();
        setIsStreaming(false);
      } catch (error) {
        setControlError(getErrorMessage(error));
      }
      return;
    }
    try {
      await spectrumController.startDeviceStream();
      setIsStreaming(true);
    } catch (error) {
      setControlError(getErrorMessage(error));
    }
  };

  const handleConnectDisconnect = async () => {
    if (deviceStatus.isConnected) {
      try {
        setGlobalActivity({
          visible: true,
          kind: 'processing',
          title: 'Disconnecting SDR',
          detail: 'Closing the active SDR session.',
        });
        await spectrumController.disconnectDevice();
        setIsStreaming(false);
      } catch (error) {
        setControlError(getErrorMessage(error));
      } finally {
        clearGlobalActivity();
      }
      return;
    }
    try {
      setGlobalActivity({
        visible: true,
        kind: 'connecting',
        title: 'Connecting to SDR',
        detail: 'The radio frontend may take a few seconds to initialize. You can keep navigating.',
      });
      await spectrumController.connectDevice();
    } catch (error) {
      setControlError(getErrorMessage(error));
    } finally {
      clearGlobalActivity();
    }
  };

  const addMarkerAtCanvas = async (event: React.MouseEvent<HTMLCanvasElement>) => {
    if (suppressNextClickRef.current) {
      suppressNextClickRef.current = false;
      return;
    }
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const relativeX = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
    const start = settings.centerFrequency - settings.span / 2;
    const frequency = start + relativeX * settings.span;
    const level = spectrumData
      ? getLevelAtFrequency(frequency, spectrumData.frequencyArray, spectrumData.powerLevels)
      : Number.NaN;
    await markerController.createMarker(frequency, undefined, level);
  };

  const frequencyFromPointer = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    const relativeX = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
    const start = settings.centerFrequency - settings.span / 2;
    return start + relativeX * settings.span;
  };

  const updateCursor = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const frequency = frequencyFromPointer(event);
    if (frequency === null) return;
    const level = spectrumData
      ? getLevelAtFrequency(frequency, spectrumData.frequencyArray, spectrumData.powerLevels)
      : Number.NaN;
    setCursor({ frequency, level });
    if (draggingMarkerId) {
      markerController.updateMarker(draggingMarkerId, { frequency, level: Number.isFinite(level) ? level : 0 });
    }
  };

  const startOverlayDrag = (event: React.MouseEvent<HTMLDivElement>) => {
    const container = event.currentTarget.parentElement;
    if (!container) return;
    const rect = container.getBoundingClientRect();
    dragStateRef.current = {
      type: 'pan',
      offsetX: event.clientX - rect.left,
      offsetY: event.clientY - rect.top,
    };
  };

  const stopOverlayDrag = () => {
    dragStateRef.current = { type: null, offsetX: 0, offsetY: 0 };
  };

  const dragOverlay = (event: React.MouseEvent<HTMLCanvasElement>) => {
    if (dragStateRef.current.type !== 'pan') return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const nextX = Math.max(8, Math.min(rect.width - 260, event.clientX - rect.left - dragStateRef.current.offsetX));
    const nextY = Math.max(8, Math.min(rect.height - 80, event.clientY - rect.top - dragStateRef.current.offsetY));
    setPanOverlayPosition({ x: nextX, y: nextY });
  };

  const startMarkerDrag = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const frequency = frequencyFromPointer(event);
    if (frequency === null) return;
    const toleranceHz = settings.span * 0.01;
    const marker = markerRows.find((item) => Math.abs(item.frequency - frequency) <= toleranceHz);
    if (marker) {
      suppressNextClickRef.current = true;
      setDraggingMarkerId(marker.id);
    }
  };

  const zoomFromWheel = async (event: React.WheelEvent<HTMLCanvasElement>) => {
    event.preventDefault();
    const zoomFactor = event.deltaY < 0 ? 0.8 : 1.25;
    const nextSpan = Math.max(settings.span * zoomFactor, 1_000);
    try {
      await spectrumController.setSpan(nextSpan);
    } catch (error) {
      setControlError(getErrorMessage(error));
    }
  };

  const createAutoPeaks = async () => {
    if (!spectrumData) return;
    const peaks = findLocalPeaks(spectrumData.frequencyArray, spectrumData.powerLevels, 3);
    for (const [index, peak] of peaks.entries()) {
      await markerController.createMarker(peak.frequency, `P${index + 1}`, peak.level);
    }
  };

  const centerOnLivePeak = async () => {
    if (!spectrumData) {
      setControlError('No live spectrum data available to recenter.');
      return;
    }
    const strongestPeak = findStrongestPeak(spectrumData.frequencyArray, spectrumData.powerLevels);
    if (!strongestPeak) {
      setControlError('No valid spectral peak available to recenter.');
      return;
    }

    setControlError(null);
    try {
      if (markerRows.length >= 2) {
        const first = markerRows[0];
        const second = markerRows[1];
        const markerBandwidth = Math.abs(second.frequency - first.frequency);
        const nextStart = strongestPeak.frequency - markerBandwidth / 2;
        const nextStop = strongestPeak.frequency + markerBandwidth / 2;
        if (!Number.isFinite(nextStart) || !Number.isFinite(nextStop) || nextStart <= 0 || nextStop <= nextStart) {
          setControlError('Unable to derive a valid marker-centered frequency window.');
          return;
        }

        await spectrumController.setStartStop(nextStart, nextStop);
        markerController.updateMarker(first.id, {
          frequency: nextStart,
          level: getLevelAtFrequency(nextStart, spectrumData.frequencyArray, spectrumData.powerLevels),
        });
        markerController.updateMarker(second.id, {
          frequency: nextStop,
          level: getLevelAtFrequency(nextStop, spectrumData.frequencyArray, spectrumData.powerLevels),
        });
        await spectrumController.refreshSpectrum();
        return;
      }

      await spectrumController.setCenterFrequency(strongestPeak.frequency);
      await spectrumController.refreshSpectrum();
    } catch (error) {
      setControlError(getErrorMessage(error));
    }
  };

  const removeLastMarker = async () => {
    if (markerRows.length === 0) return;
    const lastMarker = markerRows[markerRows.length - 1];
    await markerController.deleteMarker(lastMarker.id);
  };

  const exportCsv = () => {
    if (!spectrumData) return;
    const rows = ['frequency_hz,level_db'];
    spectrumData.frequencyArray.forEach((frequency, index) => {
      rows.push(`${frequency},${spectrumData.powerLevels[index] ?? ''}`);
    });
    const blob = new Blob([rows.join('\n')], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `spectraease_${Math.round(settings.centerFrequency)}Hz.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const exportPng = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const link = document.createElement('a');
    link.href = canvas.toDataURL('image/png');
    link.download = `spectraease_${Math.round(settings.centerFrequency)}Hz.png`;
    link.click();
  };

  return (
    <div className="h-full flex flex-col bg-slate-950 text-slate-100">
      <div className="border-b border-slate-800 bg-slate-900 px-4 py-3">
        <div className="flex flex-wrap items-end gap-3">
          <button
            onClick={handleConnectDisconnect}
            className={cn(
              'h-9 flex items-center px-3 rounded-md text-sm font-medium',
              deviceStatus.isConnected ? 'bg-slate-700 hover:bg-slate-600' : 'bg-emerald-600 hover:bg-emerald-500'
            )}
          >
            {deviceStatus.isConnected ? <Unplug className="w-4 h-4 mr-2" /> : <Usb className="w-4 h-4 mr-2" />}
            {deviceStatus.isConnected ? 'Disconnect' : 'Connect USB'}
          </button>

          <button
            onClick={handleStartStop}
            disabled={!deviceStatus.isConnected}
            className={cn(
              'h-9 flex items-center px-3 rounded-md text-sm font-medium',
              !deviceStatus.isConnected ? 'bg-slate-700 text-slate-400 cursor-not-allowed' :
              isStreaming ? 'bg-red-600 hover:bg-red-500' : 'bg-green-600 hover:bg-green-500'
            )}
          >
            {isStreaming ? <Square className="w-4 h-4 mr-2" /> : <Play className="w-4 h-4 mr-2" />}
            {isStreaming ? 'Stop' : 'Start'}
          </button>

          <button
            onClick={() => spectrumController.openWfmReceiver()}
            className="h-9 flex items-center px-3 rounded-md bg-indigo-600 hover:bg-indigo-500 text-sm font-medium"
          >
            <Radio className="w-4 h-4 mr-2" />
            WFM Receiver
          </button>

          <button
            onClick={() => spectrumController.refreshSpectrum()}
            className="h-9 flex items-center px-3 rounded-md bg-blue-600 hover:bg-blue-500 text-sm font-medium"
          >
            <RotateCcw className="w-4 h-4 mr-2" />
            Refresh
          </button>

          <button
            onClick={() => setShowWaterfallSplit((current) => !current)}
            aria-pressed={showWaterfallSplit}
            title={showWaterfallSplit ? 'Volver a solo espectro' : 'Dividir vista con waterfall'}
            className={cn(
              'h-9 flex items-center px-3 rounded-md text-sm font-medium',
              showWaterfallSplit ? 'bg-cyan-500 text-slate-950 hover:bg-cyan-400' : 'bg-slate-700 hover:bg-slate-600'
            )}
          >
            <BarChart3 className="w-4 h-4 mr-2" />
            {showWaterfallSplit ? 'Spectrum Only' : 'Spectrum + Waterfall'}
          </button>

          <button
            onClick={() => setShowPanOverlay((current) => !current)}
            className="h-9 flex items-center px-3 rounded-md bg-slate-700 hover:bg-slate-600 text-sm"
          >
            {showPanOverlay ? <EyeOff className="w-4 h-4 mr-2" /> : <Eye className="w-4 h-4 mr-2" />}
            Pan Overlay
          </button>

          <button
            onClick={() => setShowMarkerBadges((current) => !current)}
            className="h-9 flex items-center px-3 rounded-md bg-slate-700 hover:bg-slate-600 text-sm"
          >
            {showMarkerBadges ? <EyeOff className="w-4 h-4 mr-2" /> : <Eye className="w-4 h-4 mr-2" />}
            Marker Badges
          </button>

          <button
            onClick={() => setShowCursorBadge((current) => !current)}
            className="h-9 flex items-center px-3 rounded-md bg-slate-700 hover:bg-slate-600 text-sm"
          >
            {showCursorBadge ? <EyeOff className="w-4 h-4 mr-2" /> : <Eye className="w-4 h-4 mr-2" />}
            Cursor Badge
          </button>

          <div className="h-9 w-px bg-slate-700 mx-1" />

          <LabeledInput label="Center MHz" value={centerMHz} onChange={setCenterMHz} onEnter={applyCenterSpan} />
          <LabeledInput label="Span MHz" value={spanMHz} onChange={setSpanMHz} onEnter={applyCenterSpan} />
          <button onClick={applyCenterSpan} className="h-9 px-3 rounded-md bg-slate-700 hover:bg-slate-600 text-sm">Apply</button>
          <LabeledInput label="Step MHz" value={panStepMHz} onChange={setPanStepMHz} onEnter={() => undefined} compact />
          <button
            onClick={() => panFrequencyWindow(-1)}
            title="Desplazar espectro hacia la izquierda"
            className="h-9 inline-flex items-center gap-1.5 rounded-md bg-cyan-700 px-3 text-sm font-semibold text-white hover:bg-cyan-600"
          >
            <ChevronLeft className="w-5 h-5" />
            Spectrum Left
          </button>
          <button
            onClick={() => panFrequencyWindow(1)}
            title="Desplazar espectro hacia la derecha"
            className="h-9 inline-flex items-center gap-1.5 rounded-md bg-cyan-700 px-3 text-sm font-semibold text-white hover:bg-cyan-600"
          >
            Spectrum Right
            <ChevronRight className="w-5 h-5" />
          </button>

          <LabeledInput label="Start MHz" value={startMHz} onChange={setStartMHz} onEnter={applyStartStop} />
          <LabeledInput label="Stop MHz" value={stopMHz} onChange={setStopMHz} onEnter={applyStartStop} />
          <button onClick={applyStartStop} className="h-9 px-3 rounded-md bg-slate-700 hover:bg-slate-600 text-sm">Set Edges</button>

          <LabeledInput label="RBW kHz" value={rbwKHz} onChange={setRbwKHz} onEnter={applyResolution} compact />
          <LabeledInput label="VBW kHz" value={vbwKHz} onChange={setVbwKHz} onEnter={applyResolution} compact />
          <LabeledInput label="Ref dB" value={refLevel} onChange={setRefLevel} onEnter={applyResolution} compact />
          <LabeledInput label="Offset dB" value={noiseOffset} onChange={setNoiseOffset} onEnter={applyResolution} compact />
          <label className="flex flex-col gap-1 text-[11px] text-slate-400">
            Detector
            <select
              value={detectorMode}
              onChange={(event) => setDetectorMode(event.target.value as AnalyzerSettings['detectorMode'])}
              className="h-9 w-28 rounded-md border border-slate-700 bg-slate-950 px-2 text-sm text-slate-100 outline-none focus:border-blue-400"
            >
              {DETECTOR_MODES.map((mode) => (
                <option key={mode.value} value={mode.value}>{mode.label}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-[11px] text-slate-400">
            Trace
            <select
              value={traceMode}
              onChange={(event) => setTraceMode(event.target.value as AnalyzerSettings['traceMode'])}
              className="h-9 w-28 rounded-md border border-slate-700 bg-slate-950 px-2 text-sm text-slate-100 outline-none focus:border-blue-400"
            >
              {TRACE_MODES.map((mode) => (
                <option key={mode.value} value={mode.value}>{mode.label}</option>
              ))}
            </select>
          </label>
          <LabeledInput label="dB/div" value={dbPerDiv} onChange={setDbPerDiv} onEnter={applyResolution} compact />
          <label className="flex flex-col gap-1 text-[11px] text-slate-400">
            Color
            <select
              value={colorScheme}
              onChange={(event) => setColorScheme(event.target.value as AnalyzerSettings['colorScheme'])}
              className="h-9 w-24 rounded-md border border-slate-700 bg-slate-950 px-2 text-sm text-slate-100 outline-none focus:border-blue-400"
            >
              {SPECTRUM_COLOR_SCHEMES.map((scheme) => (
                <option key={scheme.value} value={scheme.value}>{scheme.label}</option>
              ))}
            </select>
          </label>
          <LabeledInput label="Avg" value={averaging} onChange={setAveraging} onEnter={applyResolution} compact />
          <button onClick={applyResolution} className="h-9 px-3 rounded-md bg-slate-700 hover:bg-slate-600 text-sm">
            <SlidersHorizontal className="w-4 h-4 mr-2 inline-block" />
            Apply Trace
          </button>

          <LabeledInput label="Gain dB" value={gainDb} onChange={setGainDb} onEnter={applyGain} compact />
          <button onClick={applyGain} className="h-9 px-3 rounded-md bg-slate-700 hover:bg-slate-600 text-sm">Gain</button>

          <button
            onClick={() => markerController.createPeakMarker()}
            className="h-9 flex items-center px-3 rounded-md bg-purple-600 hover:bg-purple-500 text-sm font-medium"
          >
            <Target className="w-4 h-4 mr-2" />
            Peak
          </button>
          <button
            onClick={centerOnLivePeak}
            disabled={!spectrumData || spectrumData.frequencyArray.length === 0}
            className={cn(
              'h-9 flex items-center px-3 rounded-md text-sm font-medium',
              !spectrumData || spectrumData.frequencyArray.length === 0
                ? 'bg-slate-700 text-slate-400 cursor-not-allowed'
                : 'bg-emerald-700 hover:bg-emerald-600 text-white'
            )}
          >
            <Target className="w-4 h-4 mr-2" />
            Center On Peak
          </button>
          <button
            onClick={createAutoPeaks}
            className="h-9 flex items-center px-3 rounded-md bg-purple-700 hover:bg-purple-600 text-sm font-medium"
          >
            Auto Peaks
          </button>
          <button
            onClick={() => removeLastMarker()}
            disabled={markerRows.length === 0}
            className={cn(
              'h-9 flex items-center px-3 rounded-md text-sm',
              markerRows.length === 0
                ? 'bg-slate-700 text-slate-400 cursor-not-allowed'
                : 'bg-slate-700 hover:bg-slate-600'
            )}
          >
            <Trash2 className="w-4 h-4 mr-2" />
            Remove One
          </button>
          <button
            onClick={() => markerController.clearAllMarkers()}
            className="h-9 flex items-center px-3 rounded-md bg-slate-700 hover:bg-slate-600 text-sm"
          >
            <Trash2 className="w-4 h-4 mr-2" />
            Clear
          </button>
          <button onClick={exportCsv} className="h-9 flex items-center px-3 rounded-md bg-slate-700 hover:bg-slate-600 text-sm">
            <Download className="w-4 h-4 mr-2" />
            CSV
          </button>
          <button onClick={exportPng} className="h-9 flex items-center px-3 rounded-md bg-slate-700 hover:bg-slate-600 text-sm">
            <Image className="w-4 h-4 mr-2" />
            PNG
          </button>
        </div>
        {controlError && <div className="mt-2 text-sm text-red-300">{controlError}</div>}
        {deviceStatus.lastError && <div className="mt-2 text-sm text-red-300">{deviceStatus.lastError}</div>}
        {showWaterfallSplit && waterfallError && <div className="mt-2 text-sm text-red-300">{waterfallError}</div>}
      </div>

      <div className="flex-1 grid grid-cols-[minmax(0,1fr)_320px] min-h-0">
        <div className="flex min-h-0 flex-col">
          <div className={cn('relative min-h-0', showWaterfallSplit ? 'flex-[3_1_0%]' : 'flex-1')}>
            {showPanOverlay && (
              <div
                className="absolute z-10 rounded-xl border border-slate-700/80 bg-slate-950/60 px-2 py-2 shadow-lg backdrop-blur-md"
                style={{ left: `${panOverlayPosition.x}px`, top: `${panOverlayPosition.y}px` }}
              >
                <div
                  className="mb-2 flex cursor-move items-center justify-between gap-2 rounded-lg bg-slate-900/70 px-2 py-1 text-[11px] uppercase tracking-[0.16em] text-slate-300"
                  onMouseDown={startOverlayDrag}
                >
                  <div className="flex items-center gap-1">
                    <Move className="w-3 h-3" />
                    Pan
                  </div>
                  <button
                    onClick={() => setShowPanOverlay(false)}
                    className="rounded-md p-1 text-slate-300 hover:bg-slate-800"
                    title="Ocultar panel"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => panFrequencyWindow(-1)}
                    title="Desplazar espectro hacia la izquierda"
                    className="h-8 inline-flex items-center gap-1 rounded-md bg-cyan-700/85 px-2 text-xs font-semibold text-white hover:bg-cyan-600"
                  >
                    <ChevronLeft className="w-4 h-4" />
                    Left
                  </button>
                  <LabeledInput label="Step MHz" value={panStepMHz} onChange={setPanStepMHz} onEnter={() => undefined} compact />
                  <button
                    onClick={() => panFrequencyWindow(1)}
                    title="Desplazar espectro hacia la derecha"
                    className="h-8 inline-flex items-center gap-1 rounded-md bg-cyan-700/85 px-2 text-xs font-semibold text-white hover:bg-cyan-600"
                  >
                    Right
                    <ChevronRight className="w-4 h-4" />
                  </button>
                </div>
              </div>
            )}
            <canvas
              ref={canvasRef}
              width={1400}
              height={720}
              className="w-full h-full cursor-crosshair bg-slate-950"
              onClick={addMarkerAtCanvas}
              onMouseDown={startMarkerDrag}
              onMouseMove={(event) => {
                dragOverlay(event);
                updateCursor(event);
              }}
              onMouseUp={() => {
                setDraggingMarkerId(null);
                stopOverlayDrag();
              }}
              onMouseLeave={() => {
                setCursor(null);
                setDraggingMarkerId(null);
                stopOverlayDrag();
              }}
              onWheel={zoomFromWheel}
            />
            {cursor && showCursorBadge && (
              <div className="absolute right-4 top-4 z-10 rounded-lg border border-slate-700/80 bg-slate-950/55 px-2 py-1 text-[11px] text-slate-100 shadow-lg backdrop-blur-md">
                {formatFrequency(cursor.frequency)} | {formatPowerLevel(cursor.level)}
              </div>
            )}
            {showMarkerBadges && markerRows.map((marker) => {
              const start = settings.centerFrequency - settings.span / 2;
              const position = ((marker.frequency - start) / settings.span) * 100;
              if (position < 0 || position > 100) return null;
              return (
                <div
                  key={marker.id}
                  className="absolute top-0 bottom-0 border-l border-amber-300/70 pointer-events-none"
                  style={{ left: `${position}%` }}
                >
                  <div className="ml-1 mt-1 rounded-md border border-amber-300/40 bg-amber-300/18 px-1.5 py-0.5 text-[10px] whitespace-nowrap text-amber-100 backdrop-blur-sm">
                    {marker.label} {formatFrequency(marker.frequency)}
                  </div>
                </div>
              );
            })}
          </div>

          {showWaterfallSplit && (
            <div className="relative min-h-[180px] flex-[2_1_0%] border-t border-slate-700 bg-black">
              <div className="absolute left-4 top-3 z-10 rounded-md border border-slate-700 bg-slate-900/95 px-3 py-2 text-xs text-slate-100 shadow-lg">
                Waterfall | {formatFrequency(settings.centerFrequency - settings.span / 2)} - {formatFrequency(settings.centerFrequency + settings.span / 2)}
              </div>
              <canvas
                ref={waterfallCanvasRef}
                width={1400}
                height={420}
                className="h-full w-full bg-black"
              />
              <div className="absolute bottom-2 left-10 right-10 flex justify-between text-xs text-slate-300">
                <span>{formatFrequency(settings.centerFrequency - settings.span / 2)}</span>
                <span>{formatFrequency(settings.centerFrequency)}</span>
                <span>{formatFrequency(settings.centerFrequency + settings.span / 2)}</span>
              </div>
              <div className="absolute right-4 top-3 bottom-8 w-4 rounded-sm bg-gradient-to-b from-red-600 via-yellow-400 via-green-500 to-blue-900" />
            </div>
          )}
        </div>

        <aside className="border-l border-slate-800 bg-slate-900 p-3 overflow-auto">
          <div className="text-xs uppercase text-slate-400 mb-2">Device Status</div>
          <StatusRow label="Status" value={deviceStatus.isConnected ? 'Connected' : 'Disconnected'} tone={deviceStatus.isConnected ? 'ok' : 'bad'} />
          <StatusRow label="Driver" value={deviceStatus.driver} />
          <StatusRow label="Center" value={formatFrequency(settings.centerFrequency)} />
          <StatusRow label="Span" value={formatFrequency(settings.span)} />
          <StatusRow label="Start" value={formatFrequency(settings.centerFrequency - settings.span / 2)} />
          <StatusRow label="Stop" value={formatFrequency(settings.centerFrequency + settings.span / 2)} />
          <StatusRow label="Sample Rate" value={formatFrequency(deviceStatus.sampleRate || settings.span) + '/s'} />
          <StatusRow label="RBW" value={formatFrequency(settings.rbw)} />
          <StatusRow label="VBW" value={formatFrequency(settings.vbw)} />
          <StatusRow label="Ref" value={formatPowerLevel(settings.referenceLevel)} />
          <StatusRow label="Offset" value={formatPowerLevel(settings.noiseFloorOffset)} />
          <StatusRow label="Detector" value={settings.detectorMode} />
          <StatusRow label="Trace" value={settings.traceMode} />
          <StatusRow label="Scale" value={`${settings.dbPerDiv} dB/div`} />
          <StatusRow label="Averaging" value={`${settings.averaging}x`} />
          <StatusRow label="Gain" value={formatPowerLevel(deviceStatus.gain)} />

          <div className="mt-5 text-xs uppercase text-slate-400 mb-2">Trace Stats</div>
          <StatusRow label="Mean" value={formatPowerLevel(traceStats.mean)} />
          <StatusRow label="Max" value={formatPowerLevel(traceStats.max)} />
          <StatusRow label="Min" value={formatPowerLevel(traceStats.min)} />
          <StatusRow label="Std Dev" value={formatPowerLevel(traceStats.std)} />

          {deltaMarker && (
            <>
              <div className="mt-5 text-xs uppercase text-slate-400 mb-2">Delta M2-M1</div>
              <StatusRow label="Delta F" value={formatFrequency(deltaMarker.frequencyDelta)} />
              <StatusRow label="Delta L" value={formatPowerLevel(deltaMarker.levelDelta)} />
            </>
          )}

          {liveMarkerBandQuality && (
            <>
              <div className="mt-5 text-xs uppercase text-slate-400 mb-2">Marker-Band QC</div>
              <StatusRow label="Peak" value={formatPowerLevel(liveMarkerBandQuality.peakLevelDb)} />
              <StatusRow label="Noise" value={formatPowerLevel(liveMarkerBandQuality.noiseFloorDb)} />
              <StatusRow label="SNR" value={`${liveMarkerBandQuality.snrDb.toFixed(1)} dB`} />
              <StatusRow label="Peak Freq" value={formatFrequency(liveMarkerBandQuality.peakFrequencyHz)} />
            </>
          )}

          <div className="mt-5 text-xs uppercase text-slate-400 mb-2">Markers</div>
          <div className="overflow-hidden rounded-md border border-slate-800">
            <table className="w-full text-sm">
              <thead className="bg-slate-800 text-slate-300">
                <tr>
                  <th className="text-left px-2 py-1">ID</th>
                  <th className="text-right px-2 py-1">Frequency</th>
                  <th className="text-right px-2 py-1">Level</th>
                </tr>
              </thead>
              <tbody>
                {markerRows.length === 0 ? (
                  <tr><td colSpan={3} className="px-2 py-3 text-slate-500">Click trace to add marker</td></tr>
                ) : markerRows.map((marker) => (
                  <tr key={marker.id} className="border-t border-slate-800">
                    <td className="px-2 py-1 text-amber-300">{marker.label}</td>
                    <td className="px-2 py-1 text-right">{formatFrequency(marker.frequency)}</td>
                    <td className="px-2 py-1 text-right">{formatPowerLevel(marker.level)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </aside>
      </div>
    </div>
  );
};

function LabeledInput({
  label,
  value,
  onChange,
  onEnter,
  compact = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  onEnter: () => void;
  compact?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1 text-[11px] text-slate-400">
      {label}
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') onEnter();
        }}
        className={cn(
          'h-9 rounded-md border border-slate-700 bg-slate-950 px-2 text-sm text-slate-100 outline-none focus:border-blue-400',
          compact ? 'w-20' : 'w-28'
        )}
      />
    </label>
  );
}

function StatusRow({ label, value, tone }: { label: string; value: string; tone?: 'ok' | 'bad' }) {
  return (
    <div className="flex justify-between gap-3 border-b border-slate-800 py-1.5 text-sm">
      <span className="text-slate-400">{label}</span>
      <span className={cn('text-right font-medium', tone === 'ok' && 'text-green-300', tone === 'bad' && 'text-red-300')}>
        {value}
      </span>
    </div>
  );
}
