import React, { useEffect, useState } from 'react';
import { ApiService } from '../../app/services/ApiService';
import { FingerprintingCaptureRecord, ModulatedSignalCapture } from '../../shared/types';

const api = new ApiService();

const splitHelp = {
  train: {
    title: 'Training',
    description:
      'Se usa para ajustar el modelo. No debe reutilizarse luego como validacion externa ni como prediccion final.',
    destination: 'fingerprinting/train',
  },
  val: {
    title: 'Validation',
    description:
      'Se reserva para medir rendimiento fuera del entrenamiento. Debe mantenerse aislada de train.',
    destination: 'fingerprinting/val',
  },
  predict: {
    title: 'Prediction',
    description:
      'Se usa para inferencia o verificacion sobre capturas nuevas. No debe contaminar train ni val.',
    destination: 'fingerprinting/predict',
  },
} as const;

const defaultForm = {
  session_id: 'session_001',
  dataset_split: 'train' as 'train' | 'val' | 'predict',
  capture_config: {
    device_source: 'uhd',
    sdr_model: 'USRP-B200',
    sdr_serial: 'unknown',
    gain_stage: 'manual',
    antenna_port: 'RX2',
    capture_type: 'iq_file',
    center_frequency_hz: 433920000,
    sample_rate_hz: 2000000,
    effective_bandwidth_hz: 2000000,
    frontend_bandwidth_hz: 2000000,
    gain_mode: 'manual',
    gain_settings: {
      lna_db: 20,
      vga_db: 0,
      if_db: 0,
      composite_gain_db: 20,
    },
    ppm_correction: 0,
    lo_offset_hz: 0,
    capture_duration_s: 2,
    sample_count: 0,
    file_format: 'cfile',
    sample_dtype: 'complex64',
    byte_order: 'native',
    channel_count: 1,
    output_path: '',
    dataset_destination: splitHelp.train.destination as string,
  },
  transmitter: {
    transmitter_label: 'remote_001',
    transmitter_class: 'garage_remote',
    transmitter_id: 'tx_remote_001',
    family: 'subghz_remote',
    ground_truth_confidence: 'confirmed',
  },
  scenario: {
    operator: 'operator_a',
    environment: 'indoor_lab_los',
    distance_m: 2,
    line_of_sight: true,
    indoor: true,
    notes: '',
    session_number: 1,
  },
  quality_metrics: {
    estimated_snr_db: 18,
    noise_floor_db: -96,
    peak_power_db: -24,
    average_power_db: -35,
    occupied_bandwidth_hz: 180000,
    peak_frequency_hz: 433920120,
    frequency_offset_hz: 120,
    clipping_pct: 0,
    sample_drop_count: 0,
    buffer_overflow_count: 0,
    silence_pct: 4,
    peak_to_average_ratio_db: 11,
    kurtosis: 2.8,
    burst_duration_ms: 42,
  },
  burst_detection: {
    method: 'energy_threshold',
    energy_threshold_db: -42,
    pre_trigger_samples: 4096,
    post_trigger_samples: 8192,
    min_burst_duration_ms: 1,
    max_burst_duration_ms: 120,
    burst_count: 1,
    regions_of_interest: ['transient_start', 'whole_burst'],
    burst_start_sample: 4096,
    burst_end_sample: 98304,
  },
  artifacts: {
    iq_file: '',
    metadata_file: '',
    sha256: '',
  },
  operator_decision: 'valid',
  review_notes: '',
  export_windows: ['transient_start', 'whole_burst'],
};

const sectionClass =
  'rounded-[1.75rem] border border-slate-200 bg-white/90 p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]';
const labelClass = 'text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500';
const inputClass =
  'mt-2 w-full rounded-2xl border border-slate-300 bg-slate-50 px-3 py-2 text-sm text-slate-900 outline-none transition focus:border-teal-500 focus:bg-white';

