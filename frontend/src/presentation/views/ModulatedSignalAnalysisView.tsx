import React, { useEffect, useMemo, useState } from 'react';
import { Database, Download, Play, RotateCcw } from 'lucide-react';
import { ApiService } from '../../app/services/ApiService';
import { useMarkers } from '../../app/store/AppStore';
import { MODULATION_HINTS } from '../../shared/constants';
import { ModulatedSignalCapture } from '../../shared/types';
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

const formatBytes = (value: number) => {
  if (!Number.isFinite(value) || value <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
};

export const ModulatedSignalAnalysisView: React.FC = () => {
  const markers = useMarkers();
  const [durationSeconds, setDurationSeconds] = useState('5');
  const [fileFormat, setFileFormat] = useState<'cfile' | 'iq'>('cfile');
  const [label, setLabel] = useState('');
  const [modulationHint, setModulationHint] = useState('unknown');
  const [notes, setNotes] = useState('');
  const [isCapturing, setIsCapturing] = useState(false);
  const [error, setError] = useState<string | null>(null);
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

  const loadCaptures = async () => {
    const data = await apiService.getModulatedSignalCaptures();
    setCaptures(data);
  };

  useEffect(() => {
    loadCaptures().catch(() => undefined);
  }, []);

  const captureSignal = async () => {
    if (!selectedBand) {
      setError('Create at least two markers first. M1 and M2 define the capture band.');
      return;
    }

    const duration = Number(durationSeconds);
    if (!Number.isFinite(duration) || duration <= 0 || duration > 120) {
      setError('Duration must be between 0 and 120 seconds.');
      return;
    }

    setError(null);
    setIsCapturing(true);
    try {
      const capture = await apiService.captureModulatedSignal({
        startFrequencyHz: selectedBand.start,
        stopFrequencyHz: selectedBand.stop,
        durationSeconds: duration,
        label,
        modulationHint,
        notes,
        fileFormat,
      });
      setCaptures((current) => [capture, ...current.filter((item) => item.id !== capture.id)]);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setIsCapturing(false);
    }
  };

  return (
    <div className="h-full overflow-auto bg-slate-950 text-slate-100">
      <div className="max-w-7xl mx-auto p-6 space-y-5">
        <section className="border border-slate-800 bg-slate-900 p-4 rounded-md">
          <div className="flex items-center justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold">Modulated Signal Analysis</h2>
              <p className="text-sm text-slate-400">
                Capture the RF band between M1 and M2 as complex IQ with metadata for replay workflows and AI datasets.
              </p>
            </div>
            <button
              onClick={() => loadCaptures()}
              className="h-9 inline-flex items-center px-3 rounded-md bg-slate-700 hover:bg-slate-600 text-sm"
            >
              <RotateCcw className="w-4 h-4 mr-2" />
              Refresh
            </button>
          </div>
        </section>

        <section className="grid grid-cols-1 xl:grid-cols-[1fr_420px] gap-5">
          <div className="border border-slate-800 bg-slate-900 p-4 rounded-md space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <Info label="M1" value={selectedBand ? formatFrequency(selectedBand.first.frequency) : 'Not set'} />
              <Info label="M2" value={selectedBand ? formatFrequency(selectedBand.second.frequency) : 'Not set'} />
              <Info label="Center" value={selectedBand ? formatFrequency(selectedBand.center) : 'Not set'} />
              <Info label="Bandwidth" value={selectedBand ? formatFrequency(selectedBand.bandwidth) : 'Not set'} />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
              <label className="flex flex-col gap-1 text-xs text-slate-400">
                Label
                <input
                  value={label}
                  onChange={(event) => setLabel(event.target.value)}
                  placeholder="device_01_signal_a"
                  className="h-9 rounded-md border border-slate-700 bg-slate-950 px-2 text-sm text-slate-100 outline-none focus:border-blue-400"
                />
              </label>

              <label className="flex flex-col gap-1 text-xs text-slate-400">
                Modulation hint
                <select
                  value={modulationHint}
                  onChange={(event) => setModulationHint(event.target.value)}
                  className="h-9 rounded-md border border-slate-700 bg-slate-950 px-2 text-sm text-slate-100 outline-none focus:border-blue-400"
                >
                  {MODULATION_HINTS.map((item) => (
                    <option key={item.value} value={item.value}>{item.label}</option>
                  ))}
                </select>
              </label>

              <label className="flex flex-col gap-1 text-xs text-slate-400">
                Duration s
                <input
                  value={durationSeconds}
                  onChange={(event) => setDurationSeconds(event.target.value)}
                  className="h-9 rounded-md border border-slate-700 bg-slate-950 px-2 text-sm text-slate-100 outline-none focus:border-blue-400"
                />
              </label>

              <label className="flex flex-col gap-1 text-xs text-slate-400">
                File format
                <select
                  value={fileFormat}
                  onChange={(event) => setFileFormat(event.target.value as 'cfile' | 'iq')}
                  className="h-9 rounded-md border border-slate-700 bg-slate-950 px-2 text-sm text-slate-100 outline-none focus:border-blue-400"
                >
                  <option value="cfile">CFILE</option>
                  <option value="iq">IQ</option>
                </select>
              </label>

              <button
                onClick={captureSignal}
                disabled={isCapturing || !selectedBand}
                className={cn(
                  'h-9 self-end inline-flex items-center justify-center px-4 rounded-md text-sm font-semibold',
                  isCapturing || !selectedBand
                    ? 'bg-slate-700 text-slate-400 cursor-not-allowed'
                    : 'bg-emerald-600 hover:bg-emerald-500 text-white'
                )}
              >
                <Play className="w-4 h-4 mr-2" />
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
          </div>

          <div className="border border-slate-800 bg-slate-900 p-4 rounded-md">
            <h3 className="text-sm font-semibold mb-3">Capture Contents</h3>
            <div className="space-y-2 text-sm text-slate-300">
              <p>Each capture creates a raw complex IQ file and a JSON metadata file.</p>
              <p>Choose `CFILE` for GNU Radio-style complex64 captures or `IQ` when you need a `.iq` extension for external tools and datasets.</p>
              <p>The metadata stores frequency limits, center, bandwidth, sample rate, gain, antenna, format, file hash, replay parameters, label, and modulation hint.</p>
              <p>Use these files later for offline analysis, controlled replay workflows, or AI model training datasets.</p>
            </div>
          </div>
        </section>

        <section className="border border-slate-800 bg-slate-900 rounded-md overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-800 flex items-center gap-2">
            <Database className="w-4 h-4" />
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
  return (
    <div className="p-4 space-y-3">
      <div className="flex flex-wrap justify-between gap-3">
        <div>
          <div className="text-sm font-semibold">
            {capture.label || capture.id} | {fileFormat} | {formatFrequency(capture.center_frequency_hz)} | BW {formatFrequency(capture.bandwidth_hz)}
          </div>
          <div className="text-xs text-slate-400">
            {capture.modulation_hint || 'unknown'} | {capture.duration_seconds}s | {formatFrequency(capture.sample_rate_hz)}/s | {formatBytes(capture.file_size_bytes)}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <a
            href={iqUrl}
            className="h-9 inline-flex items-center px-3 rounded-md bg-blue-600 hover:bg-blue-500 text-sm font-medium"
          >
            <Download className="w-4 h-4 mr-2" />
            {fileFormat}
          </a>
          <a
            href={metadataUrl}
            className="h-9 inline-flex items-center px-3 rounded-md bg-slate-700 hover:bg-slate-600 text-sm font-medium"
          >
            <Download className="w-4 h-4 mr-2" />
            JSON
          </a>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-2 text-xs text-slate-400">
        <div>Start: {formatFrequency(capture.start_frequency_hz)}</div>
        <div>Stop: {formatFrequency(capture.stop_frequency_hz)}</div>
        <div>Gain: {capture.gain_db.toFixed(1)} dB</div>
        <div>Antenna: {capture.antenna}</div>
        <div>Format: {capture.iq_format}{capture.file_extension ? ` ${capture.file_extension}` : ''}</div>
        <div>SHA256: {capture.sha256.slice(0, 16)}...</div>
      </div>

      {capture.notes && <div className="text-sm text-slate-300">{capture.notes}</div>}
    </div>
  );
}
