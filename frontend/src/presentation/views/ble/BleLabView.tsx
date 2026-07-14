import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Bluetooth, CheckCircle2, Download, Play, RefreshCw, RotateCcw, Square } from 'lucide-react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { BleAdvertisement, BleAdvertiser, BleApiService, BleCapabilities, BleCaptureCapabilities, BleCaptureJob, BleCaptureLive, BleCaptureRecord, BleGate2a2Candidate, BleGate2a2ConfirmedPacket, BleGate2a2Job, BleGate2a2Status, BleJob, BleJobEvent, BlePacket } from '../../../app/services/bleApi';

const api = new BleApiService();
const replayNotice = 'This result was produced from a validated bitstream replay. No IQ demodulation or RF recovery was performed.';
export const BLE_DSP_UNAVAILABLE_REASON = 'IQ-based BLE analysis is unavailable because the DSP recovery gate has not been completed. Validated bitstream replay is available for platform-integration testing.';
const BLE_PRIMARY_CHANNELS = [
  { channel: 37, frequencyMHz: 2402 },
  { channel: 38, frequencyMHz: 2426 },
  { channel: 39, frequencyMHz: 2480 },
] as const;
const surfaceStyle = { borderColor: 'var(--app-border)', background: 'var(--app-surface)' };
const Panel: React.FC<React.PropsWithChildren<{ title: string; className?: string }>> = ({ title, className = '', children }) => <section className={`overflow-hidden rounded-lg border ${className}`} style={surfaceStyle}><div className="border-b px-4 py-3 text-sm font-semibold" style={{ borderColor: 'var(--app-border)' }}>{title}</div><div className="p-4">{children}</div></section>;
const Metric = ({ label, display }: { label: string; display: React.ReactNode }) => <div className="rounded-lg border p-4" style={surfaceStyle}><div className="text-xs uppercase tracking-wide text-[var(--app-text-muted)]">{label}</div><div className="mt-1 break-all text-xl font-semibold">{display}</div></div>;
const summaryNumber = (summary: Record<string, unknown> | undefined, ...keys: string[]) => Number(keys.map((key) => summary?.[key]).find((item) => item !== undefined) ?? 0);
const JOB_PROGRESS: Record<string, number> = { created: 5, queued: 12, validating_input: 25, starting_worker: 38, running: 60, validating_artifacts: 85, cancel_requested: 90, completed: 100, completed_with_diagnostics: 100, failed: 100, timed_out: 100, cancelled: 100 };

const BleJobProgress = ({ job }: { job: BleJob }) => {
  const progress = JOB_PROGRESS[job.state] ?? 0;
  const terminal = ['completed', 'completed_with_diagnostics', 'failed', 'timed_out', 'cancelled'].includes(job.state);
  return <div className="mt-3 min-w-[18rem]">
    <div className="mb-1 flex justify-between text-xs"><span>{terminal ? 'Finished' : 'Analysis progress'}</span><b>{progress}%</b></div>
    <div className="h-2 overflow-hidden rounded-full bg-black/15"><div className={`h-full transition-all duration-500 ${job.state === 'failed' || job.state === 'timed_out' ? 'bg-red-500' : 'bg-sky-500'}`} style={{ width: `${progress}%` }} /></div>
  </div>;
};

export const BleCapabilityStatus = ({ capabilities }: { capabilities: BleCapabilities | null }) => {
  const rows = [['Bit-true primitives', 'bit_true_gate', 'passed'], ['Link Layer bitstream decoder', 'link_layer_bitstream_gate', 'passed'], ['Advertising semantic parser', 'semantic_advertising_gate', 'passed'], ['Platform integration', 'platform_integration_gate', 'in_progress'], ['IQ/DSP recovery', 'dsp_gate', 'not_started'], ['OTA validation', 'ota_validated', 'not_performed']];
  return <Panel title="Decoder readiness — not a running job"><p className="mb-2 text-xs text-[var(--app-text-muted)]">These are validation gates for the BLE decoder. They do not mean an analysis is currently running.</p><dl className="grid gap-x-6 md:grid-cols-2">{rows.map(([label, key, fallback]) => <div key={key} className="flex justify-between border-b py-2 text-sm" style={{ borderColor: 'var(--app-border)' }}><dt>{label}</dt><dd className="font-semibold">{String(capabilities?.gates[key] ?? fallback).replaceAll('_', ' ')}</dd></div>)}<div className="flex justify-between border-b py-2 text-sm" style={{ borderColor: 'var(--app-border)' }}><dt>Normative conformance</dt><dd className="font-semibold">{(capabilities?.normative_conformance ?? 'not_established').replaceAll('_', ' ')}</dd></div></dl></Panel>;
};

