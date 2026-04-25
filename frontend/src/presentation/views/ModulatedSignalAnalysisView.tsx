import React, { useEffect, useMemo, useState } from 'react';
import { Database, Download, Play, RotateCcw, ShieldCheck } from 'lucide-react';
import { ApiService } from '../../app/services/ApiService';
import { useAnalyzerSettings, useAppActions, useMarkers, useSpectrumData } from '../../app/store/AppStore';
import { MODULATION_HINTS } from '../../shared/constants';
import { ModulatedSignalCapture } from '../../shared/types';
import { estimateBandQuality, formatFrequency, formatPowerLevel } from '../../shared/utils';
import { cn } from '../../shared/utils';

const apiService = new ApiService();

const splitHelp = {
  train: 'Entrena el modelo. No reutilizar luego para validacion ni prediccion.',
  val: 'Se reserva solo para validacion externa. No mezclar con train.',
  predict: 'Se usa para inferencia sobre muestras nuevas. No contaminar train ni val.',
} as const;

const CAPTURE_LAB_MAX_BANDWIDTH_HZ = 10_000_000;
const CAPTURE_LAB_MAX_DURATION_S = 120;
const CAPTURE_LAB_CENTER_WARNING_FRACTION = 0.25;
const LIVE_OFFSET_VALID_HZ = 5_000;
const LIVE_OFFSET_DOUBTFUL_HZ = 20_000;

const getErrorMessage = (error: unknown) => {
  if (typeof error === 'object' && error !== null && 'response' in error) {
    const response = (error as { response?: { data?: { detail?: string } } }).response;
    if (response?.data?.detail) return response.data.detail;
  }
  return error instanceof Error ? error.message : 'Operation failed';
};

