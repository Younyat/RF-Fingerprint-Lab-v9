import React, { useEffect, useMemo, useState } from 'react';
import { Beaker, BrainCircuit, FileInput, GitCompare, Microscope, Network, RadioTower, RefreshCw, Save, ScanSearch, Waves } from 'lucide-react';
import { ApiService } from '../../app/services/ApiService';
import type { RFSignalUnderstandingComparison, RFSignalUnderstandingResult } from '../../shared/types';
import { formatFrequency } from '../../shared/utils';

const apiService = new ApiService();

const techniqueRows = [
  ['STFT waterfall generation', 'A Radio Frequency Signal Recognition Method Based on Spectrogram'],
  ['SSD waterfall detection', 'RF Fingerprint Recognition Based on Spectrum Waterfall Diagram'],
  ['MLP over spectrogram rows', 'Simple Detection and Classification of Spectrogram RF Signals Using a Four-Layer Perceptron'],
  ['Bispectrum-waterfall fusion', 'Bispectrum-Based Signal Processing Using Waterfall Features'],
];

export const RFSignalUnderstandingView: React.FC = () => {
  const [filePath, setFilePath] = useState('');
  const [sampleRateHz, setSampleRateHz] = useState(2_000_000);
  const [centerFrequencyHz, setCenterFrequencyHz] = useState(433_920_000);
  const [result, setResult] = useState<RFSignalUnderstandingResult | null>(null);
  const [comparison, setComparison] = useState<RFSignalUnderstandingComparison | null>(null);
  const [references, setReferences] = useState<Record<string, any> | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const firstRegion = result?.regions?.[0] ?? null;
  const finalDecision = firstRegion?.final_decision ?? null;
  const spectral = firstRegion?.features?.spectral ?? {};
  const bispectral = firstRegion?.features?.bispectral ?? {};

  const payload = useMemo(() => ({
    file_path: filePath,
    sample_rate_hz: sampleRateHz,
    center_frequency_hz: centerFrequencyHz,
    format: 'complex64',
    n_fft: 1024,
    hop_length: 256,
    window: 'hann',
  }), [filePath, sampleRateHz, centerFrequencyHz]);

  useEffect(() => {
    apiService.getRFSignalUnderstandingReferences().then(setReferences).catch(() => setReferences(null));
  }, []);

  const refreshLive = async () => {
    try {
      setLoading(true);
      setError(null);
      const next = await apiService.getLiveRFSignalUnderstanding();
      setResult(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Live RF Signal Understanding failed');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refreshLive();
  }, []);

  useEffect(() => {
    if (!autoRefresh) return;
    const timer = window.setInterval(refreshLive, 1500);
    return () => window.clearInterval(timer);
  }, [autoRefresh]);

  const runAnalyze = async () => {
    try {
      setLoading(true);
      setError(null);
      const next = await apiService.analyzeRFSignalUnderstanding(payload);
      setResult(next);
      setComparison(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'RF Signal Understanding analysis failed');
    } finally {
      setLoading(false);
    }
  };

  const runCompare = async () => {
    try {
      setLoading(true);
      setError(null);
      const next = filePath ? await apiService.compareRFSignalUnderstanding(payload) : await apiService.compareLiveRFSignalUnderstanding();
      setComparison(next);
      if (next.live_result) {
        setResult(next.live_result as RFSignalUnderstandingResult);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Legacy comparison failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-full bg-[var(--app-bg)] p-6 text-[var(--app-text)]">
      <div className="mb-6 flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.18em] text-cyan-500">
            <ScanSearch className="h-4 w-4" />
            Waterfall Evidence Pipeline
          </div>
          <h1 className="text-2xl font-semibold">RF Signal Understanding</h1>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={() => setAutoRefresh((value) => !value)} className="inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm" style={{ borderColor: 'var(--app-border)', background: autoRefresh ? 'var(--app-accent)' : 'var(--app-surface-strong)', color: autoRefresh ? 'var(--app-accent-foreground)' : 'var(--app-text)' }}>
            <RefreshCw className={`h-4 w-4 ${loading && autoRefresh ? 'animate-spin' : ''}`} />
            {autoRefresh ? 'Live on' : 'Live off'}
          </button>
          <button type="button" onClick={refreshLive} disabled={loading} className="inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm disabled:opacity-50" style={{ borderColor: 'var(--app-border)', background: 'var(--app-surface-strong)' }}>
            <RadioTower className="h-4 w-4" />
            Refresh live
          </button>
          <button type="button" onClick={runAnalyze} disabled={loading || !filePath} className="inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm disabled:opacity-50" style={{ borderColor: 'var(--app-border)', background: 'var(--app-surface-strong)' }}>
            <Microscope className="h-4 w-4" />
            Analyze file
          </button>
          <button type="button" onClick={runCompare} disabled={loading} className="inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm disabled:opacity-50" style={{ borderColor: 'var(--app-border)', background: 'var(--app-accent)', color: 'var(--app-accent-foreground)' }}>
            <GitCompare className="h-4 w-4" />
            Compare legacy
          </button>
        </div>
      </div>

      {error && <div className="mb-4 rounded-md border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-500">{error}</div>}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Panel title="Live input" icon={<FileInput className="h-4 w-4" />}>
          <Metric label="Mode" value={(result?.mode as string) ?? 'live'} />
          <Metric label="Source" value={(result?.source as string) ?? 'real_sdr'} />
          <label className="mt-3 block text-xs uppercase text-[var(--app-text-muted)]">Optional I/Q or cfile path</label>
          <input value={filePath} onChange={(event) => setFilePath(event.target.value)} className="mt-2 w-full rounded-md border bg-transparent px-3 py-2 text-sm" style={{ borderColor: 'var(--app-border)' }} placeholder="C:\captures\capture_001.iq" />
          <div className="mt-3 grid grid-cols-2 gap-3">
            <NumberInput label="Sample rate Hz" value={sampleRateHz} onChange={setSampleRateHz} />
            <NumberInput label="Center Hz" value={centerFrequencyHz} onChange={setCenterFrequencyHz} />
          </div>
        </Panel>

        <Panel title="Live waterfall from SDR" icon={<Waves className="h-4 w-4" />}>
          <Metric label="Analysis" value={result?.analysis_id ?? 'not run'} />
          <Metric label="Rows" value={`${result?.waterfall.rows ?? result?.waterfall.n_fft ?? 0}`} />
          <Metric label="Bins" value={`${result?.waterfall.freq_bins ?? result?.waterfall.hop_length ?? 0}`} />
        </Panel>

        <Panel title="Detected time-frequency regions" icon={<Network className="h-4 w-4" />}>
          <Metric label="Regions" value={`${result?.regions?.length ?? 0}`} />
          <Metric label="First center" value={firstRegion ? formatFrequency(Number(firstRegion.freq_start_hz + firstRegion.freq_end_hz) / 2) : 'n/a'} />
          <Metric label="Detector" value={firstRegion?.detector?.type ?? 'morphological'} />
        </Panel>

        <Panel title="Region classification" icon={<BrainCircuit className="h-4 w-4" />}>
          <Metric label="Visual" value={firstRegion?.classification?.visual_label ?? 'unknown'} />
          <Metric label="MLP" value={firstRegion?.classification?.mlp_label ?? 'unknown'} />
          <Metric label="Policy" value="protocol-like only" />
        </Panel>

        <Panel title="Spectral features" icon={<RadioTower className="h-4 w-4" />}>
          <Metric label="Occupied BW" value={`${Number(spectral.occupied_bandwidth_hz ?? 0).toFixed(0)} Hz`} />
          <Metric label="SNR" value={`${Number(spectral.snr_db ?? 0).toFixed(1)} dB`} />
          <Metric label="Entropy" value={Number(spectral.spectral_entropy ?? 0).toFixed(3)} />
        </Panel>

        <Panel title="Bispectral verification" icon={<Beaker className="h-4 w-4" />}>
          <Metric label="Peak energy" value={Number(bispectral.bispectral_peak_energy ?? 0).toFixed(3)} />
          <Metric label="Phase coupling" value={Number(bispectral.phase_coupling_score ?? 0).toFixed(3)} />
          <Metric label="Nonlinear ratio" value={Number(bispectral.nonlinear_energy_ratio ?? 0).toFixed(3)} />
        </Panel>

        <Panel title="Final fused decision" icon={<ScanSearch className="h-4 w-4" />}>
          <Metric label="Label" value={finalDecision?.label ?? 'unknown'} />
          <Metric label="Confidence" value={`${(Number(finalDecision?.confidence ?? 0) * 100).toFixed(0)}%`} />
          <Metric label="Status" value={finalDecision?.status ?? 'unknown'} />
        </Panel>

        <Panel title="Legacy vs new comparison" icon={<GitCompare className="h-4 w-4" />}>
          <Metric label="Legacy" value={comparison?.legacy_rf_intelligence?.label ?? 'not compared'} />
          <Metric label="New" value={comparison?.new_rf_signal_understanding?.label ?? finalDecision?.label ?? 'unknown'} />
          <Metric label="Agreement" value={comparison?.comparison?.agreement_level ?? 'n/a'} />
        </Panel>

        <Panel title="Export result to dataset" icon={<Save className="h-4 w-4" />}>
          <Metric label="Artifacts" value="saved by backend" />
          <Metric label="Folder" value={result ? `analyses/${result.analysis_id}` : 'n/a'} />
          <Metric label="Includes" value="IQ, PNG, JSON, NPY" />
        </Panel>
      </div>

      <section className="mt-4 rounded-lg border p-4" style={{ borderColor: 'var(--app-border)', background: 'var(--app-surface)' }}>
        <div className="mb-3 text-sm font-semibold">Scientific traceability</div>
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
          {techniqueRows.map(([technique, paper]) => (
            <div key={technique} className="rounded-md bg-black/5 px-3 py-2 text-sm">
              <div className="font-medium">Technique: {technique}</div>
              <div className="mt-1 text-[var(--app-text-muted)]">Supported by: {paper}</div>
            </div>
          ))}
        </div>
        {references && <div className="mt-3 text-xs text-[var(--app-text-muted)]">Reference groups loaded: {Object.keys(references).join(', ')}</div>}
      </section>
    </div>
  );
};

const Panel = ({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) => (
  <section className="rounded-lg border p-4" style={{ borderColor: 'var(--app-border)', background: 'var(--app-surface)' }}>
    <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
      {icon}
      {title}
    </div>
    <div className="space-y-2">{children}</div>
  </section>
);

const Metric = ({ label, value }: { label: string; value: string }) => (
  <div className="flex items-center justify-between gap-3 rounded-md bg-black/5 px-3 py-2 text-sm">
    <span className="text-[var(--app-text-muted)]">{label}</span>
    <span className="max-w-[14rem] truncate text-right font-medium">{value}</span>
  </div>
);

const NumberInput = ({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) => (
  <label className="block">
    <span className="text-xs uppercase text-[var(--app-text-muted)]">{label}</span>
    <input value={value} onChange={(event) => onChange(Number(event.target.value))} type="number" className="mt-2 w-full rounded-md border bg-transparent px-3 py-2 text-sm" style={{ borderColor: 'var(--app-border)' }} />
  </label>
);