export const BleJobLauncher = ({ enabled, captureCapabilities, captureBusy, onCreated, onCaptureCreated }: { enabled: boolean; captureCapabilities: BleCaptureCapabilities | null; captureBusy: boolean; onCreated: (job: BleJob) => void; onCaptureCreated: (job: BleCaptureJob) => void }) => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [channel, setChannel] = useState(37);
  const [duration, setDuration] = useState(5);
  const selected = BLE_PRIMARY_CHANNELS.find((item) => item.channel === channel) ?? BLE_PRIMARY_CHANNELS[0];
  const launch = async () => { setBusy(true); setError(''); try { onCreated(await api.createReplayJob()); } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to create replay job'); } finally { setBusy(false); } };
  const captureDevice = captureCapabilities?.devices[0];
  const launchCapture = async () => {
    if (!captureDevice) return;
    setBusy(true); setError('');
    try {
      const formats = captureDevice.stream_formats ?? [];
      const sampleFormat = formats.includes('CF32') ? 'cf32_le' : formats.includes('CS16') ? 'ci16_le' : 'ci8';
      onCaptureCreated(await api.createCapture({ device_id: captureDevice.device_id, ble_channel: selected.channel, center_frequency_hz: selected.frequencyMHz * 1e6, sample_rate_sps: 4_000_000, bandwidth_hz: 2_000_000, gain_mode: 'manual', gain_db: 20, antenna: captureDevice.antenna_options.includes('RX2') ? 'RX2' : captureDevice.antenna_options[0], duration_seconds: duration, sample_format: sampleFormat, description: 'USRP B200 real IQ capture — manual dashboard action', purpose: 'interactive_experimental_capture' }));
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to start real-IQ capture'); } finally { setBusy(false); }
  };
  return <div className="contents">
    <Panel title="Capture a BLE advertising channel">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs text-[var(--app-text-muted)]">PHY<select className="h-9 rounded-md border bg-transparent px-2 text-sm" style={{ borderColor: 'var(--app-border)' }} disabled><option>LE 1M</option></select></label>
        <label className="flex flex-col gap-1 text-xs text-[var(--app-text-muted)]">Primary channel<select value={channel} onChange={(event) => setChannel(Number(event.target.value))} className="h-9 min-w-[13rem] rounded-md border bg-transparent px-2 text-sm" style={{ borderColor: 'var(--app-border)' }}>{BLE_PRIMARY_CHANNELS.map((item) => <option key={item.channel} value={item.channel}>CH{item.channel} — {item.frequencyMHz} MHz</option>)}</select></label>
        <label className="flex flex-col gap-1 text-xs text-[var(--app-text-muted)]">Duration (s)<input type="number" min={1} max={60} value={duration} onChange={(event) => setDuration(Number(event.target.value))} className="h-9 w-20 rounded-md border bg-transparent px-2 text-sm" style={{ borderColor: 'var(--app-border)' }} /></label>
        <button type="button" onClick={() => void launchCapture()} disabled={!captureCapabilities?.capture_enabled || !captureDevice || captureBusy || busy} title={!captureDevice ? 'No compatible SDR detected' : 'Starts a preserved real-IQ recording; it does not decode BLE'} className="inline-flex h-9 items-center rounded-md bg-sky-600 px-4 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"><Bluetooth className="mr-2 h-4 w-4" />{captureBusy ? 'Capturing IQ…' : 'Start Real IQ Capture'}</button>
      </div>
      <div className="mt-3 rounded-md bg-black/10 px-3 py-2 text-xs"><b>Selected RF center:</b> {selected.frequencyMHz} MHz · CH{selected.channel} · {duration}s<div className="mt-1 text-cyan-500">Manual real-IQ capture only. No BLE decoding or Gate 2A.2 analysis starts automatically.</div></div>
    </Panel>
    <Panel title="Analyze validated BLE traffic">
      <p className="mb-3 text-sm text-[var(--app-text-muted)]">Run the frozen Gate 1B campaign and inspect CRC-valid PDUs, headers, payload bytes, addresses and Advertising Data structures.</p>
      <div className="mb-3 rounded-md bg-black/10 px-3 py-2 text-xs"><span className="text-[var(--app-text-muted)]">Input mode</span><div className="mt-1 font-semibold">Validated bitstream replay · channels 37, 38 and 39</div></div>
      <button onClick={() => void launch()} disabled={!enabled || busy} className="inline-flex h-9 items-center rounded-md bg-indigo-600 px-4 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"><Play className="mr-2 h-4 w-4" />{busy ? 'Creating job...' : 'Analyze replay frames'}</button>
      {error && <p className="mt-2 text-sm text-red-400">{error}</p>}
    </Panel>
  </div>;
};

export const BleJobSummary = ({ job }: { job: BleJob }) => { const s = job.result_summary; const metrics: [string, React.ReactNode][] = [['CRC-valid packets', summaryNumber(s, 'confirmed_packet_count', 'crc_valid_packets')], ['Parsed advertising PDUs', summaryNumber(s, 'parsed_packet_count', 'parsed_advertising_pdus')], ['Advertising Data structures', summaryNumber(s, 'ad_structure_count')], ['Observed advertiser addresses', summaryNumber(s, 'advertiser_count')], ['PDU types observed', summaryNumber(s, 'pdu_type_count')], ['Channels represented', summaryNumber(s, 'channel_count')], ['CRC-invalid diagnostic candidates', summaryNumber(s, 'crc_invalid_candidate_count')], ['Duplicate publications', summaryNumber(s, 'duplicate_publications')], ['Worker commit', String(job.worker?.worker_commit ?? job.worker?.commit ?? 'Unavailable')], ['Processing duration', job.processing_duration_seconds == null ? 'Unavailable' : `${job.processing_duration_seconds}s`], ['Input mode', 'Validated bitstream replay']]; return <Panel title="Job summary"><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{metrics.map(([label, display]) => <Metric key={label} label={label} display={display} />)}</div></Panel>; };

export const BleChannelMap = ({ represented }: { represented: number[] }) => <Panel title="Channel overview"><div className="grid grid-cols-5 gap-2 sm:grid-cols-8 lg:grid-cols-10">{Array.from({ length: 40 }, (_, channel) => { const present = represented.includes(channel); return <div key={channel} title={present ? 'represented_in_test_vector' : 'not_represented_in_test_vector'} className={`rounded border p-2 text-center text-xs ${present ? 'border-cyan-400 bg-cyan-400/15' : 'border-slate-700 text-slate-500'} ${channel >= 37 ? 'ring-1 ring-amber-400' : ''}`}><b>{channel}</b><div>{present ? 'represented' : 'not represented'}</div></div>; })}</div></Panel>;
export const BlePacketDetails = ({ packet }: { packet: BlePacket }) => {
  const raw = packet as Record<string, unknown>;
  return <div className="space-y-3">
    <div className="grid grid-cols-2 gap-2 text-sm">
      <div className="rounded-md bg-black/10 px-3 py-2"><div className="text-xs text-[var(--app-text-muted)]">Access Address</div><code>{String(raw.access_address ?? 'Unknown')}</code></div>
      <div className="rounded-md bg-black/10 px-3 py-2"><div className="text-xs text-[var(--app-text-muted)]">PDU type</div><b>{String(packet.pdu_type ?? 'Unknown')}</b></div>
      <div className="rounded-md bg-black/10 px-3 py-2"><div className="text-xs text-[var(--app-text-muted)]">Channel / frequency</div><b>CH{String(packet.channel_index ?? '?')} · {BLE_PRIMARY_CHANNELS.find((item) => item.channel === Number(packet.channel_index))?.frequencyMHz ?? 'Unknown'} MHz</b></div>
      <div className="rounded-md bg-black/10 px-3 py-2"><div className="text-xs text-[var(--app-text-muted)]">CRC</div><b className="text-emerald-500">{packet.crc_valid ? 'Valid' : 'Invalid'}</b></div>
    </div>
    <div><div className="mb-1 text-xs uppercase tracking-wide text-[var(--app-text-muted)]">Complete Link Layer PDU</div><div className="max-h-32 overflow-auto break-all rounded-md bg-black/10 px-3 py-2 font-mono text-xs">{String(raw.pdu_hex ?? raw.payload_hex ?? 'Unavailable')}</div></div>
    <details><summary className="cursor-pointer text-xs font-semibold text-sky-500">All packet metadata</summary><pre className="mt-2 max-h-72 overflow-auto break-all rounded-md bg-black/10 p-3 text-xs">{JSON.stringify(packet, null, 2)}</pre></details>
  </div>;
};
export const BlePacketTable = ({ packets }: { packets: BlePacket[] }) => { const [selected, setSelected] = useState<BlePacket | null>(null); return <Panel title="Confirmed packets"><div className="overflow-auto"><table className="w-full text-left text-sm"><thead className="text-slate-400"><tr><th className="p-2">Packet ID</th><th>PDU type</th><th>Channel</th><th>CRC</th></tr></thead><tbody>{packets.map((packet, index) => <tr key={packet.packet_id ?? index} onClick={() => setSelected(packet)} className="cursor-pointer border-t border-slate-800"><td className="p-2">{packet.packet_id ?? `packet-${index + 1}`}</td><td>{packet.pdu_type ?? 'Unknown'}</td><td>{packet.channel_index ?? 'Unknown'}</td><td className={packet.crc_valid ? 'text-emerald-300' : 'text-rose-300'}>{String(packet.crc_valid)}</td></tr>)}</tbody></table></div>{selected && <BlePacketDetails packet={selected} />}</Panel>; };
export const BleAdStructureViewer = ({ structures }: { structures: unknown[] }) => <pre className="max-h-64 overflow-auto rounded bg-slate-950 p-3 text-xs">{JSON.stringify(structures, null, 2)}</pre>;
export const BleAdvertisementDetails = ({ advertisement }: { advertisement: BleAdvertisement }) => <div><p className="mb-2 text-xs text-amber-200">An observed address is not a permanent device identity.</p><BleAdStructureViewer structures={advertisement.ad_structures ?? []} /></div>;
export const BleAdvertisementTable = ({ advertisements }: { advertisements: BleAdvertisement[] }) => { const [selected, setSelected] = useState<BleAdvertisement | null>(null); return <Panel title="Advertisements">{advertisements.map((ad, index) => <button key={ad.packet_id ?? index} onClick={() => setSelected(ad)} className="mb-2 flex w-full justify-between rounded border border-slate-700 p-2 text-sm"><span>{ad.pdu_type ?? 'Unknown PDU'}</span><span className="font-mono">{ad.advertiser_address ?? 'No address'}</span></button>)}{selected && <BleAdvertisementDetails advertisement={selected} />}</Panel>; };
export const BleAdvertiserTable = ({ advertisers }: { advertisers: BleAdvertiser[] }) => <Panel title="Observed advertiser addresses"><p className="mb-2 text-xs text-amber-200">Addresses are observations, not stable device identities.</p>{advertisers.map((advertiser, index) => <div key={`${advertiser.address}-${index}`} className="flex justify-between border-t border-slate-800 py-2 text-sm"><code>{advertiser.address ?? 'Unknown'}</code><span>{advertiser.address_type ?? 'unknown type'} · {advertiser.packet_count ?? 0}</span></div>)}</Panel>;
export const BleReceiverPipeline = ({ events }: { events: BleJobEvent[] }) => <Panel title="Receiver / job pipeline"><ol>{events.map((event, index) => <li key={event.sequence ?? index} className="mb-2 text-sm"><code className="mr-3 text-cyan-300">#{event.sequence ?? index + 1}</code>{event.previous_state ?? 'start'} → <b>{event.new_state ?? 'unknown'}</b> · {event.reason ?? 'no reason supplied'}</li>)}</ol></Panel>;
export const BleDiagnostics = ({ diagnostics }: { diagnostics: unknown }) => <Panel title="Diagnostics"><pre className="max-h-64 overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(diagnostics, null, 2)}</pre></Panel>;
export const BleKnownLimitations = () => <Panel title="Known limitations"><ul className="list-disc space-y-2 pl-5 text-sm text-slate-300"><li>{BLE_DSP_UNAVAILABLE_REASON}</li><li>RSSI, SNR, CFO, RF bursts, sample coverage and timing lock: Unavailable — DSP not implemented.</li><li>OTA validation: Not performed. Normative conformance: Not established.</li><li>Replay timestamps are sequence-derived, never RF timestamps.</li></ul></Panel>;
export const BleArtifactDownloads = ({ jobId, artifacts }: { jobId: string; artifacts: unknown }) => <Panel title="Artifacts"><a href={api.bundleUrl(jobId)} className="inline-flex items-center gap-2 rounded bg-slate-700 px-3 py-2 text-sm"><Download className="h-4 w-4" />Download reproducible bundle</a><pre className="mt-3 max-h-44 overflow-auto text-xs">{JSON.stringify(artifacts, null, 2)}</pre></Panel>;
export const BleWorkerProvenance = ({ capabilities, job }: { capabilities: BleCapabilities | null; job?: BleJob }) => <Panel title="Worker provenance"><div className="grid gap-2 text-sm md:grid-cols-2"><div>Frozen worker commit: <code>{capabilities?.worker_commit ?? 'Unavailable'}</code></div><div>Scientific status: <b>{capabilities?.scientific_status ?? 'BLE_P0_INCOMPLETE'}</b></div><div>Capability: <b>{capabilities?.capability_status ?? 'experimental'}</b></div><div>Job: <b>{job?.job_id ?? 'No job selected'}</b></div></div></Panel>;

// ── Gate 2A.2 -- experimental IQ recovery, separate from Gate 1B above ──────
// Every panel below must keep reading live status/results from the backend;
// none of these numbers are hardcoded, and none of this is ever framed as
// approved, frozen, or validated.

const GATE2A2_CHANNELS = [37, 38, 39] as const;
export const CAPTURE_AND_DECODE_DISABLED_REASON = 'Disabled because Receiver Candidate B is not frozen and OTA validation has not been completed.';
const GATE2A2_JOB_TERMINAL = ['completed', 'cancelled', 'failed', 'timed_out'];

export const Gate2a2StatusPanel = ({ status }: { status: BleGate2a2Status | null }) => {
  if (!status) return <Panel title="Gate 2A.2 status">Loading…</Panel>;
  if (!status.available) {
    return <Panel title="Gate 2A.2 status"><p className="text-sm text-amber-500">Status unavailable: {status.reason ?? 'unknown'}</p></Panel>;
  }
  const sweep = status.development_timing_sweep;
  const rows: [string, string][] = [
    ['Gate 2A.1', status.gate_2a1_status ?? 'unknown'],
    ['Gate 2A.2', status.gate_2a2_status ?? 'unknown'],
    ['DSP gate', status.dsp_gate ?? 'unknown'],
    ['Receiver candidate', status.receiver_candidate ?? 'unknown'],
    ['Candidate frozen', String(status.candidate_frozen ?? false)],
    ['Development timing sweep', `${sweep?.byte_exact ?? '?'} / ${sweep?.cases ?? '?'} (${sweep?.result ?? 'unknown'})`],
    ['Residual failures', String(status.residual_failures ?? 'unknown')],
    ['Holdout B created', String(status.holdout_b_created ?? false)],
    ['IQ recovery validated', String(status.iq_recovery_validated ?? false)],
    ['OTA validated', String(status.ota_validated ?? false)],
    ['Worker repository commit', status.worker_repository_commit ?? 'unknown'],
    ['Receiver commit', status.receiver_commit ?? 'unknown'],
  ];
  return (
    <Panel title="Gate 2A.2 status — experimental, not approved">
      <dl className="grid gap-x-6 md:grid-cols-2">
        {rows.map(([label, value]) => (
          <div key={label} className="flex justify-between border-b py-2 text-sm" style={{ borderColor: 'var(--app-border)' }}>
            <dt>{label}</dt><dd className="break-all font-mono font-semibold">{value}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-xs text-amber-500">{status.disabled_reason}</p>
    </Panel>
  );
};

export const AnalyzeIqFilePanel = ({ enabled, disabledReason, onCreated }: { enabled: boolean; disabledReason?: string; onCreated: (job: BleGate2a2Job) => void }) => {
  const [path, setPath] = useState('');
  const [channel, setChannel] = useState<number>(38);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const launch = async () => {
    if (!path.trim()) { setError('Enter a local cf32_le IQ file path first.'); return; }
    setBusy(true); setError('');
    try {
      onCreated(await api.createGate2a2Job({ iq_file_path: path.trim(), channel_index: channel }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to start analysis');
    } finally {
      setBusy(false);
    }
  };
  return (
    <Panel title="Analyze IQ file — experimental offline analysis">
      <p className="mb-3 text-xs font-semibold text-amber-500">
        Experimental offline IQ analysis. Receiver Candidate B is not frozen. Not validated for OTA reception. Results may contain decoding errors.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex min-w-[18rem] flex-1 flex-col gap-1 text-xs text-[var(--app-text-muted)]">
          IQ file path (cf32_le, 4 MS/s)
          <input value={path} onChange={(event) => setPath(event.target.value)} placeholder="C:\path\to\capture.cf32" className="h-9 rounded-md border bg-transparent px-2 text-sm" style={{ borderColor: 'var(--app-border)' }} />
        </label>
        <label className="flex flex-col gap-1 text-xs text-[var(--app-text-muted)]">
          Primary channel
          <select value={channel} onChange={(event) => setChannel(Number(event.target.value))} className="h-9 rounded-md border bg-transparent px-2 text-sm" style={{ borderColor: 'var(--app-border)' }}>
            {GATE2A2_CHANNELS.map((item) => <option key={item} value={item}>CH{item}</option>)}
          </select>
        </label>
        <button
          type="button"
          onClick={() => void launch()}
          disabled={!enabled || busy}
          title={!enabled ? disabledReason : undefined}
          className="inline-flex h-9 items-center rounded-md bg-sky-600 px-4 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Play className="mr-2 h-4 w-4" />{busy ? 'Starting…' : 'Analyze IQ File'}
        </button>
      </div>
      {!enabled && <p className="mt-2 text-xs text-amber-500">{disabledReason ?? 'Disabled.'}</p>}
      {error && <p className="mt-2 text-sm text-red-400">{error}</p>}
    </Panel>
  );
};

export const Gate2a2CandidateTable = ({ candidates }: { candidates: BleGate2a2Candidate[] }) => {
  const [selected, setSelected] = useState<BleGate2a2Candidate | null>(null);
  return (
    <Panel title={`Recovered candidates (${candidates.length})`}>
      <div className="overflow-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-slate-400"><tr><th className="p-2">Trace ID</th><th>Channel</th><th>Winning hypothesis</th><th>Hypotheses evaluated</th><th>CFO (Hz)</th></tr></thead>
          <tbody>
            {candidates.map((candidate, index) => (
              <tr key={String(candidate.receiver_trace_id ?? index)} onClick={() => setSelected(candidate)} className="cursor-pointer border-t border-slate-800">
                <td className="p-2 font-mono text-xs">{String(candidate.receiver_trace_id ?? index)}</td>
                <td>{candidate.channel_index ?? 'Unknown'}</td>
                <td>{candidate.winning_timing_hypothesis_id ?? 'Unknown'}</td>
                <td>{candidate.timing_hypotheses_evaluated ?? 0}</td>
                <td>{typeof candidate.estimated_cfo_hz === 'number' ? candidate.estimated_cfo_hz.toFixed(1) : 'Unknown'}</td>
              </tr>
            ))}
            {candidates.length === 0 && <tr><td colSpan={5} className="p-4 text-center text-[var(--app-text-muted)]">No candidates recovered for this job.</td></tr>}
          </tbody>
        </table>
      </div>
      {selected && (
        <div className="mt-3 space-y-2 text-sm">
          <div className="rounded-md bg-black/10 px-3 py-2">
            <div className="text-xs text-[var(--app-text-muted)]">Winning hypothesis / evaluated / losing hypotheses</div>
            <div className="break-all font-mono">{selected.winning_timing_hypothesis_id} / {selected.timing_hypotheses_evaluated} / {(selected.merged_timing_hypothesis_ids ?? []).join(', ') || 'none'}</div>
          </div>
          <div className="rounded-md bg-black/10 px-3 py-2">
            <div className="text-xs text-[var(--app-text-muted)]">Estimated CFO / timing phase (input samples)</div>
            <div className="font-mono">{selected.estimated_cfo_hz?.toFixed(1) ?? 'Unknown'} Hz / {selected.estimated_timing_phase?.toFixed(4) ?? 'Unknown'}</div>
          </div>
        </div>
      )}
    </Panel>
  );
};

export const Gate2a2ConfirmedPacketsPanel = ({ packets }: { packets: BleGate2a2ConfirmedPacket[] }) => (
  <Panel title={`Confirmed packets from this analysis (${packets.length})`}>
    <p className="mb-2 text-xs text-[var(--app-text-muted)]">
      These passed the same frozen Gate 1A/1B CRC check Gate 1B trusts — only the DSP front end that produced the candidate bits is experimental.
    </p>
    <table className="w-full text-left text-sm">
      <thead className="text-slate-400"><tr><th className="p-2">PDU type</th><th>Channel</th><th>CRC</th></tr></thead>
      <tbody>
        {packets.map((packet, index) => (
          <tr key={packet.packet_sha256 ?? index} className="border-t border-slate-800">
            <td className="p-2">{packet.pdu_type_name ?? 'Unknown'}</td>
            <td>{packet.channel_index ?? 'Unknown'}</td>
            <td className={packet.crc_valid ? 'text-emerald-300' : 'text-rose-300'}>{String(packet.crc_valid)}</td>
          </tr>
        ))}
        {packets.length === 0 && <tr><td colSpan={3} className="p-4 text-center text-[var(--app-text-muted)]">No confirmed packets.</td></tr>}
      </tbody>
    </table>
  </Panel>
);

const Trace = ({ values, color }: { values: number[]; color: string }) => { if(values.length<2)return <div className="flex h-32 items-center justify-center text-xs text-[var(--app-text-muted)]">Waiting for real SDR samples…</div>; const lo=Math.min(...values), hi=Math.max(...values), span=Math.max(1e-9,hi-lo); const points=values.map((v,i)=>`${i*100/(values.length-1)},${100-(v-lo)*100/span}`).join(' '); return <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="h-32 w-full bg-black/20"><polyline points={points} fill="none" stroke={color} strokeWidth="1" vectorEffect="non-scaling-stroke" /></svg>; };
const LiveHistory = ({ live }: { live: BleCaptureLive|null }) => { const [rows,setRows]=useState<number[][]>([]),[power,setPower]=useState<number[]>([]); useEffect(()=>{if(!live?.spectrum_dbfs?.length)return;setRows(old=>[...old.slice(-39),live.spectrum_dbfs!]);if(typeof live.average_power_dbfs==='number')setPower(old=>[...old.slice(-119),live.average_power_dbfs!]);},[live?.timestamp_utc]); return <div className="grid gap-4 xl:grid-cols-2"><Panel title="Live waterfall — time / frequency / dBFS"><div className="h-40 overflow-hidden rounded bg-black">{rows.map((row,i)=><div key={i} className="flex h-1" title={live?.timestamp_utc}>{row.filter((_,x)=>x%4===0).map((v,x)=>{const level=Math.max(0,Math.min(1,(v+120)/120));return <span key={x} className="h-full flex-1" style={{backgroundColor:`hsl(${240-level*240} 90% ${15+level*45}%)`}}/>;})}</div>)}</div></Panel><Panel title="Temporal average power"><Trace values={power} color="#f59e0b" /></Panel></div>; };

export const RealIqCapture = ({ capabilities, job, live, records, onJob, onOpen, refresh }: { capabilities: BleCaptureCapabilities|null; job: BleCaptureJob|null; live: BleCaptureLive|null; records: BleCaptureRecord[]; onJob:(job:BleCaptureJob)=>void; onOpen:(id:string)=>Promise<void>; refresh:()=>Promise<void> }) => {
  const [channel,setChannel]=useState(37),[duration,setDuration]=useState(3),[gain,setGain]=useState(20),[rate,setRate]=useState(4_000_000),[bandwidth,setBandwidth]=useState(2_000_000),[format,setFormat]=useState('cf32_le'),[antenna,setAntenna]=useState('RX2'),[error,setError]=useState(''); const device=capabilities?.devices[0];
  useEffect(()=>{if(!device)return;const rates=device.sample_rate_ranges_sps.flatMap(x=>x.minimum===x.maximum?[x.minimum]:[x.minimum,x.maximum]);if(rates.length)setRate(rates.reduce((best,x)=>Math.abs(x-4_000_000)<Math.abs(best-4_000_000)?x:best));if(device.antenna_options.length)setAntenna(device.antenna_options.includes('RX2')?'RX2':device.antenna_options[0]);const formats=device.stream_formats??[];setFormat(formats.includes('CF32')?'cf32_le':formats.includes('CS16')?'ci16_le':'ci8');},[device?.device_id]);
  const start=async()=>{if(!device)return;setError('');try{const frequency=BLE_PRIMARY_CHANNELS.find(x=>x.channel===channel)?.frequencyMHz??2402;onJob(await api.createCapture({device_id:device.device_id,ble_channel:channel,center_frequency_hz:frequency*1e6,sample_rate_sps:rate,bandwidth_hz:bandwidth,gain_mode:'manual',gain_db:gain,antenna,duration_seconds:duration,sample_format:format,description:'USRP B200 real IQ capture — experimental',purpose:'interactive_experimental_capture'}));}catch(reason){setError(reason instanceof Error?reason.message:'Capture failed');}};
  const active=job&&!['completed','failed','cancelled','timed_out'].includes(job.state);
  return <div className="space-y-4"><Panel title="Capture Real IQ — Experimental capture">
    {!capabilities?.available&&<div className="mb-3 rounded bg-amber-500/10 p-3 text-sm text-amber-500"><b>{capabilities?.reason_code??'DETECTING_SDR'}</b> — {capabilities?.message??'Detecting compatible SDR.'}</div>}
    {capabilities?.available&&!capabilities.capture_enabled&&<div className="mb-3 rounded border border-sky-400/30 bg-sky-500/10 p-3 text-sm text-sky-200"><b>USRP B200 detected.</b> Real-IQ capture is disabled in this already-running backend process. Restart the normal laboratory launcher to apply the new default. No capture starts until you press <b>Capture Real IQ</b>; Capture and Decode BLE remains disabled.</div>}
    {capabilities?.available&&capabilities.capture_enabled&&<div className="mb-3 rounded border border-emerald-400/30 bg-emerald-500/10 p-3 text-sm text-emerald-200"><b>USRP B200 ready.</b> Experimental real-IQ capture is enabled. BLE decoding is not started automatically.</div>}
    <div className="flex flex-wrap items-end gap-3"><label className="text-xs">SDR<select disabled className="mt-1 block h-9 min-w-48 rounded border bg-transparent px-2"><option>{device?`${device.label} (${device.driver})`:'No compatible SDR'}</option></select></label><label className="text-xs">Channel<select value={channel} onChange={e=>setChannel(Number(e.target.value))} className="mt-1 block h-9 rounded border bg-transparent px-2">{BLE_PRIMARY_CHANNELS.map(x=><option key={x.channel} value={x.channel}>CH{x.channel} — {x.frequencyMHz} MHz</option>)}</select></label><label className="text-xs">Rate<input type="number" value={rate} onChange={e=>setRate(Number(e.target.value))} className="mt-1 block h-9 w-28 rounded border bg-transparent px-2" /></label><label className="text-xs">Bandwidth<input type="number" value={bandwidth} onChange={e=>setBandwidth(Number(e.target.value))} className="mt-1 block h-9 w-28 rounded border bg-transparent px-2" /></label><label className="text-xs">Format<select value={format} onChange={e=>setFormat(e.target.value)} className="mt-1 block h-9 rounded border bg-transparent px-2"><option value="cf32_le">cf32_le</option><option value="ci16_le">ci16_le</option><option value="ci8">ci8</option></select></label><label className="text-xs">Antenna<select value={antenna} onChange={e=>setAntenna(e.target.value)} className="mt-1 block h-9 rounded border bg-transparent px-2">{(device?.antenna_options??[]).map(x=><option key={x}>{x}</option>)}</select></label><label className="text-xs">Duration s<input type="number" min={1} max={60} value={duration} onChange={e=>setDuration(Number(e.target.value))} className="mt-1 block h-9 w-20 rounded border bg-transparent px-2" /></label><label className="text-xs">Gain dB<input type="number" value={gain} onChange={e=>setGain(Number(e.target.value))} className="mt-1 block h-9 w-20 rounded border bg-transparent px-2" /></label><button disabled={!capabilities?.capture_enabled||!device||Boolean(active)} onClick={()=>void start()} className="h-9 rounded bg-sky-600 px-4 text-sm font-semibold text-white disabled:opacity-40">Capture Real IQ</button>{active&&<button onClick={async()=>onJob(await api.cancelCapture(job.capture_id))} className="h-9 rounded bg-red-600 px-4 text-sm text-white">Stop</button>}<button onClick={()=>void refresh()} className="h-9 rounded border px-3 text-sm">Refresh</button></div>
    <div className="mt-2 text-xs text-[var(--app-text-muted)]">Profile derived from {device?.label??'the detected SDR'} capabilities: {format} · {rate} S/s · {bandwidth} Hz · {antenna||'default antenna'}. Capture is preserved before optional analysis.</div>{job&&<div className="mt-2 text-sm"><code>{job.capture_id}</code> · {job.state} {job.error&&<span className="text-red-400">· {job.error}</span>}</div>}{error&&<div className="mt-2 text-red-400">{error}</div>}
  </Panel><div className="grid gap-4 xl:grid-cols-3"><Panel title="Live spectrum (dBFS)"><Trace values={live?.spectrum_dbfs??[]} color="#38bdf8" /></Panel><Panel title="I component"><Trace values={live?.i_preview??[]} color="#34d399" /></Panel><Panel title="Q component"><Trace values={live?.q_preview??[]} color="#f472b6" /></Panel></div><LiveHistory live={live} />
  <Panel title="Capture telemetry"><div className="grid gap-2 sm:grid-cols-4 lg:grid-cols-8">{[['Samples',live?.samples_received],['Bytes',live?.bytes_written],['Overflows',live?.stream_overflows],['Discontinuities',live?.input_discontinuities],['Average dBFS',live?.average_power_dbfs?.toFixed(2)],['Peak dBFS',live?.peak_power_dbfs?.toFixed(2)],['Clipping %',live?.clipping_percentage?.toFixed(3)],['UTC',live?.timestamp_utc]].map(([k,v])=><div key={String(k)} className="rounded border p-2 text-xs"><div className="text-[var(--app-text-muted)]">{k}</div><b>{String(v??'Unavailable')}</b></div>)}</div></Panel>
  <Panel title="Real IQ Captures"><div className="overflow-auto"><table className="w-full text-left text-sm"><thead><tr><th>ID</th><th>UTC</th><th>Channel</th><th>Sample rate</th><th>Size</th><th>Integrity</th><th>Actions</th></tr></thead><tbody>{records.map(r=><tr key={r.capture_id} className="border-t"><td className="py-2 font-mono">{r.capture_id}</td><td>{r.created_at_utc}</td><td>CH{r.ble_channel??'?'}</td><td>{r.sample_rate_sps}</td><td>{r.actual_size_bytes}</td><td>{r.capture_complete?`complete · ${r.overflow_count} overflow`:'incomplete'}</td><td className="space-x-2"><button onClick={()=>void onOpen(r.capture_id)} className="text-cyan-500">Open</button><a href={api.captureMetaUrl(r.capture_id)} className="text-sky-500">Metadata</a><button onClick={async()=>window.alert(JSON.stringify(await api.verifyCapture(r.capture_id)))} className="text-emerald-500">Verify</button></td></tr>)}</tbody></table>{records.length===0&&<p className="p-4 text-center text-[var(--app-text-muted)]">No preserved real IQ captures.</p>}</div><p className="mt-2 text-xs text-amber-500">These are preserved real RF samples. The dashboard does not claim that visible activity is a decoded BLE frame.</p></Panel></div>;
};

export const Gate2a2DisabledCaptureButtons = () => (
  <Panel title="Automatic capture and decode remains unavailable">
    <div className="flex flex-wrap gap-3">
      <button type="button" disabled title={CAPTURE_AND_DECODE_DISABLED_REASON} className="inline-flex h-9 cursor-not-allowed items-center rounded-md bg-slate-700 px-4 text-sm font-semibold opacity-50">
        <Bluetooth className="mr-2 h-4 w-4" />Capture and Decode BLE
      </button>
    </div>
    <p className="text-xs text-[var(--app-text-muted)]">{CAPTURE_AND_DECODE_DISABLED_REASON}</p>
  </Panel>
);

export const BleLabView: React.FC = () => {
  const { jobId } = useParams(); const navigate = useNavigate(); const [capabilities, setCapabilities] = useState<BleCapabilities | null>(null); const [job, setJob] = useState<BleJob | null>(null); const [packets, setPackets] = useState<BlePacket[]>([]); const [advertisements, setAdvertisements] = useState<BleAdvertisement[]>([]); const [advertisers, setAdvertisers] = useState<BleAdvertiser[]>([]); const [events, setEvents] = useState<BleJobEvent[]>([]); const [channels, setChannels] = useState<unknown>([]); const [diagnostics, setDiagnostics] = useState<unknown>([]); const [artifacts, setArtifacts] = useState<unknown>([]); const [error, setError] = useState('');
  const load = async () => { setError(''); try { setCapabilities(await api.capabilities()); if (!jobId) return; setJob(await api.job(jobId)); const results = await Promise.allSettled([api.packets(jobId), api.advertisements(jobId), api.advertisers(jobId), api.resource<unknown>(jobId, 'channels'), api.resource<BleJobEvent[]>(jobId, 'events'), api.resource<unknown>(jobId, 'diagnostics'), api.resource<unknown>(jobId, 'artifacts')]); const item = <T,>(index: number, fallback: T) => results[index].status === 'fulfilled' ? (results[index] as PromiseFulfilledResult<T>).value : fallback; setPackets(item(0, [])); setAdvertisements(item(1, [])); setAdvertisers(item(2, [])); setChannels(item(3, [])); setEvents(item(4, [])); setDiagnostics(item(5, [])); setArtifacts(item(6, [])); } catch (reason) { setError(reason instanceof Error ? reason.message : 'BLE API unavailable'); } };
  useEffect(() => { void load(); }, [jobId]);
  useEffect(() => {
    if (!jobId || !job || ['completed', 'completed_with_diagnostics', 'failed', 'timed_out', 'cancelled'].includes(job.state)) return;
    const timer = window.setInterval(() => void load(), 750);
    return () => window.clearInterval(timer);
  }, [jobId, job?.state]);
  const represented = useMemo(() => (Array.isArray(channels) ? channels : []).map((entry) => typeof entry === 'number' ? entry : Number((entry as Record<string, unknown>).channel_index ?? (entry as Record<string, unknown>).channel)).filter(Number.isFinite), [channels]);
  const active = job && ['created', 'queued', 'validating_input', 'starting_worker', 'running', 'validating_artifacts', 'cancel_requested'].includes(job.state);

  // ── Gate 2A.2 -- entirely separate state, never mixed with Gate 1B above ──
  const [gate2a2Status, setGate2a2Status] = useState<BleGate2a2Status | null>(null);
  const [gate2a2Job, setGate2a2Job] = useState<BleGate2a2Job | null>(null);
  const [gate2a2Candidates, setGate2a2Candidates] = useState<BleGate2a2Candidate[]>([]);
  const [gate2a2ConfirmedPackets, setGate2a2ConfirmedPackets] = useState<BleGate2a2ConfirmedPacket[]>([]);
  const [captureCapabilities,setCaptureCapabilities]=useState<BleCaptureCapabilities|null>(null),[captureJob,setCaptureJob]=useState<BleCaptureJob|null>(null),[captureLive,setCaptureLive]=useState<BleCaptureLive|null>(null),[captureRecords,setCaptureRecords]=useState<BleCaptureRecord[]>([]);
  const loadCapture=async()=>{try{const [caps,records]=await Promise.all([api.captureCapabilities(),api.captures()]);setCaptureCapabilities(caps);setCaptureRecords(records);}catch{setCaptureCapabilities({available:false,capture_enabled:false,capture_and_decode_enabled:false,reason_code:'CAPTURE_API_UNAVAILABLE',message:'Capture API unavailable.',devices:[],default_duration_seconds:10,maximum_duration_seconds:60,supported_formats:[],ble_channels:{}});}};
  const loadGate2a2Status = async () => { try { setGate2a2Status(await api.gate2a2Status()); } catch { setGate2a2Status({ available: false, reason: 'gate2a2_api_unavailable' }); } };
  useEffect(() => { void loadGate2a2Status(); }, []);
  useEffect(()=>{void loadCapture();},[]);
  useEffect(()=>{if(!captureJob||['completed','failed','cancelled','timed_out'].includes(captureJob.state))return;const timer=window.setInterval(async()=>{const next=await api.captureJob(captureJob.capture_id);setCaptureJob(next);setCaptureLive(await api.captureLive(next.capture_id));if(['completed','failed','cancelled','timed_out'].includes(next.state))await loadCapture();},500);return()=>window.clearInterval(timer);},[captureJob?.capture_id,captureJob?.state]);
  useEffect(() => {
    if (!gate2a2Job || GATE2A2_JOB_TERMINAL.includes(gate2a2Job.state)) return;
    const timer = window.setInterval(async () => {
      const next = await api.gate2a2Job(gate2a2Job.job_id);
      setGate2a2Job(next);
      if (GATE2A2_JOB_TERMINAL.includes(next.state) && next.state === 'completed') {
        setGate2a2Candidates(await api.gate2a2Candidates(next.job_id));
        setGate2a2ConfirmedPackets(await api.gate2a2ConfirmedPackets(next.job_id));
      }
    }, 750);
    return () => window.clearInterval(timer);
  }, [gate2a2Job?.job_id, gate2a2Job?.state]);
  const operatorDashboard = true;
  if (operatorDashboard) return (
    <div className="h-full overflow-auto bg-[var(--app-bg)] p-6 text-[var(--app-text)]">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.18em] text-sky-500"><Bluetooth className="h-4 w-4" />Real RF acquisition</div>
          <h1 className="text-2xl font-semibold">Bluetooth LE Capture</h1>
          <p className="mt-1 text-sm text-[var(--app-text-muted)]">USRP B200 · LE 1M advertising channels · manual operation</p>
        </div>
        <button type="button" onClick={() => void loadCapture()} className="inline-flex h-9 items-center gap-2 rounded-md border px-3 text-sm font-medium" style={{ borderColor: 'var(--app-border)' }}><RefreshCw className="h-4 w-4" />Refresh SDR</button>
      </div>

      <Panel title="How to make a BLE-channel recording">
        <ol className="grid gap-3 lg:grid-cols-5">
          {[
            ['1', 'Prepare', 'Connect the USRP B200 and its RX antenna. Do not transmit through the B200.'],
            ['2', 'Select', 'Choose advertising channel 37, 38 or 39, duration and conservative RX gain.'],
            ['3', 'Capture', 'Press Capture Real IQ. Nothing starts before this manual action.'],
            ['4', 'Monitor', 'Wait for completion while watching spectrum, I/Q, waterfall and telemetry.'],
            ['5', 'Review', 'Open the saved recording and use Verify to check its data and metadata hashes.'],
          ].map(([number,title,description])=><li key={number} className="rounded-lg border p-4" style={{ borderColor:'var(--app-border)' }}><div className="mb-2 flex h-7 w-7 items-center justify-center rounded-full bg-sky-600 text-sm font-bold text-white">{number}</div><div className="font-semibold">{title}</div><p className="mt-1 text-xs leading-5 text-[var(--app-text-muted)]">{description}</p></li>)}
        </ol>
      </Panel>

      <div className="my-6 rounded-md border border-amber-400/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
        <AlertTriangle className="mr-2 inline h-4 w-4" /><b>Current scope:</b> this page records and visualizes real IQ. It does not yet present RF activity as decoded BLE frames. Automatic Capture and Decode remains unavailable until its receiver and OTA validation are complete.
      </div>

      <RealIqCapture capabilities={captureCapabilities} job={captureJob} live={captureLive} records={captureRecords} onJob={setCaptureJob} onOpen={async(id)=>setCaptureLive(await api.captureLive(id))} refresh={loadCapture} />
    </div>
  );
  return (
    <div className="h-full overflow-auto bg-[var(--app-bg)] p-6 text-[var(--app-text)]">
      <div className="mb-6 flex items-center justify-between gap-4">
        <div>
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.18em] text-sky-500">
            <Bluetooth className="h-4 w-4" /> Experimental passive analyzer
          </div>
          <h1 className="text-2xl font-semibold">Bluetooth LE Analysis</h1>
          <p className="mt-1 text-sm text-[var(--app-text-muted)]">LE 1M primary advertising</p>
        </div>
        <div className="flex gap-2">
          {jobId && <Link to="/ble-lab" className="inline-flex h-9 items-center rounded-md border px-3 text-sm font-medium" style={{ borderColor: 'var(--app-border)' }}>BLE Lab home</Link>}
          <button type="button" onClick={() => void load()} className="inline-flex h-9 w-9 items-center justify-center rounded-md border" style={{ borderColor: 'var(--app-border)' }} title="Refresh"><RefreshCw className="h-4 w-4" /></button>
        </div>
      </div>

      {error && <div className="mb-4 rounded-md border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">{error}</div>}

      <div className="mb-3 text-sm font-semibold uppercase tracking-[0.18em] text-emerald-500">Validated bitstream replay — Gate 1B</div>
      <div className="mb-6 rounded-md border border-amber-400/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-500">
        <AlertTriangle className="mr-2 inline h-4 w-4" />{replayNotice}
      </div>

      <div className="mb-6 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <BleJobLauncher enabled={Boolean(capabilities?.enabled)} captureCapabilities={captureCapabilities} captureBusy={Boolean(captureJob&&!['completed','failed','cancelled','timed_out'].includes(captureJob.state))} onCreated={(created) => navigate(`/ble-lab/jobs/${created.job_id}`)} onCaptureCreated={setCaptureJob} />
        <BleCapabilityStatus capabilities={capabilities} />
      </div>

      {job ? <>
        <section className="mb-6 flex flex-wrap items-center justify-between gap-4 rounded-lg border p-4" style={surfaceStyle}>
          <div className="flex items-center gap-3">
            <CheckCircle2 className={`h-5 w-5 ${job.state === 'completed' ? 'text-emerald-500' : 'text-amber-500'}`} />
            <div><div className="text-xs uppercase tracking-wide text-[var(--app-text-muted)]">Current analysis</div><code className="font-semibold">{job.job_id}</code> <span className="ml-2 text-sm">{job.state.replaceAll('_', ' ')}</span><BleJobProgress job={job} /></div>
          </div>
          <div>{active && <button onClick={async () => setJob(await api.cancel(job.job_id))} className="mr-2 inline-flex h-9 items-center gap-2 rounded-md bg-red-600 px-3 text-sm font-semibold text-white"><Square className="h-4 w-4" />Cancel</button>}{['failed', 'timed_out', 'cancelled'].includes(job.state) && <button onClick={async () => { const next = await api.retry(job.job_id); navigate(`/ble-lab/jobs/${next.job_id}`); }} className="inline-flex h-9 items-center gap-2 rounded-md bg-amber-500 px-3 text-sm font-semibold text-slate-950"><RotateCcw className="h-4 w-4" />Retry</button>}</div>
        </section>
        <div className="mb-6"><BleJobSummary job={job} /></div>
        <div className="mb-6"><BleChannelMap represented={represented} /></div>
        <div className="mb-6 grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1.45fr)_minmax(20rem,0.75fr)]">
          <BlePacketTable packets={packets} />
          <div className="space-y-6"><BleAdvertisementTable advertisements={advertisements} /><BleAdvertiserTable advertisers={advertisers} /></div>
        </div>
        <div className="mb-6 grid gap-6 xl:grid-cols-2"><BleReceiverPipeline events={events} /><BleDiagnostics diagnostics={diagnostics} /></div>
        <div className="mb-6"><BleArtifactDownloads jobId={job.job_id} artifacts={artifacts} /></div>
      </> : <div className="mb-6 rounded-lg border border-dashed p-8 text-center" style={{ borderColor: 'var(--app-border)' }}><div className="text-base font-semibold">No BLE analysis is running</div><div className="mt-1 text-sm text-[var(--app-text-muted)]">Choose a channel for the future IQ capture workflow, or press “Analyze replay frames” to launch the validated decoder test.</div></div>}

      <div className="mb-10 grid gap-6 xl:grid-cols-2"><BleWorkerProvenance capabilities={capabilities} job={job ?? undefined} /><BleKnownLimitations /></div>

      <div className="mb-3 text-sm font-semibold uppercase tracking-[0.18em] text-cyan-500">Real IQ capture and visualization</div>
      <div className="mb-8"><RealIqCapture capabilities={captureCapabilities} job={captureJob} live={captureLive} records={captureRecords} onJob={setCaptureJob} onOpen={async(id)=>setCaptureLive(await api.captureLive(id))} refresh={loadCapture} /></div>

      <div className="mb-3 text-sm font-semibold uppercase tracking-[0.18em] text-sky-500">Experimental IQ recovery — Gate 2A.2</div>
      <div className="mb-6 rounded-md border border-amber-400/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-500">
        <AlertTriangle className="mr-2 inline h-4 w-4" />
        Experimental offline IQ analysis. Receiver Candidate B is not frozen. Not validated for OTA reception. Results may contain decoding errors.
      </div>

      <div className="mb-6 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Gate2a2StatusPanel status={gate2a2Status} />
        <AnalyzeIqFilePanel
          enabled={Boolean(gate2a2Status?.available)}
          disabledReason={gate2a2Status?.disabled_reason ?? gate2a2Status?.reason}
          onCreated={setGate2a2Job}
        />
      </div>

      {gate2a2Job && (
        <section className="mb-6 flex flex-wrap items-center justify-between gap-4 rounded-lg border p-4" style={surfaceStyle}>
          <div className="flex items-center gap-3">
            <CheckCircle2 className={`h-5 w-5 ${gate2a2Job.state === 'completed' ? 'text-emerald-500' : 'text-amber-500'}`} />
            <div>
              <div className="text-xs uppercase tracking-wide text-[var(--app-text-muted)]">Current offline analysis</div>
              <code className="font-semibold">{gate2a2Job.job_id}</code> <span className="ml-2 text-sm">{gate2a2Job.state.replaceAll('_', ' ')}</span>
              {gate2a2Job.error && <div className="mt-1 text-sm text-red-400">{gate2a2Job.error}</div>}
            </div>
          </div>
          {!GATE2A2_JOB_TERMINAL.includes(gate2a2Job.state) && (
            <button onClick={async () => setGate2a2Job(await api.cancelGate2a2Job(gate2a2Job.job_id))} className="inline-flex h-9 items-center gap-2 rounded-md bg-red-600 px-3 text-sm font-semibold text-white">
              <Square className="h-4 w-4" />Cancel
            </button>
          )}
        </section>
      )}

      {gate2a2Job?.state === 'completed' && (
        <>
          <div className="mb-6"><Gate2a2CandidateTable candidates={gate2a2Candidates} /></div>
          <div className="mb-6"><Gate2a2ConfirmedPacketsPanel packets={gate2a2ConfirmedPackets} /></div>
          <div className="mb-6">
            <a href={api.gate2a2BundleUrl(gate2a2Job.job_id)} className="inline-flex items-center gap-2 rounded bg-slate-700 px-3 py-2 text-sm"><Download className="h-4 w-4" />Download reproducible bundle</a>
          </div>
        </>
      )}

      <div className="mb-6"><Gate2a2DisabledCaptureButtons /></div>
    </div>
  );
};