export const GuidedCaptureView: React.FC = () => {
  const [form, setForm] = useState(defaultForm);
  const [captures, setCaptures] = useState<FingerprintingCaptureRecord[]>([]);
  const [modulatedCaptures, setModulatedCaptures] = useState<ModulatedSignalCapture[]>([]);
  const [message, setMessage] = useState<string>('');

  const activeSplit = splitHelp[form.dataset_split as keyof typeof splitHelp];

  const refresh = async () => {
    const [fingerprintingCaptures, modulated] = await Promise.all([
      api.getFingerprintingCaptures(),
      api.getModulatedSignalCaptures(),
    ]);
    setCaptures(fingerprintingCaptures);
    setModulatedCaptures(modulated.slice(0, 6));
  };

  useEffect(() => {
    refresh().catch((error) => console.error('Failed to load guided capture data', error));
  }, []);

  const setNested = (section: keyof typeof form, field: string, value: unknown) => {
    setForm((current) => ({
      ...current,
      [section]: {
        ...(current[section] as Record<string, unknown>),
        [field]: value,
      },
    }));
  };

  const setGainSetting = (field: string, value: number) => {
    setForm((current) => ({
      ...current,
      capture_config: {
        ...current.capture_config,
        gain_settings: {
          ...current.capture_config.gain_settings,
          [field]: value,
        },
      },
    }));
  };

  const setDatasetSplit = (datasetSplit: 'train' | 'val' | 'predict') => {
    setForm((current) => ({
      ...current,
      dataset_split: datasetSplit,
      capture_config: {
        ...current.capture_config,
        dataset_destination: splitHelp[datasetSplit].destination,
      },
    }));
  };

  const submit = async () => {
    try {
      await api.createFingerprintingCapture(form);
      setMessage(`Scientific capture manifest stored as ${form.dataset_split}.`);
      await refresh();
    } catch (error) {
      console.error(error);
      setMessage('Failed to store scientific capture manifest.');
    }
  };

  const importCapture = async (capture: ModulatedSignalCapture) => {
    try {
      await api.importModulatedCaptureToFingerprinting(capture.id, {
        session_id: form.session_id,
        dataset_split: form.dataset_split,
        transmitter_label: form.transmitter.transmitter_label,
        transmitter_class: form.transmitter.transmitter_class,
        transmitter_id: form.transmitter.transmitter_id,
        operator: form.scenario.operator,
        environment: form.scenario.environment,
        notes: form.scenario.notes,
        ground_truth_confidence: form.transmitter.ground_truth_confidence,
      });
      setMessage(`Imported modulated capture ${capture.id} as ${form.dataset_split}.`);
      await refresh();
    } catch (error) {
      console.error(error);
      setMessage(`Failed to import modulated capture ${capture.id}.`);
    }
  };

  return (
    <div className="min-h-full bg-[linear-gradient(180deg,_#f7fafc,_#edf6f3)] p-6">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="text-sm font-semibold uppercase tracking-[0.2em] text-teal-700">Guided Capture</div>
          <h1 className="mt-2 font-serif text-4xl text-slate-900">Adquisicion rigurosa, no grabacion indiscriminada</h1>
          <p className="mt-3 max-w-4xl text-sm leading-7 text-slate-600">
            Esta vista obliga a separar configuracion SDR, identidad del emisor, escenario de adquisicion, split del
            dataset, burst detection y control de calidad. El objetivo es que el modelo aprenda el transmisor, no el setup.
          </p>
        </div>
        <div className="rounded-full border border-slate-300 bg-white px-4 py-2 text-sm text-slate-700">{message}</div>
      </div>

      <div className="grid gap-5 xl:grid-cols-[1.25fr_0.95fr]">
        <div className="space-y-5">
          <section className={sectionClass}>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className={labelClass}>Capture intent / dataset split</div>
                <p className="mt-2 max-w-3xl text-sm leading-7 text-slate-600">
                  Antes de capturar tienes que declarar si esta muestra es para entrenamiento, validacion externa o prediccion.
                  Esa decision afecta como se debe usar despues y evita fugas entre fases experimentales.
                </p>
              </div>
              <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
                Current destination: <span className="font-mono text-xs">{activeSplit.destination}</span>
              </div>
            </div>
            <div className="mt-5 grid gap-4 md:grid-cols-3">
              {(['train', 'val', 'predict'] as const).map((split) => (
                <button
                  key={split}
                  type="button"
                  onClick={() => setDatasetSplit(split)}
                  className={`rounded-[1.5rem] border p-5 text-left transition ${
                    form.dataset_split === split
                      ? 'border-slate-900 bg-slate-950 text-white'
                      : 'border-slate-200 bg-slate-50 text-slate-900 hover:bg-white'
                  }`}
                >
                  <div className="text-xs font-semibold uppercase tracking-[0.18em] opacity-80">{splitHelp[split].title}</div>
                  <p className="mt-3 text-sm leading-6 opacity-90">{splitHelp[split].description}</p>
                </button>
              ))}
            </div>
          </section>

          <section className={sectionClass}>
            <div className="grid gap-4 md:grid-cols-3">
              <label>
                <div className={labelClass}>Device / SDR source</div>
                <input className={inputClass} value={form.capture_config.device_source} onChange={(e) => setNested('capture_config', 'device_source', e.target.value)} />
              </label>
              <label>
                <div className={labelClass}>SDR model</div>
                <input className={inputClass} value={form.capture_config.sdr_model} onChange={(e) => setNested('capture_config', 'sdr_model', e.target.value)} />
              </label>
              <label>
                <div className={labelClass}>Serial</div>
                <input className={inputClass} value={form.capture_config.sdr_serial} onChange={(e) => setNested('capture_config', 'sdr_serial', e.target.value)} />
              </label>
              <label>
                <div className={labelClass}>Center frequency (Hz)</div>
                <input className={inputClass} type="number" value={form.capture_config.center_frequency_hz} onChange={(e) => setNested('capture_config', 'center_frequency_hz', Number(e.target.value))} />
              </label>
              <label>
                <div className={labelClass}>Sample rate (Hz)</div>
                <input className={inputClass} type="number" value={form.capture_config.sample_rate_hz} onChange={(e) => setNested('capture_config', 'sample_rate_hz', Number(e.target.value))} />
              </label>
              <label>
                <div className={labelClass}>Effective bandwidth (Hz)</div>
                <input className={inputClass} type="number" value={form.capture_config.effective_bandwidth_hz} onChange={(e) => setNested('capture_config', 'effective_bandwidth_hz', Number(e.target.value))} />
              </label>
              <label>
                <div className={labelClass}>Capture duration (s)</div>
                <input className={inputClass} type="number" value={form.capture_config.capture_duration_s} onChange={(e) => setNested('capture_config', 'capture_duration_s', Number(e.target.value))} />
              </label>
              <label>
                <div className={labelClass}>PPM correction</div>
                <input className={inputClass} type="number" value={form.capture_config.ppm_correction} onChange={(e) => setNested('capture_config', 'ppm_correction', Number(e.target.value))} />
              </label>
              <label>
                <div className={labelClass}>LO offset (Hz)</div>
                <input className={inputClass} type="number" value={form.capture_config.lo_offset_hz} onChange={(e) => setNested('capture_config', 'lo_offset_hz', Number(e.target.value))} />
              </label>
            </div>
            <div className="mt-4 grid gap-4 md:grid-cols-4">
              <label>
                <div className={labelClass}>LNA gain</div>
                <input className={inputClass} type="number" value={Number(form.capture_config.gain_settings.lna_db)} onChange={(e) => setGainSetting('lna_db', Number(e.target.value))} />
              </label>
              <label>
                <div className={labelClass}>VGA gain</div>
                <input className={inputClass} type="number" value={Number(form.capture_config.gain_settings.vga_db)} onChange={(e) => setGainSetting('vga_db', Number(e.target.value))} />
              </label>
              <label>
                <div className={labelClass}>IF gain</div>
                <input className={inputClass} type="number" value={Number(form.capture_config.gain_settings.if_db)} onChange={(e) => setGainSetting('if_db', Number(e.target.value))} />
              </label>
              <label>
                <div className={labelClass}>Composite gain</div>
                <input className={inputClass} type="number" value={Number(form.capture_config.gain_settings.composite_gain_db)} onChange={(e) => setGainSetting('composite_gain_db', Number(e.target.value))} />
              </label>
            </div>
          </section>

          <section className={sectionClass}>
            <div className="grid gap-4 md:grid-cols-3">
              <label>
                <div className={labelClass}>Transmitter label</div>
                <input className={inputClass} value={form.transmitter.transmitter_label} onChange={(e) => setNested('transmitter', 'transmitter_label', e.target.value)} />
              </label>
              <label>
                <div className={labelClass}>Class / family</div>
                <input className={inputClass} value={form.transmitter.transmitter_class} onChange={(e) => setNested('transmitter', 'transmitter_class', e.target.value)} />
              </label>
              <label>
                <div className={labelClass}>Unique transmitter ID</div>
                <input className={inputClass} value={form.transmitter.transmitter_id} onChange={(e) => setNested('transmitter', 'transmitter_id', e.target.value)} />
              </label>
              <label>
                <div className={labelClass}>Session ID</div>
                <input className={inputClass} value={form.session_id} onChange={(e) => setForm((current) => ({ ...current, session_id: e.target.value }))} />
              </label>
              <label>
                <div className={labelClass}>Dataset split</div>
                <select className={inputClass} value={form.dataset_split} onChange={(e) => setDatasetSplit(e.target.value as 'train' | 'val' | 'predict')}>
                  <option value="train">train</option>
                  <option value="val">val</option>
                  <option value="predict">predict</option>
                </select>
              </label>
              <label>
                <div className={labelClass}>Operator</div>
                <input className={inputClass} value={form.scenario.operator} onChange={(e) => setNested('scenario', 'operator', e.target.value)} />
              </label>
              <label>
                <div className={labelClass}>Environment</div>
                <input className={inputClass} value={form.scenario.environment} onChange={(e) => setNested('scenario', 'environment', e.target.value)} />
              </label>
            </div>
            <label className="mt-4 block">
              <div className={labelClass}>Notes</div>
              <textarea className={`${inputClass} min-h-24`} value={form.scenario.notes} onChange={(e) => setNested('scenario', 'notes', e.target.value)} />
            </label>
          </section>

          <section className={sectionClass}>
            <div className="grid gap-4 md:grid-cols-4">
              <label>
                <div className={labelClass}>Estimated SNR (dB)</div>
                <input className={inputClass} type="number" value={form.quality_metrics.estimated_snr_db} onChange={(e) => setNested('quality_metrics', 'estimated_snr_db', Number(e.target.value))} />
              </label>
              <label>
                <div className={labelClass}>Frequency offset (Hz)</div>
                <input className={inputClass} type="number" value={form.quality_metrics.frequency_offset_hz} onChange={(e) => setNested('quality_metrics', 'frequency_offset_hz', Number(e.target.value))} />
              </label>
              <label>
                <div className={labelClass}>Clipping (%)</div>
                <input className={inputClass} type="number" value={form.quality_metrics.clipping_pct} onChange={(e) => setNested('quality_metrics', 'clipping_pct', Number(e.target.value))} />
              </label>
              <label>
                <div className={labelClass}>Silence (%)</div>
                <input className={inputClass} type="number" value={form.quality_metrics.silence_pct} onChange={(e) => setNested('quality_metrics', 'silence_pct', Number(e.target.value))} />
              </label>
              <label>
                <div className={labelClass}>Energy threshold (dB)</div>
                <input className={inputClass} type="number" value={form.burst_detection.energy_threshold_db ?? 0} onChange={(e) => setNested('burst_detection', 'energy_threshold_db', Number(e.target.value))} />
              </label>
              <label>
                <div className={labelClass}>Pre-trigger samples</div>
                <input className={inputClass} type="number" value={form.burst_detection.pre_trigger_samples} onChange={(e) => setNested('burst_detection', 'pre_trigger_samples', Number(e.target.value))} />
              </label>
              <label>
                <div className={labelClass}>Post-trigger samples</div>
                <input className={inputClass} type="number" value={form.burst_detection.post_trigger_samples} onChange={(e) => setNested('burst_detection', 'post_trigger_samples', Number(e.target.value))} />
              </label>
              <label>
                <div className={labelClass}>Burst duration (ms)</div>
                <input className={inputClass} type="number" value={form.quality_metrics.burst_duration_ms} onChange={(e) => setNested('quality_metrics', 'burst_duration_ms', Number(e.target.value))} />
              </label>
            </div>
            <label className="mt-4 block">
              <div className={labelClass}>IQ file</div>
              <input className={inputClass} value={form.artifacts.iq_file} onChange={(e) => setForm((current) => ({ ...current, artifacts: { ...current.artifacts, iq_file: e.target.value }, capture_config: { ...current.capture_config, output_path: e.target.value } }))} />
            </label>
            <label className="mt-4 block">
              <div className={labelClass}>Dataset destination</div>
              <input className={inputClass} value={form.capture_config.dataset_destination} onChange={(e) => setNested('capture_config', 'dataset_destination', e.target.value)} />
            </label>
            <div className="mt-5 flex flex-wrap gap-3">
              <button className="rounded-full bg-teal-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-teal-500" onClick={submit}>
                Save Scientific Manifest
              </button>
              <a className="rounded-full border border-slate-300 px-5 py-3 text-sm font-semibold text-slate-700 transition hover:bg-slate-100" href="/spectrum">
                Open Live Monitor
              </a>
            </div>
          </section>
        </div>

        <div className="space-y-5">
          <section className={sectionClass}>
            <div className="mb-4 flex items-center justify-between">
              <div>
                <div className={labelClass}>Real IQ captures available</div>
                <div className="mt-1 text-sm text-slate-600">
                  Importa una captura ya adquirida en `Signal Analysis` y clasificala como train, val o predict.
                </div>
              </div>
            </div>
            <div className="space-y-3">
              {modulatedCaptures.map((capture) => (
                <div key={capture.id} className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <div className="font-semibold text-slate-900">{capture.id}</div>
                      <div className="mt-1 text-xs text-slate-600">
                        {(capture.center_frequency_hz / 1e6).toFixed(6)} MHz · {(capture.bandwidth_hz / 1e3).toFixed(1)} kHz · {capture.duration_seconds}s
                      </div>
                      <div className="mt-1 text-xs text-slate-500">Will import as: {form.dataset_split}</div>
                    </div>
                    <button
                      className="rounded-full border border-teal-500 px-3 py-2 text-xs font-semibold text-teal-700 transition hover:bg-teal-50"
                      onClick={() => importCapture(capture)}
                    >
                      Import as fingerprint capture
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className={sectionClass}>
            <div className="mb-4 flex items-center justify-between">
              <div className={labelClass}>Recent scientific captures</div>
              <div className="text-xs text-slate-500">{captures.length} manifests</div>
            </div>
            <div className="space-y-3">
              {captures.slice(0, 6).map((capture) => (
                <div key={capture.capture_id} className="rounded-2xl border border-slate-200 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="font-semibold text-slate-900">{capture.transmitter.transmitter_id}</div>
                      <div className="text-xs text-slate-600">
                        {capture.session_id} · {capture.dataset_split} · {capture.capture_config.dataset_destination}
                      </div>
                    </div>
                    <span
                      className={`rounded-full px-3 py-1 text-xs font-semibold ${
                        capture.quality_review.status === 'valid'
                          ? 'bg-emerald-100 text-emerald-700'
                          : capture.quality_review.status === 'doubtful'
                            ? 'bg-amber-100 text-amber-700'
                            : 'bg-rose-100 text-rose-700'
                      }`}
                    >
                      {capture.quality_review.status}
                    </span>
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-slate-600">
                    <div>SNR: {capture.quality_metrics.estimated_snr_db ?? 0} dB</div>
                    <div>Offset: {capture.quality_metrics.frequency_offset_hz ?? 0} Hz</div>
                    <div>Clipping: {capture.quality_metrics.clipping_pct ?? 0}%</div>
                    <div>Burst: {capture.quality_metrics.burst_duration_ms ?? 0} ms</div>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
};