const formatBytes = (value: number) => {
  if (!Number.isFinite(value) || value <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
};

const formatMHz = (hz: number) => (hz / 1e6).toFixed(6);

export const ModulatedSignalAnalysisView: React.FC = () => {
  const markers = useMarkers();
  const analyzerSettings = useAnalyzerSettings();
  const spectrumData = useSpectrumData();
  const { setGlobalActivity, clearGlobalActivity } = useAppActions();
  const [durationSeconds, setDurationSeconds] = useState('5');
  const [fileFormat, setFileFormat] = useState<'cfile' | 'iq'>('cfile');
  const [captureBandMode, setCaptureBandMode] = useState<'markers' | 'custom'>('markers');
  const [bandSourcePinned, setBandSourcePinned] = useState(false);
  const [customStartMHz, setCustomStartMHz] = useState('');
  const [customStopMHz, setCustomStopMHz] = useState('');
  const [customCenterMHz, setCustomCenterMHz] = useState('');
  const [customBandwidthMHz, setCustomBandwidthMHz] = useState('');
  const [datasetSplit, setDatasetSplit] = useState<'train' | 'val' | 'predict'>('train');
  const [label, setLabel] = useState('remote_001');
  const [transmitterId, setTransmitterId] = useState('tx_remote_001');
  const [transmitterClass, setTransmitterClass] = useState('garage_remote');
  const [sessionId, setSessionId] = useState('session_001');
  const [operator, setOperator] = useState('operator_a');
  const [environment, setEnvironment] = useState('indoor_lab_los');
  const [modulationHint, setModulationHint] = useState('unknown');
  const [notes, setNotes] = useState('');
  const [autoImport, setAutoImport] = useState(true);
  const [captureMode, setCaptureMode] = useState<'immediate' | 'triggered_burst'>('immediate');
  const [triggerThresholdDb, setTriggerThresholdDb] = useState('6');
  const [preTriggerMs, setPreTriggerMs] = useState('0');
  const [postTriggerMs, setPostTriggerMs] = useState('50');
  const [triggerMaxWaitSeconds, setTriggerMaxWaitSeconds] = useState('5');
  const [isCapturing, setIsCapturing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [captures, setCaptures] = useState<ModulatedSignalCapture[]>([]);

  const selectedBand = useMemo(() => {
    if (markers.length < 2) return null;
    const [first, second] = markers;
    const start = Math.min(first.frequency, second.frequency);
    const stop = Math.max(first.frequency, second.frequency);
    return {
      start,
      stop,
      center: start + (stop - start) / 2,
      bandwidth: stop - start,
      first,
      second,
    };
  }, [markers]);

  const customBand = useMemo(() => {
    const start = Number(customStartMHz) * 1e6;
    const stop = Number(customStopMHz) * 1e6;
    if (!Number.isFinite(start) || !Number.isFinite(stop) || start <= 0 || stop <= start) {
      return null;
    }
    return {
      start,
      stop,
      center: start + (stop - start) / 2,
      bandwidth: stop - start,
    };
  }, [customStartMHz, customStopMHz]);

  const activeBand = captureBandMode === 'markers' ? selectedBand : customBand;
  const activeBandSourceLabel = captureBandMode === 'markers' ? 'Markers M1-M2' : 'Custom Frequencies';
  const liveBandQuality = useMemo(() => {
    if (!activeBand || !spectrumData) return null;
    return estimateBandQuality(
      spectrumData.frequencyArray,
      spectrumData.powerLevels,
      activeBand.start,
      activeBand.stop,
    );
  }, [activeBand, spectrumData]);
  const liveCenteringAssessment = useMemo(() => {
    if (!activeBand || !liveBandQuality) return null;
    const offsetHz = liveBandQuality.peakFrequencyHz - activeBand.center;
    const absOffsetHz = Math.abs(offsetHz);
    const warningThresholdHz = activeBand.bandwidth * CAPTURE_LAB_CENTER_WARNING_FRACTION;
    const isWarning = absOffsetHz > warningThresholdHz;
    const validMarginHz = LIVE_OFFSET_VALID_HZ - absOffsetHz;
    const doubtfulMarginHz = LIVE_OFFSET_DOUBTFUL_HZ - absOffsetHz;
    let risk: 'valid' | 'doubtful' | 'rejected' = 'valid';
    let riskLabel = 'Valid risk';
    let riskDetail = 'El offset en vivo está dentro del rango objetivo para una captura bien centrada.';
    if (absOffsetHz > LIVE_OFFSET_DOUBTFUL_HZ) {
      risk = 'rejected';
      riskLabel = 'Rejected risk';
      riskDetail = 'Si capturas así, la muestra tiene muchas probabilidades de acabar rechazada por offset extremo.';
    } else if (absOffsetHz > LIVE_OFFSET_VALID_HZ) {
      risk = 'doubtful';
      riskLabel = 'Doubtful risk';
      riskDetail = 'La captura puede acabar en zona dudosa o degradarse offline. Conviene recentrar antes de grabar.';
    }
    return {
      offsetHz,
      absOffsetHz,
      warningThresholdHz,
      isWarning,
      risk,
      riskLabel,
      riskDetail,
      validMarginHz,
      doubtfulMarginHz,
    };
  }, [activeBand, liveBandQuality]);
  const requestedDuration = Number(durationSeconds);
  const requestedTriggerThresholdDb = Number(triggerThresholdDb);
  const requestedPreTriggerMs = Number(preTriggerMs);
  const requestedPostTriggerMs = Number(postTriggerMs);
  const requestedTriggerMaxWaitSeconds = Number(triggerMaxWaitSeconds);
  const captureValidationMessage = useMemo(() => {
    if (!activeBand) {
      return captureBandMode === 'markers'
        ? 'Create at least two markers to define the capture band.'
        : 'Enter a valid frequency window. Start must be lower than stop and both must be positive.';
    }
    if (activeBand.bandwidth > CAPTURE_LAB_MAX_BANDWIDTH_HZ) {
      return `Capture Lab supports up to ${(CAPTURE_LAB_MAX_BANDWIDTH_HZ / 1e6).toFixed(1)} MHz of bandwidth in this workflow. Reduce the requested window.`;
    }
    if (!Number.isFinite(requestedDuration) || requestedDuration <= 0 || requestedDuration > CAPTURE_LAB_MAX_DURATION_S) {
      return `Duration must be between 0 and ${CAPTURE_LAB_MAX_DURATION_S} seconds.`;
    }
    if (captureMode === 'triggered_burst') {
      if (!Number.isFinite(requestedTriggerThresholdDb) || requestedTriggerThresholdDb <= 0 || requestedTriggerThresholdDb > 40) {
        return 'Triggered Burst threshold must be between 0 and 40 dB above the estimated noise floor.';
      }
      if (!Number.isFinite(requestedPreTriggerMs) || requestedPreTriggerMs < 0 || requestedPreTriggerMs > 5000) {
        return 'Pre-trigger must be between 0 and 5000 ms.';
      }
      if (!Number.isFinite(requestedPostTriggerMs) || requestedPostTriggerMs < 0 || requestedPostTriggerMs > 5000) {
        return 'Post-trigger must be between 0 and 5000 ms.';
      }
      if (!Number.isFinite(requestedTriggerMaxWaitSeconds) || requestedTriggerMaxWaitSeconds <= 0 || requestedTriggerMaxWaitSeconds > 120) {
        return 'Trigger max wait must be between 0 and 120 seconds.';
      }
    }
    return null;
  }, [
    activeBand,
    captureBandMode,
    requestedDuration,
    captureMode,
    requestedTriggerThresholdDb,
    requestedPreTriggerMs,
    requestedPostTriggerMs,
    requestedTriggerMaxWaitSeconds,
  ]);

  const loadCaptures = async () => {
    const data = await apiService.getModulatedSignalCaptures();
    setCaptures(data);
  };

  useEffect(() => {
    loadCaptures().catch(() => undefined);
  }, []);

  useEffect(() => {
    const start = (analyzerSettings.centerFrequency - analyzerSettings.span / 2) / 1e6;
    const stop = (analyzerSettings.centerFrequency + analyzerSettings.span / 2) / 1e6;
    setCustomStartMHz(start.toFixed(6));
    setCustomStopMHz(stop.toFixed(6));
    setCustomCenterMHz(formatMHz(analyzerSettings.centerFrequency));
    setCustomBandwidthMHz(formatMHz(analyzerSettings.span));
  }, [analyzerSettings.centerFrequency, analyzerSettings.span]);

  useEffect(() => {
    if (!bandSourcePinned && selectedBand) {
      setCaptureBandMode('markers');
    }
  }, [selectedBand, bandSourcePinned]);

  const useAnalyzerWindow = () => {
    const startHz = analyzerSettings.centerFrequency - analyzerSettings.span / 2;
    const stopHz = analyzerSettings.centerFrequency + analyzerSettings.span / 2;
    setCustomStartMHz(formatMHz(startHz));
    setCustomStopMHz(formatMHz(stopHz));
    setCustomCenterMHz(formatMHz(analyzerSettings.centerFrequency));
    setCustomBandwidthMHz(formatMHz(analyzerSettings.span));
    setCaptureBandMode('custom');
    setBandSourcePinned(true);
  };

  const centerOnLivePeak = () => {
    if (!activeBand || !liveBandQuality) {
      return;
    }
    const bandwidthHz = activeBand.bandwidth;
    const centerHz = liveBandQuality.peakFrequencyHz;
    const startHz = centerHz - bandwidthHz / 2;
    const stopHz = centerHz + bandwidthHz / 2;
    if (startHz <= 0 || stopHz <= startHz) {
      return;
    }
    setCustomCenterMHz(formatMHz(centerHz));
    setCustomBandwidthMHz(formatMHz(bandwidthHz));
    setCustomStartMHz(formatMHz(startHz));
    setCustomStopMHz(formatMHz(stopHz));
    setCaptureBandMode('custom');
    setBandSourcePinned(true);
  };

  const useCurrentMarkersNow = () => {
    if (!selectedBand) {
      setError('Create at least two markers in Live Monitor before using marker-driven capture.');
      return;
    }
    setError(null);
    setCaptureBandMode('markers');
    setBandSourcePinned(false);
  };

  const updateFromStartStop = (startMHzValue: string, stopMHzValue: string) => {
    setCustomStartMHz(startMHzValue);
    setCustomStopMHz(stopMHzValue);
    const startHz = Number(startMHzValue) * 1e6;
    const stopHz = Number(stopMHzValue) * 1e6;
    if (!Number.isFinite(startHz) || !Number.isFinite(stopHz) || startHz <= 0 || stopHz <= startHz) {
      return;
    }
    const centerHz = startHz + (stopHz - startHz) / 2;
    const bandwidthHz = stopHz - startHz;
    setCustomCenterMHz(formatMHz(centerHz));
    setCustomBandwidthMHz(formatMHz(bandwidthHz));
  };

  const updateFromCenterBandwidth = (centerMHzValue: string, bandwidthMHzValue: string) => {
    setCustomCenterMHz(centerMHzValue);
    setCustomBandwidthMHz(bandwidthMHzValue);
    const centerHz = Number(centerMHzValue) * 1e6;
    const bandwidthHz = Number(bandwidthMHzValue) * 1e6;
    if (!Number.isFinite(centerHz) || !Number.isFinite(bandwidthHz) || centerHz <= 0 || bandwidthHz <= 0) {
      return;
    }
    const startHz = centerHz - bandwidthHz / 2;
    const stopHz = centerHz + bandwidthHz / 2;
    if (startHz <= 0 || stopHz <= startHz) {
      return;
    }
    setCustomStartMHz(formatMHz(startHz));
    setCustomStopMHz(formatMHz(stopHz));
  };

  const captureSignal = async () => {
    if (!activeBand) {
      setError(
        captureBandMode === 'markers'
          ? 'Create at least two markers first. M1 and M2 define the capture band.'
          : 'Set valid custom start and stop frequencies before capturing.',
      );
      return;
    }

    const duration = Number(durationSeconds);
    if (captureValidationMessage) {
      setError(captureValidationMessage);
      return;
    }

    setError(null);
    setSuccess(null);
    setIsCapturing(true);
    setGlobalActivity({
      visible: true,
      kind: 'capturing',
      title: `Capturing ${datasetSplit.toUpperCase()} dataset segment`,
      detail: `${formatFrequency(activeBand.start)} to ${formatFrequency(activeBand.stop)} · ${duration}s · Navigation remains available.`,
    });
    try {
      const capture = await apiService.captureModulatedSignal({
        startFrequencyHz: activeBand.start,
        stopFrequencyHz: activeBand.stop,
        durationSeconds: duration,
        label,
        modulationHint,
        notes,
        datasetSplit,
        sessionId,
        transmitterId,
        transmitterClass,
        operator,
        environment,
        fileFormat,
        livePreviewSnrDb: liveBandQuality?.snrDb,
        livePreviewNoiseFloorDb: liveBandQuality?.noiseFloorDb,
        livePreviewPeakLevelDb: liveBandQuality?.peakLevelDb,
        livePreviewPeakFrequencyHz: liveBandQuality?.peakFrequencyHz,
        captureMode,
        triggerThresholdDb: requestedTriggerThresholdDb,
        preTriggerMs: requestedPreTriggerMs,
        postTriggerMs: requestedPostTriggerMs,
        triggerMaxWaitSeconds: requestedTriggerMaxWaitSeconds,
      });

      if (autoImport) {
        await apiService.importModulatedCaptureToFingerprinting(capture.id, {
          session_id: sessionId,
          dataset_split: datasetSplit,
          transmitter_label: label,
          transmitter_class: transmitterClass,
          transmitter_id: transmitterId,
          operator,
          environment,
          notes,
          ground_truth_confidence: 'confirmed',
        });
      }

      setCaptures((current) => [capture, ...current.filter((item) => item.id !== capture.id)]);
      setSuccess(
        autoImport
          ? `Capture ${capture.id} stored and imported as ${datasetSplit}.`
          : `Capture ${capture.id} stored as raw IQ metadata with split ${datasetSplit}.`,
      );
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setIsCapturing(false);
      clearGlobalActivity();
    }
  };

  return (
    <div className="h-full overflow-auto bg-slate-950 text-slate-100">
      <div className="mx-auto max-w-7xl space-y-5 p-6">
        <section className="rounded-md border border-slate-800 bg-slate-900 p-4">
          <div className="flex items-center justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold">Capture Lab</h2>
              <p className="text-sm text-slate-400">
                Esta es ahora la pantalla principal de captura. Captura IQ real entre M1 y M2, define si la muestra es
                para `train`, `val` o `predict`, y la deja lista para que entrenamiento, validación o inferencia la detecten automáticamente.
              </p>
            </div>
            <button
              onClick={() => loadCaptures()}
              className="inline-flex h-9 items-center rounded-md bg-slate-700 px-3 text-sm hover:bg-slate-600"
            >
              <RotateCcw className="mr-2 h-4 w-4" />
              Refresh
            </button>
          </div>
        </section>

        <section className="grid grid-cols-1 gap-5 xl:grid-cols-[1fr_420px]">
          <div className="space-y-4 rounded-md border border-slate-800 bg-slate-900 p-4">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Info label="M1" value={selectedBand ? formatFrequency(selectedBand.first.frequency) : 'Not set'} />
              <Info label="M2" value={selectedBand ? formatFrequency(selectedBand.second.frequency) : 'Not set'} />
              <Info label="Center" value={activeBand ? formatFrequency(activeBand.center) : 'Not set'} />
              <Info label="Bandwidth" value={activeBand ? formatFrequency(activeBand.bandwidth) : 'Not set'} />
            </div>

            <div className="rounded-md border border-slate-800 bg-slate-950 p-4 text-sm text-slate-300">
              <div className="text-xs uppercase text-slate-500">Current Capture Source</div>
              <div className="mt-2 flex flex-wrap items-center gap-3">
                <span className="rounded-full border border-cyan-700/60 bg-cyan-500/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.14em] text-cyan-100">
                  {activeBandSourceLabel}
                </span>
                <span className="text-xs text-slate-400">
                  {captureBandMode === 'markers'
                    ? 'La captura usará exactamente M1 y M2.'
                    : 'La captura usará la ventana custom actual, aunque existan markers visibles.'}
                </span>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
              <Info label="Live peak" value={liveBandQuality ? formatPowerLevel(liveBandQuality.peakLevelDb) : 'Not available'} />
              <Info label="Noise floor" value={liveBandQuality ? formatPowerLevel(liveBandQuality.noiseFloorDb) : 'Not available'} />
              <Info label="Live SNR" value={liveBandQuality ? `${liveBandQuality.snrDb.toFixed(1)} dB` : 'Not available'} />
              <Info label="Peak freq" value={liveBandQuality ? formatFrequency(liveBandQuality.peakFrequencyHz) : 'Not available'} />
            </div>

            {liveCenteringAssessment && (
              <div
                className={cn(
                  'rounded-2xl border p-4 text-sm',
                  liveCenteringAssessment.isWarning
                    ? 'border-amber-400/40 bg-amber-500/10 text-amber-100'
                    : 'border-emerald-400/30 bg-emerald-500/10 text-emerald-100',
                )}
              >
                <div className="font-semibold uppercase tracking-[0.18em]">
                  {liveCenteringAssessment.isWarning ? 'Peak Centering Warning' : 'Peak Centering Check'}
                </div>
                <div className="mt-2">
                  Live peak offset relative to capture center: {formatFrequency(liveCenteringAssessment.offsetHz)}.
                </div>
                <div className="mt-1">
                  Warning threshold for this window: {formatFrequency(liveCenteringAssessment.warningThresholdHz)}.
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <span className="text-xs uppercase tracking-[0.18em] opacity-80">Offset risk</span>
                  <span
                    className={cn(
                      'rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.14em]',
                      liveCenteringAssessment.risk === 'valid' && 'border-emerald-300/40 bg-emerald-400/15 text-emerald-100',
                      liveCenteringAssessment.risk === 'doubtful' && 'border-amber-300/40 bg-amber-400/15 text-amber-100',
                      liveCenteringAssessment.risk === 'rejected' && 'border-rose-300/40 bg-rose-400/15 text-rose-100',
                    )}
                  >
                    {liveCenteringAssessment.riskLabel}
                  </span>
                </div>
                <div className="mt-2 text-xs leading-6 opacity-90">
                  {liveCenteringAssessment.isWarning
                    ? 'El pico en vivo está demasiado desplazado dentro de la ventana. La captura puede terminar rechazada por offset extremo. Recomendación: recentra la ventana o estrecha la banda alrededor del pico real antes de capturar.'
                    : 'El pico en vivo está razonablemente centrado dentro de la ventana activa.'}
                </div>
                <div className="mt-1 text-xs leading-6 opacity-90">{liveCenteringAssessment.riskDetail}</div>
                <div className="mt-1 text-xs leading-6 opacity-90">
                  {liveCenteringAssessment.validMarginHz >= 0
                    ? `Margin before leaving VALID: ${formatFrequency(liveCenteringAssessment.validMarginHz)}.`
                    : `Distance above VALID limit: ${formatFrequency(Math.abs(liveCenteringAssessment.validMarginHz))}.`}
                </div>
                <div className="text-xs leading-6 opacity-90">
                  {liveCenteringAssessment.doubtfulMarginHz >= 0
                    ? `Margin before entering REJECTED: ${formatFrequency(liveCenteringAssessment.doubtfulMarginHz)}.`
                    : `Distance above REJECTED limit: ${formatFrequency(Math.abs(liveCenteringAssessment.doubtfulMarginHz))}.`}
                </div>
              </div>
            )}

            <div className="rounded-md border border-slate-800 bg-slate-950 p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-xs uppercase text-slate-500">Capture Frequency Source</div>
                  <div className="mt-1 text-sm text-slate-300">
                    Elige si quieres capturar entre los dos primeros markers o con frecuencias personalizadas.
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={useCurrentMarkersNow}
                    disabled={!selectedBand}
                    className={cn(
                      'rounded-full border px-4 py-2 text-xs font-semibold',
                      !selectedBand
                        ? 'cursor-not-allowed border-slate-800 text-slate-600'
                        : 'border-cyan-700 text-cyan-100 hover:bg-cyan-950/40',
                    )}
                  >
                    Use Current M1-M2 Now
                  </button>
                  <button
                    type="button"
                    onClick={centerOnLivePeak}
                    disabled={!activeBand || !liveBandQuality}
                    className={cn(
                      'rounded-full border px-4 py-2 text-xs font-semibold',
                      !activeBand || !liveBandQuality
                        ? 'cursor-not-allowed border-slate-800 text-slate-600'
                        : 'border-emerald-700 text-emerald-100 hover:bg-emerald-950/40',
                    )}
                  >
                    Center on Live Peak
                  </button>
                  <button
                    type="button"
                    onClick={useAnalyzerWindow}
                    className="rounded-full border border-slate-700 px-4 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-800"
                  >
                    Use Live Monitor Window
                  </button>
                </div>
              </div>
              <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
                <button
                  type="button"
                  onClick={() => {
                    setCaptureBandMode('markers');
                    setBandSourcePinned(false);
                  }}
                  className={cn(
                    'rounded-md border p-3 text-left text-sm transition',
                    captureBandMode === 'markers'
                      ? 'border-cyan-500 bg-cyan-500/10 text-white'
                      : 'border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800',
                  )}
                >
                  <div className="font-semibold uppercase">Markers M1-M2</div>
                  <div className="mt-2 text-xs text-slate-400">Captura exactamente la banda delimitada por los dos primeros markers.</div>
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setCaptureBandMode('custom');
                    setBandSourcePinned(true);
                  }}
                  className={cn(
                    'rounded-md border p-3 text-left text-sm transition',
                    captureBandMode === 'custom'
                      ? 'border-cyan-500 bg-cyan-500/10 text-white'
                      : 'border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800',
                  )}
                >
                  <div className="font-semibold uppercase">Custom Frequencies</div>
                  <div className="mt-2 text-xs text-slate-400">Define center y bandwidth o start y stop. El otro par se recalcula automáticamente.</div>
                </button>
              </div>

              {captureBandMode === 'custom' && (
                <div className="mt-4 space-y-4">
                  <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
                    <label className="flex flex-col gap-1 text-xs text-slate-400">
                      Center MHz
                      <input value={customCenterMHz} onChange={(event) => updateFromCenterBandwidth(event.target.value, customBandwidthMHz)} className={inputClass} />
                    </label>
                    <label className="flex flex-col gap-1 text-xs text-slate-400">
                      Bandwidth MHz
                      <input value={customBandwidthMHz} onChange={(event) => updateFromCenterBandwidth(customCenterMHz, event.target.value)} className={inputClass} />
                    </label>
                    <Info label="Derived start" value={customBand ? formatFrequency(customBand.start) : 'Invalid'} />
                    <Info label="Derived stop" value={customBand ? formatFrequency(customBand.stop) : 'Invalid'} />
                  </div>

                  <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
                  <label className="flex flex-col gap-1 text-xs text-slate-400">
                    Start MHz
                    <input value={customStartMHz} onChange={(event) => updateFromStartStop(event.target.value, customStopMHz)} className={inputClass} />
                  </label>
                  <label className="flex flex-col gap-1 text-xs text-slate-400">
                    Stop MHz
                    <input value={customStopMHz} onChange={(event) => updateFromStartStop(customStartMHz, event.target.value)} className={inputClass} />
                  </label>
                  <Info label="Derived center" value={customBand ? formatFrequency(customBand.center) : 'Invalid'} />
                  <Info label="Derived bandwidth" value={customBand ? formatFrequency(customBand.bandwidth) : 'Invalid'} />
                </div>
                </div>
              )}

              {captureValidationMessage && (
                <div className="mt-4 rounded-2xl border border-amber-400/40 bg-amber-500/10 p-4 text-sm text-amber-100">
                  {captureValidationMessage}
                </div>
              )}
            </div>

            <div className="rounded-md border border-slate-800 bg-slate-950 p-4">
              <div className="text-xs uppercase text-slate-500">Capture Mode</div>
              <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
                <button
                  type="button"
                  onClick={() => setCaptureMode('immediate')}
                  className={cn(
                    'rounded-md border p-3 text-left text-sm transition',
                    captureMode === 'immediate'
                      ? 'border-emerald-500 bg-emerald-500/10 text-white'
                      : 'border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800',
                  )}
                >
                  <div className="font-semibold uppercase">Immediate</div>
                  <div className="mt-2 text-xs text-slate-400">Graba inmediatamente toda la ventana temporal pedida.</div>
                </button>
                <button
                  type="button"
                  onClick={() => setCaptureMode('triggered_burst')}
                  className={cn(
                    'rounded-md border p-3 text-left text-sm transition',
                    captureMode === 'triggered_burst'
                      ? 'border-emerald-500 bg-emerald-500/10 text-white'
                      : 'border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800',
                  )}
                >
                  <div className="font-semibold uppercase">Triggered Burst</div>
                  <div className="mt-2 text-xs text-slate-400">Espera actividad y recorta automáticamente el IQ alrededor del primer burst detectado.</div>
                </button>
              </div>

              {captureMode === 'triggered_burst' && (
                <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-4">
                  <label className="flex flex-col gap-1 text-xs text-slate-400">
                    Threshold dB
                    <input value={triggerThresholdDb} onChange={(event) => setTriggerThresholdDb(event.target.value)} className={inputClass} />
                  </label>
                  <label className="flex flex-col gap-1 text-xs text-slate-400">
                    Pre-trigger ms
                    <input value={preTriggerMs} onChange={(event) => setPreTriggerMs(event.target.value)} className={inputClass} />
                  </label>
                  <label className="flex flex-col gap-1 text-xs text-slate-400">
                    Post-trigger ms
                    <input value={postTriggerMs} onChange={(event) => setPostTriggerMs(event.target.value)} className={inputClass} />
                  </label>
                  <label className="flex flex-col gap-1 text-xs text-slate-400">
                    Max wait s
                    <input value={triggerMaxWaitSeconds} onChange={(event) => setTriggerMaxWaitSeconds(event.target.value)} className={inputClass} />
                  </label>
                </div>
              )}
            </div>

            <div className="rounded-md border border-slate-800 bg-slate-950 p-4">
              <div className="text-xs uppercase text-slate-500">Capture Purpose</div>
              <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-3">
                {(['train', 'val', 'predict'] as const).map((split) => (
                  <button
                    key={split}
                    type="button"
                    onClick={() => setDatasetSplit(split)}
                    className={cn(
                      'rounded-md border p-3 text-left text-sm transition',
                      datasetSplit === split
                        ? 'border-emerald-500 bg-emerald-500/10 text-white'
                        : 'border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800',
                    )}
                  >
                    <div className="font-semibold uppercase">{split}</div>
                    <div className="mt-2 text-xs text-slate-400">{splitHelp[split]}</div>
                  </button>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              <label className="flex flex-col gap-1 text-xs text-slate-400">
                Label
                <input value={label} onChange={(event) => setLabel(event.target.value)} className={inputClass} />
              </label>
              <label className="flex flex-col gap-1 text-xs text-slate-400">
                Transmitter ID
                <input value={transmitterId} onChange={(event) => setTransmitterId(event.target.value)} className={inputClass} />
              </label>
              <label className="flex flex-col gap-1 text-xs text-slate-400">
                Transmitter class
                <input value={transmitterClass} onChange={(event) => setTransmitterClass(event.target.value)} className={inputClass} />
              </label>
              <label className="flex flex-col gap-1 text-xs text-slate-400">
                Session ID
                <input value={sessionId} onChange={(event) => setSessionId(event.target.value)} className={inputClass} />
              </label>
              <label className="flex flex-col gap-1 text-xs text-slate-400">
                Operator
                <input value={operator} onChange={(event) => setOperator(event.target.value)} className={inputClass} />
              </label>
              <label className="flex flex-col gap-1 text-xs text-slate-400">
                Environment
                <input value={environment} onChange={(event) => setEnvironment(event.target.value)} className={inputClass} />
              </label>
            </div>

            <div className="grid grid-cols-1 gap-3 md:grid-cols-5">
              <label className="flex flex-col gap-1 text-xs text-slate-400">
                Modulation hint
                <select value={modulationHint} onChange={(event) => setModulationHint(event.target.value)} className={inputClass}>
                  {MODULATION_HINTS.map((item) => (
                    <option key={item.value} value={item.value}>{item.label}</option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-xs text-slate-400">
                Duration s
                <input value={durationSeconds} onChange={(event) => setDurationSeconds(event.target.value)} className={inputClass} />
              </label>
              <label className="flex flex-col gap-1 text-xs text-slate-400">
                File format
                <select value={fileFormat} onChange={(event) => setFileFormat(event.target.value as 'cfile' | 'iq')} className={inputClass}>
                  <option value="cfile">CFILE</option>
                  <option value="iq">IQ</option>
                </select>
              </label>
              <label className="flex items-end gap-2 text-xs text-slate-400">
                <input type="checkbox" checked={autoImport} onChange={(event) => setAutoImport(event.target.checked)} />
                Auto-import to fingerprinting
              </label>
              <button
                onClick={captureSignal}
                disabled={isCapturing || !activeBand}
                className={cn(
                  'inline-flex h-9 items-center justify-center self-end rounded-md px-4 text-sm font-semibold',
                  isCapturing || !activeBand || Boolean(captureValidationMessage)
                    ? 'cursor-not-allowed bg-slate-700 text-slate-400'
                    : 'bg-emerald-600 text-white hover:bg-emerald-500',
                )}
              >
                <Play className="mr-2 h-4 w-4" />
                {isCapturing ? 'Capturing...' : `Capture ${fileFormat.toUpperCase()}`}
              </button>
            </div>

            <label className="flex flex-col gap-1 text-xs text-slate-400">
              Notes
              <textarea
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
                rows={3}
                placeholder="Device state, distance, scenario, antenna setup, or dataset notes"
                className="rounded-md border border-slate-700 bg-slate-950 px-2 py-2 text-sm text-slate-100 outline-none focus:border-blue-400"
              />
            </label>

            {error && <div className="text-sm text-red-300">{error}</div>}
            {success && <div className="text-sm text-emerald-300">{success}</div>}
          </div>

          <div className="rounded-md border border-slate-800 bg-slate-900 p-4">
            <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
              <ShieldCheck className="h-4 w-4" />
              What this capture now does
            </h3>
            <div className="space-y-2 text-sm text-slate-300">
              <p>1. Captura IQ real del USRP entre M1 y M2 o con frecuencias personalizadas.</p>
              <p>2. Guarda metadata con split experimental: train, val o predict.</p>
              <p>3. Si activas auto-import, registra la captura en el flujo de fingerprinting.</p>
              <p>4. Ese registro luego aparece en `Dataset Builder` y se detecta automáticamente en `Training`, `Validation`, `Inference` o `Retraining` según el split.</p>
              <p>5. El banner central informa de conexión o captura sin bloquear la navegación entre pestañas.</p>
              <p>6. Esta pantalla avisa antes de lanzar configuraciones demasiado anchas para el flujo de captura científica.</p>
              <p>7. La estimación SNR en vivo del marker-band se guarda también en la metadata de la captura para trazabilidad operativa.</p>
            </div>
          </div>
        </section>

        <section className="overflow-hidden rounded-md border border-slate-800 bg-slate-900">
          <div className="flex items-center gap-2 border-b border-slate-800 px-4 py-3">
            <Database className="h-4 w-4" />
            <h3 className="text-sm font-semibold">Generated RF Captures</h3>
          </div>
          <div className="divide-y divide-slate-800">
            {captures.length === 0 ? (
              <div className="p-4 text-sm text-slate-500">No RF captures found.</div>
            ) : captures.map((capture) => (
              <CaptureRow key={capture.id} capture={capture} />
            ))}
          </div>
        </section>
      </div>
    </div>
  );
};

const inputClass =
  'h-9 rounded-md border border-slate-700 bg-slate-950 px-2 text-sm text-slate-100 outline-none focus:border-blue-400';

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950 p-3">
      <div className="text-xs uppercase text-slate-500">{label}</div>
      <div className="text-sm font-semibold text-slate-100">{value}</div>
    </div>
  );
}

function CaptureRow({ capture }: { capture: ModulatedSignalCapture }) {
  const iqUrl = apiService.getModulatedSignalIqUrl(capture.id);
  const metadataUrl = apiService.getModulatedSignalMetadataUrl(capture.id);
  const fileFormat = (capture.file_format || (capture.iq_file?.toLowerCase().endsWith('.iq') ? 'iq' : 'cfile')).toUpperCase();
  const shaPreview = capture.sha256 ? `${capture.sha256.slice(0, 16)}...` : 'n/a';
  const gainLabel = Number.isFinite(capture.gain_db) ? `${capture.gain_db.toFixed(1)} dB` : 'n/a';
  const capturedDurationLabel = Number.isFinite(capture.trigger_capture?.captured_duration_s)
    ? `${capture.trigger_capture?.captured_duration_s?.toFixed(3)} s`
    : Number.isFinite(capture.duration_seconds)
      ? `${capture.duration_seconds.toFixed(3)} s`
      : 'n/a';
  return (
    <div className="space-y-3 p-4">
      <div className="flex flex-wrap justify-between gap-3">
        <div>
          <div className="text-sm font-semibold">
            {capture.label || capture.id} | {fileFormat} | {formatFrequency(capture.center_frequency_hz)} | BW {formatFrequency(capture.bandwidth_hz)}
          </div>
          <div className="text-xs text-slate-400">
            {(capture.dataset_split || 'train')} | {capture.session_id || 'no_session'} | {capture.modulation_hint || 'unknown'} | {capture.duration_seconds}s | {formatFrequency(capture.sample_rate_hz)}/s | {formatBytes(capture.file_size_bytes)}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <a href={iqUrl} className="inline-flex h-9 items-center rounded-md bg-blue-600 px-3 text-sm font-medium hover:bg-blue-500">
            <Download className="mr-2 h-4 w-4" />
            {fileFormat}
          </a>
          <a href={metadataUrl} className="inline-flex h-9 items-center rounded-md bg-slate-700 px-3 text-sm font-medium hover:bg-slate-600">
            <Download className="mr-2 h-4 w-4" />
            JSON
          </a>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-2 text-xs text-slate-400 md:grid-cols-3">
        <div>Start: {formatFrequency(capture.start_frequency_hz)}</div>
        <div>Stop: {formatFrequency(capture.stop_frequency_hz)}</div>
        <div>Gain: {gainLabel}</div>
        <div>Antenna: {capture.antenna || 'unknown'}</div>
        <div>Tx ID: {capture.transmitter_id || 'unknown'}</div>
        <div>Class: {capture.transmitter_class || 'unknown'}</div>
        <div>Operator: {capture.operator || 'unknown'}</div>
        <div>Environment: {capture.environment || 'unknown'}</div>
        <div>SHA256: {shaPreview}</div>
        <div>Live preview SNR: {capture.preview_metrics?.live_preview_snr_db?.toFixed(1) ?? 'n/a'} dB</div>
        <div>Live preview noise: {capture.preview_metrics?.live_preview_noise_floor_db !== undefined ? formatPowerLevel(capture.preview_metrics.live_preview_noise_floor_db) : 'n/a'}</div>
        <div>Live preview peak: {capture.preview_metrics?.live_preview_peak_level_db !== undefined ? formatPowerLevel(capture.preview_metrics.live_preview_peak_level_db) : 'n/a'}</div>
        <div>Capture mode: {capture.trigger_capture?.mode || 'immediate'}</div>
        <div>Trigger detected: {capture.trigger_capture?.trigger_detected === undefined ? 'n/a' : String(capture.trigger_capture.trigger_detected)}</div>
        <div>Captured duration: {capturedDurationLabel}</div>
      </div>

      {capture.notes && <div className="text-sm text-slate-300">{capture.notes}</div>}
    </div>
  );
}
