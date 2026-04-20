import React, { useEffect, useMemo, useState } from 'react';
import { Play, RotateCcw, Radio, Download } from 'lucide-react';
import { ApiService } from '../../app/services/ApiService';
import { useMarkers } from '../../app/store/AppStore';
import { DEMODULATION_MODES } from '../../shared/constants';
import { DemodulationResult } from '../../shared/types';
import { formatFrequency } from '../../shared/utils';
import { cn } from '../../shared/utils';

const apiService = new ApiService();

const getErrorMessage = (error: unknown) => {
  if (typeof error === 'object' && error !== null && 'response' in error) {
    const response = (error as { response?: { data?: { detail?: string } } }).response;
    if (response?.data?.detail) return response.data.detail;
  }
  return error instanceof Error ? error.message : 'Operation failed';
};

export const DemodulationView: React.FC = () => {
  const markers = useMarkers();
  const [mode, setMode] = useState('fm');
  const [durationSeconds, setDurationSeconds] = useState('5');
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<DemodulationResult[]>([]);

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

  const loadResults = async () => {
    const data = await apiService.getDemodulationResults();
    setResults(data.reverse());
  };

  useEffect(() => {
    loadResults().catch(() => undefined);
  }, []);

  const applyDemodulation = async () => {
    if (!selectedBand) {
      setError('Create at least two markers first. M1 and M2 define the demodulation band.');
      return;
    }

    const duration = Number(durationSeconds);
    if (!Number.isFinite(duration) || duration <= 0 || duration > 60) {
      setError('Duration must be between 0 and 60 seconds.');
      return;
    }

    setError(null);
    setIsRunning(true);
    try {
      const result = await apiService.demodulateMarkerBand({
        startFrequencyHz: selectedBand.start,
        stopFrequencyHz: selectedBand.stop,
        mode,
        durationSeconds: duration,
      });
      setResults((current) => [result, ...current]);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setIsRunning(false);
    }
  };

  return (
    <div className="h-full overflow-auto bg-slate-950 text-slate-100">
      <div className="max-w-6xl mx-auto p-6 space-y-5">
        <section className="border border-slate-800 bg-slate-900 p-4 rounded-md">
          <div className="flex items-center justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold">Marker Band Demodulation</h2>
              <p className="text-sm text-slate-400">
                M1 and M2 define the RF band. AM/FM/WFM generate WAV audio. ASK/FSK/PSK/OOK capture IQ and metadata for digital analysis.
              </p>
            </div>
            <button
              onClick={() => loadResults()}
              className="h-9 inline-flex items-center px-3 rounded-md bg-slate-700 hover:bg-slate-600 text-sm"
            >
              <RotateCcw className="w-4 h-4 mr-2" />
              Refresh
            </button>
          </div>
        </section>

        <section className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-5">
          <div className="border border-slate-800 bg-slate-900 p-4 rounded-md space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <Info label="M1" value={selectedBand ? formatFrequency(selectedBand.first.frequency) : 'Not set'} />
              <Info label="M2" value={selectedBand ? formatFrequency(selectedBand.second.frequency) : 'Not set'} />
              <Info label="Center" value={selectedBand ? formatFrequency(selectedBand.center) : 'Not set'} />
              <Info label="Bandwidth" value={selectedBand ? formatFrequency(selectedBand.bandwidth) : 'Not set'} />
            </div>

            <div className="flex flex-wrap items-end gap-3">
              <label className="flex flex-col gap-1 text-xs text-slate-400">
                Demodulation
                <select
                  value={mode}
                  onChange={(event) => setMode(event.target.value)}
                  className="h-9 w-32 rounded-md border border-slate-700 bg-slate-950 px-2 text-sm text-slate-100 outline-none focus:border-blue-400"
                >
                  {DEMODULATION_MODES.map((item) => (
                    <option key={item.value} value={item.value}>{item.label}</option>
                  ))}
                </select>
              </label>

              <label className="flex flex-col gap-1 text-xs text-slate-400">
                Duration s
                <input
                  value={durationSeconds}
                  onChange={(event) => setDurationSeconds(event.target.value)}
                  className="h-9 w-24 rounded-md border border-slate-700 bg-slate-950 px-2 text-sm text-slate-100 outline-none focus:border-blue-400"
                />
              </label>

              <button
                onClick={applyDemodulation}
                disabled={isRunning || !selectedBand}
                className={cn(
                  'h-9 inline-flex items-center px-4 rounded-md text-sm font-semibold',
                  isRunning || !selectedBand
                    ? 'bg-slate-700 text-slate-400 cursor-not-allowed'
                    : 'bg-emerald-600 hover:bg-emerald-500 text-white'
                )}
              >
                <Play className="w-4 h-4 mr-2" />
                {isRunning ? 'Demodulating...' : 'Apply Demodulation'}
              </button>
            </div>

            {error && <div className="text-sm text-red-300">{error}</div>}
          </div>

          <div className="border border-slate-800 bg-slate-900 p-4 rounded-md">
            <h3 className="text-sm font-semibold mb-3">Mode Notes</h3>
            <div className="space-y-2 text-sm text-slate-300">
              <p><span className="text-slate-100 font-medium">AM/FM/WFM:</span> produce a WAV file that can be played in the dashboard.</p>
              <p><span className="text-slate-100 font-medium">ASK/FSK/PSK/OOK:</span> capture the selected marker band as IQ plus metadata for later symbol analysis.</p>
              <p>The selected center is the midpoint between M1 and M2.</p>
            </div>
          </div>
        </section>

        <section className="border border-slate-800 bg-slate-900 rounded-md overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-800 flex items-center gap-2">
            <Radio className="w-4 h-4" />
            <h3 className="text-sm font-semibold">Demodulation Results</h3>
          </div>
          <div className="divide-y divide-slate-800">
            {results.length === 0 ? (
              <div className="p-4 text-sm text-slate-500">No demodulation results yet.</div>
            ) : results.map((result) => (
              <ResultRow key={result.id} result={result} />
            ))}
          </div>
        </section>
      </div>
    </div>
  );
};

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950 p-3">
      <div className="text-xs uppercase text-slate-500">{label}</div>
      <div className="text-sm font-semibold text-slate-100">{value}</div>
    </div>
  );
}

function ResultRow({ result }: { result: DemodulationResult }) {
  const audioUrl = result.audio_url ? apiService.getDemodulationAudioUrl(result.id) : null;
  return (
    <div className="p-4 space-y-3">
      <div className="flex flex-wrap justify-between gap-3">
        <div>
          <div className="text-sm font-semibold">
            {result.mode.toUpperCase()} | {formatFrequency(result.center_frequency_hz)} | BW {formatFrequency(result.bandwidth_hz)}
          </div>
          <div className="text-xs text-slate-400">
            {result.duration_seconds}s capture | {formatFrequency(result.sample_rate_hz)}/s | {result.status}
          </div>
        </div>
        {audioUrl && (
          <a
            href={audioUrl}
            className="h-9 inline-flex items-center px-3 rounded-md bg-blue-600 hover:bg-blue-500 text-sm font-medium"
          >
            <Download className="w-4 h-4 mr-2" />
            WAV
          </a>
        )}
      </div>
      {audioUrl ? (
        <audio controls src={audioUrl} className="w-full" />
      ) : (
        <div className="text-sm text-slate-400">
          This mode does not produce dashboard audio yet. IQ and metadata were captured for digital analysis/export.
        </div>
      )}
    </div>
  );
}
