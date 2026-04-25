import React, { useEffect, useMemo, useState } from 'react';
import { ApiService } from '../../app/services/ApiService';
import { FingerprintingCaptureRecord } from '../../shared/types';

const api = new ApiService();

const reviewTemplate = {
  operator_decision: 'valid',
  review_notes: 'Accepted after manual review.',
  export_windows: ['transient_start', 'whole_burst'],
};

const formatTimestamp = (value?: string) => {
  if (!value) return 'not available';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
};

const formatHz = (value?: number | null) => {
  if (value === null || value === undefined || !Number.isFinite(value)) return 'not available';
  const absolute = Math.abs(value);
  if (absolute >= 1e9) return `${(value / 1e9).toFixed(6)} GHz`;
  if (absolute >= 1e6) return `${(value / 1e6).toFixed(6)} MHz`;
  if (absolute >= 1e3) return `${(value / 1e3).toFixed(3)} kHz`;
  return `${value.toFixed(2)} Hz`;
};

export const DatasetBuilderView: React.FC = () => {
  const [captures, setCaptures] = useState<FingerprintingCaptureRecord[]>([]);
  const [selectedCaptureId, setSelectedCaptureId] = useState<string>('');
  const [splitFilter, setSplitFilter] = useState<'all' | 'train' | 'val' | 'predict'>('all');
  const [statusFilter, setStatusFilter] = useState<'all' | 'valid' | 'doubtful' | 'rejected'>('all');
  const [lastRefresh, setLastRefresh] = useState<string>('');
  const [isRecomputingQc, setIsRecomputingQc] = useState(false);
  const [isDeletingCapture, setIsDeletingCapture] = useState(false);
  const [actionMessage, setActionMessage] = useState<string>('');

  const refresh = async () => {
    const data = await api.getFingerprintingCaptures();
    setCaptures(data);
    setLastRefresh(new Date().toISOString());
    if (!selectedCaptureId && data.length > 0) {
      setSelectedCaptureId(data[0].capture_id);
    }
  };

  useEffect(() => {
    refresh().catch((error) => console.error('Failed to load dataset builder data', error));
  }, []);

  const filteredCaptures = useMemo(() => {
    return captures.filter((capture) => {
      const splitOk = splitFilter === 'all' || capture.dataset_split === splitFilter;
      const statusOk = statusFilter === 'all' || capture.quality_review.status === statusFilter;
      return splitOk && statusOk;
    });
  }, [captures, splitFilter, statusFilter]);

  const selectedCapture =
    filteredCaptures.find((item) => item.capture_id === selectedCaptureId) ??
    captures.find((item) => item.capture_id === selectedCaptureId) ??
    filteredCaptures[0] ??
    captures[0];

  const reviewCapture = async (status: 'valid' | 'doubtful' | 'rejected') => {
    if (!selectedCapture) {
      return;
    }
    await api.reviewFingerprintingCapture(selectedCapture.capture_id, {
      ...reviewTemplate,
      operator_decision: status,
      review_notes:
        status === 'valid'
          ? 'Accepted for dataset export.'
          : status === 'doubtful'
            ? 'Borderline quality; retain for manual comparison only.'
            : 'Rejected due to quality or labeling issues.',
    });
    await refresh();
  };

  const recomputeQc = async () => {
    if (!selectedCapture) return;
    setIsRecomputingQc(true);
    setActionMessage('');
    try {
      const updated = await api.recomputeFingerprintingCaptureQc(selectedCapture.capture_id);
      setActionMessage(`QC recomputed for ${updated.capture_id}. New status: ${updated.quality_review.status}.`);
      await refresh();
      setSelectedCaptureId(updated.capture_id);
    } catch (error) {
      console.error('Failed to recompute capture QC', error);
      setActionMessage('Failed to recompute QC for this capture.');
    } finally {
      setIsRecomputingQc(false);
    }
  };

  const deleteCapture = async () => {
    if (!selectedCapture) return;
    const confirmed = window.confirm(
      `Delete capture ${selectedCapture.capture_id} (${selectedCapture.transmitter.transmitter_label}) from Dataset Builder?`,
    );
    if (!confirmed) return;
    setIsDeletingCapture(true);
    setActionMessage('');
    try {
      const result = await api.deleteFingerprintingCapture(selectedCapture.capture_id, { delete_artifacts: true });
      setActionMessage(
        result.deleted_artifacts.length > 0
          ? `Capture ${result.capture_id} deleted. Removed ${result.deleted_artifacts.length} linked artifact(s).`
          : `Capture ${result.capture_id} deleted from the fingerprinting registry.`,
      );
      const deletedId = selectedCapture.capture_id;
      await refresh();
      setSelectedCaptureId((current) => (current === deletedId ? '' : current));
    } catch (error) {
      console.error('Failed to delete capture', error);
      setActionMessage('Failed to delete this capture from Dataset Builder.');
    } finally {
      setIsDeletingCapture(false);
    }
  };

  return (
    <div className="min-h-full bg-[linear-gradient(180deg,_#fffef8,_#f5f7fb)] p-6">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="text-sm font-semibold uppercase tracking-[0.2em] text-amber-700">Dataset Builder</div>
          <h1 className="mt-2 font-serif text-4xl text-slate-900">Curación manual y calidad antes de entrenar</h1>
          <p className="mt-3 max-w-4xl text-sm leading-7 text-slate-600">
            Esta pestaña no captura señal. Esta pestaña decide qué capturas pasan a ser dataset serio. Aquí revisas calidad,
            separas `train`, `val` y `predict`, y aceptas o rechazas cada adquisición antes de contaminar el pipeline.
          </p>
          <p className="mt-2 max-w-4xl text-sm leading-7 text-slate-500">
            Último refresco UI: {formatTimestamp(lastRefresh)}. Fuente: registro fingerprinting del backend.
          </p>
        </div>
        <div className="grid grid-cols-3 gap-3 text-center">
          <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3">
            <div className="text-2xl font-semibold text-slate-900">{captures.length}</div>
            <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Total</div>
          </div>
          <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3">
            <div className="text-2xl font-semibold text-emerald-700">
              {captures.filter((capture) => capture.quality_review.status === 'valid').length}
            </div>
            <div className="text-xs uppercase tracking-[0.18em] text-emerald-700">Valid</div>
          </div>
          <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3">
            <div className="text-2xl font-semibold text-rose-700">
              {captures.filter((capture) => capture.quality_review.status === 'rejected').length}
            </div>
            <div className="text-xs uppercase tracking-[0.18em] text-rose-700">Rejected</div>
          </div>
        </div>
      </div>

      <div className="mb-5 grid gap-4 lg:grid-cols-3">
        <div className="rounded-2xl border border-slate-200 bg-white p-4">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">What It Does</div>
          <div className="mt-3 text-sm leading-6 text-slate-700">
            Revisa trazabilidad, calidad, burst extraction y destino experimental antes de exportar un registro al dataset usable.
          </div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-4">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Accept</div>
          <div className="mt-3 text-sm leading-6 text-slate-700">
            Marca la captura como válida para el split ya definido. No cambia `train`, `val` o `predict`; valida su calidad.
          </div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-4">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Reject / Doubtful</div>
          <div className="mt-3 text-sm leading-6 text-slate-700">
            Evita que una muestra mal etiquetada, duplicada o degradada entre en entrenamiento, validación o predicción.
          </div>
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-[0.95fr_1.05fr]">
        <section className="rounded-[1.75rem] border border-slate-200 bg-white/90 p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
          <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
            <div className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-500">Capture inventory</div>
            <button className="rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700" onClick={() => refresh()}>
              Refresh
            </button>
          </div>

          <div className="mb-4 grid gap-3 md:grid-cols-2">
            <label>
              <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Split filter</div>
              <select
                className="mt-2 w-full rounded-2xl border border-slate-300 bg-slate-50 px-3 py-2 text-sm"
                value={splitFilter}
                onChange={(event) => setSplitFilter(event.target.value as typeof splitFilter)}
              >
                <option value="all">all</option>
                <option value="train">train</option>
                <option value="val">val</option>
                <option value="predict">predict</option>
              </select>
            </label>
            <label>
              <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Status filter</div>
              <select
                className="mt-2 w-full rounded-2xl border border-slate-300 bg-slate-50 px-3 py-2 text-sm"
                value={statusFilter}
                onChange={(event) => setStatusFilter(event.target.value as typeof statusFilter)}
              >
                <option value="all">all</option>
                <option value="valid">valid</option>
                <option value="doubtful">doubtful</option>
                <option value="rejected">rejected</option>
              </select>
            </label>
          </div>

          <div className="mb-4 text-xs text-slate-500">
            Showing {filteredCaptures.length} of {captures.length} captures.
          </div>

          <div className="space-y-3">
            {filteredCaptures.map((capture) => (
              <button
                key={capture.capture_id}
                onClick={() => setSelectedCaptureId(capture.capture_id)}
                className={`w-full rounded-2xl border p-4 text-left transition ${
                  capture.capture_id === selectedCapture?.capture_id
                    ? 'border-slate-900 bg-slate-950 text-white'
                    : 'border-slate-200 bg-slate-50 text-slate-900 hover:bg-slate-100'
                }`}
              >
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="font-semibold">{capture.transmitter.transmitter_id}</div>
                    <div className="mt-1 text-xs opacity-75">
                      {capture.session_id} · {capture.capture_config.file_format} · {capture.dataset_split}
                    </div>
                    <div className="mt-1 text-xs opacity-75">
                      Captured: {formatTimestamp(capture.created_at_utc)}
                    </div>
                  </div>
                  <div className="text-xs uppercase tracking-[0.18em]">{capture.quality_review.status}</div>
                </div>
              </button>
            ))}
            {filteredCaptures.length === 0 && (
              <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-500">
                No captures match the current filters.
              </div>
            )}
          </div>
        </section>

        <section className="rounded-[1.75rem] border border-slate-200 bg-white/90 p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
          {selectedCapture ? (
            <>
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <div className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-500">Capture summary</div>
                  <h2 className="mt-2 text-2xl font-semibold text-slate-900">{selectedCapture.transmitter.transmitter_label}</h2>
                  <div className="mt-2 text-sm text-slate-600">
                    {selectedCapture.transmitter.transmitter_class} · {selectedCapture.scenario.environment} · session {selectedCapture.scenario.session_number}
                  </div>
                </div>
                <div className="flex gap-2">
                  <button
                    className="rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
                    onClick={() => recomputeQc()}
                    disabled={isRecomputingQc}
                  >
                    {isRecomputingQc ? 'Recomputing QC...' : 'Recompute QC'}
                  </button>
                  <button className="rounded-full bg-emerald-600 px-4 py-2 text-sm font-semibold text-white" onClick={() => reviewCapture('valid')}>
                    Accept
                  </button>
                  <button className="rounded-full bg-amber-500 px-4 py-2 text-sm font-semibold text-white" onClick={() => reviewCapture('doubtful')}>
                    Doubtful
                  </button>
                  <button className="rounded-full bg-rose-600 px-4 py-2 text-sm font-semibold text-white" onClick={() => reviewCapture('rejected')}>
                    Reject
                  </button>
                  <button
                    className="rounded-full border border-rose-300 bg-white px-4 py-2 text-sm font-semibold text-rose-700 disabled:cursor-not-allowed disabled:opacity-50"
                    onClick={() => deleteCapture()}
                    disabled={isDeletingCapture}
                  >
                    {isDeletingCapture ? 'Deleting...' : 'Delete'}
                  </button>
                </div>
              </div>

              {actionMessage && (
                <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
                  {actionMessage}
                </div>
              )}

              <div className="mt-4 grid gap-3 md:grid-cols-2">
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
                  <div>Created: {formatTimestamp(selectedCapture.created_at_utc)}</div>
                  <div className="mt-2">Record updated: {formatTimestamp(selectedCapture.updated_at_utc)}</div>
                  <div className="mt-2">Scenario timestamp: {formatTimestamp(selectedCapture.scenario.timestamp_utc)}</div>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
                  <div>Split: {selectedCapture.dataset_split}</div>
                  <div className="mt-2">Dataset destination: {selectedCapture.capture_config.dataset_destination}</div>
                  <div className="mt-2">Review status: {selectedCapture.quality_review.status}</div>
                </div>
              </div>

              <div className="mt-6 grid gap-4 md:grid-cols-2">
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Capture configuration</div>
                  <div className="mt-3 space-y-2 text-sm text-slate-700">
                    <div>Center frequency: {formatHz(selectedCapture.capture_config.center_frequency_hz)}</div>
                    <div>Sample rate: {formatHz(selectedCapture.capture_config.sample_rate_hz)}</div>
                    <div>Effective bandwidth: {formatHz(selectedCapture.capture_config.effective_bandwidth_hz)}</div>
                    <div>Gain: {String((selectedCapture.capture_config.gain_settings?.['composite_gain_db'] ?? 'not available'))} dB</div>
                    <div>Antenna: {selectedCapture.capture_config.antenna_port || 'not available'}</div>
                    <div>Format: {selectedCapture.capture_config.file_format}</div>
                  </div>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Quality metrics</div>
                  <div className="mt-3 space-y-2 text-sm text-slate-700">
                    <div>SNR estimado: {selectedCapture.quality_metrics.estimated_snr_db ?? 0} dB</div>
                    <div>SNR espectral: {selectedCapture.quality_metrics.spectral_snr_db ?? 'not available'} dB</div>
                    <div>Offset de frecuencia: {selectedCapture.quality_metrics.frequency_offset_hz ?? 0} Hz</div>
                    <div>Occupied bandwidth: {selectedCapture.quality_metrics.occupied_bandwidth_hz ?? 0} Hz</div>
                    <div>Clipping: {selectedCapture.quality_metrics.clipping_pct ?? 0}%</div>
                    <div>Silence: {selectedCapture.quality_metrics.silence_pct ?? 0}%</div>
                  </div>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Burst extraction</div>
                  <div className="mt-3 space-y-2 text-sm text-slate-700">
                    <div>Method: {selectedCapture.burst_detection.method}</div>
                    <div>Pre-trigger: {selectedCapture.burst_detection.pre_trigger_samples}</div>
                    <div>Post-trigger: {selectedCapture.burst_detection.post_trigger_samples}</div>
                    <div>ROI: {selectedCapture.burst_detection.regions_of_interest.join(', ') || 'none'}</div>
                    <div>Export windows: {(selectedCapture.quality_review.export_windows ?? []).join(', ') || 'not reviewed'}</div>
                  </div>
                </div>
              </div>

              <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4">
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Capture-time live preview</div>
                <div className="mt-3 space-y-2 text-sm text-slate-700">
                  <div>Live SNR: {selectedCapture.preview_metrics?.live_preview_snr_db ?? 'not available'} dB</div>
                  <div>Live noise floor: {selectedCapture.preview_metrics?.live_preview_noise_floor_db ?? 'not available'} dB</div>
                  <div>Live peak: {selectedCapture.preview_metrics?.live_preview_peak_level_db ?? 'not available'} dB</div>
                  <div>Live peak frequency: {formatHz(selectedCapture.preview_metrics?.live_preview_peak_frequency_hz)}</div>
                </div>
                <div className="mt-3 text-xs leading-6 text-slate-500">
                  Este bloque muestra lo que veía el operador justo antes de capturar. No sustituye el QC offline calculado sobre el archivo IQ guardado.
                </div>
              </div>

              <div className="mt-4 rounded-2xl border border-slate-200 bg-white p-4">
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Automatic review flags</div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {(selectedCapture.quality_review.quality_flags ?? []).map((flag) => (
                    <span key={flag} className="rounded-full border border-slate-300 bg-slate-50 px-3 py-1 text-xs text-slate-700">
                      {flag}
                    </span>
                  ))}
                  {(selectedCapture.quality_review.quality_flags ?? []).length === 0 && (
                    <span className="text-sm text-slate-500">No automatic flags raised.</span>
                  )}
                </div>
                <div className="mt-4 text-sm text-slate-700">
                  IQ path: <span className="font-mono text-xs">{selectedCapture.artifacts.iq_file || selectedCapture.capture_config.output_path || 'not linked'}</span>
                </div>
                <div className="mt-2 text-sm text-slate-700">
                  SHA-256: <span className="font-mono text-xs">{selectedCapture.artifacts.sha256 || 'pending'}</span>
                </div>
              </div>
            </>
          ) : (
            <div className="text-sm text-slate-500">No fingerprinting captures available yet.</div>
          )}
        </section>
      </div>
    </div>
  );
};
