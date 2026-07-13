import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Bluetooth, CheckCircle2, Download, Play, RefreshCw, RotateCcw, Square } from 'lucide-react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { BleAdvertisement, BleAdvertiser, BleApiService, BleCapabilities, BleJob, BleJobEvent, BlePacket } from '../../../app/services/bleApi';

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

export const BleJobLauncher = ({ enabled, onCreated }: { enabled: boolean; onCreated: (job: BleJob) => void }) => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [channel, setChannel] = useState(37);
  const [duration, setDuration] = useState(5);
  const selected = BLE_PRIMARY_CHANNELS.find((item) => item.channel === channel) ?? BLE_PRIMARY_CHANNELS[0];
  const launch = async () => { setBusy(true); setError(''); try { onCreated(await api.createReplayJob()); } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to create replay job'); } finally { setBusy(false); } };
  return <div className="contents">
    <Panel title="Capture a BLE advertising channel">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs text-[var(--app-text-muted)]">PHY<select className="h-9 rounded-md border bg-transparent px-2 text-sm" style={{ borderColor: 'var(--app-border)' }} disabled><option>LE 1M</option></select></label>
        <label className="flex flex-col gap-1 text-xs text-[var(--app-text-muted)]">Primary channel<select value={channel} onChange={(event) => setChannel(Number(event.target.value))} className="h-9 min-w-[13rem] rounded-md border bg-transparent px-2 text-sm" style={{ borderColor: 'var(--app-border)' }}>{BLE_PRIMARY_CHANNELS.map((item) => <option key={item.channel} value={item.channel}>CH{item.channel} — {item.frequencyMHz} MHz</option>)}</select></label>
        <label className="flex flex-col gap-1 text-xs text-[var(--app-text-muted)]">Duration (s)<input type="number" min={1} max={60} value={duration} onChange={(event) => setDuration(Number(event.target.value))} className="h-9 w-20 rounded-md border bg-transparent px-2 text-sm" style={{ borderColor: 'var(--app-border)' }} /></label>
        <button type="button" disabled title={BLE_DSP_UNAVAILABLE_REASON} className="inline-flex h-9 cursor-not-allowed items-center rounded-md bg-sky-600 px-4 text-sm font-semibold text-white opacity-50"><Bluetooth className="mr-2 h-4 w-4" />Start BLE Capture</button>
      </div>
      <div className="mt-3 rounded-md bg-black/10 px-3 py-2 text-xs"><b>Selected RF center:</b> {selected.frequencyMHz} MHz · CH{selected.channel} · {duration}s<div className="mt-1 text-amber-500">Unavailable — DSP recovery gate has not passed. No IQ job will be started.</div></div>
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

      <div className="mb-6 rounded-md border border-amber-400/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-500">
        <AlertTriangle className="mr-2 inline h-4 w-4" />{replayNotice}
      </div>
      {error && <div className="mb-4 rounded-md border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">{error}</div>}

      <div className="mb-6 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <BleJobLauncher enabled={Boolean(capabilities?.enabled)} onCreated={(created) => navigate(`/ble-lab/jobs/${created.job_id}`)} />
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

      <div className="grid gap-6 xl:grid-cols-2"><BleWorkerProvenance capabilities={capabilities} job={job ?? undefined} /><BleKnownLimitations /></div>
    </div>
  );
};
