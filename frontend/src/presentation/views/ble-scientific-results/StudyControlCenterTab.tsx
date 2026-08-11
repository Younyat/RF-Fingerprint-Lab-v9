import { useEffect, useState } from 'react';
import { BleScientificResultsApiService, HardwareQualificationJob, StudyControlCenterStatus } from '../../../app/services/bleScientificResultsApi';
import NoDataNotice, { StatusBadge } from './NoDataNotice';

const sciApi = new BleScientificResultsApiService();

const JOB_TERMINAL = new Set(['completed', 'failed', 'cancelled']);

async function pollJob(jobId: string, onUpdate: (job: HardwareQualificationJob) => void): Promise<HardwareQualificationJob> {
  let current = await sciApi.getHardwareQualificationJob(jobId);
  onUpdate(current);
  while (!JOB_TERMINAL.has(current.state)) {
    await new Promise((resolve) => setTimeout(resolve, 800));
    current = await sciApi.getHardwareQualificationJob(jobId);
    onUpdate(current);
  }
  return current;
}

/** Study Control Center, Phase 1 (2026-08-11): the 17-phase experimental
 * workflow map (read-only aggregation, computes no science) plus the RUN
 * REAL HARDWARE QUALIFICATION launcher -- the same real job/canonical
 * artifact path both the developer and a lab operator use; there is no
 * separate, simplified frontend flow and no hidden CLI step. */
export default function StudyControlCenterTab() {
  const [status, setStatus] = useState<StudyControlCenterStatus | null>(null);

  const refresh = () => {
    sciApi.getStudyControlCenterStatus().then(setStatus).catch(() => setStatus(null));
  };
  useEffect(refresh, []);

  return (
    <div className="space-y-6 p-4">
      <div>
        <div className="text-sm font-semibold text-slate-200">Study Control Center</div>
        <div className="mt-1 text-xs text-slate-500">
          El mismo workflow experimental para el desarrollador y el operador de laboratorio -- sin un paso de CLI
          oculto del que dependa ningun resultado del paper. Cada fase se bloquea automaticamente con la razon real
          cuando falta un prerrequisito.
        </div>
      </div>

      {!status && <NoDataNotice reason="Cargando el estado del Study Control Center..." />}
      {status && (
        <div className="space-y-2">
          {status.phases.map((phase) => (
            <div key={phase.phase_id} className="rounded border border-slate-800 bg-slate-950 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs text-slate-500">{phase.phase_id}</span>
                <span className="text-sm font-semibold text-slate-200">{phase.label}</span>
                <StatusBadge status={phase.state} />
                {phase.next_allowed_operation && <span className="text-[11px] text-cyan-400">{phase.next_allowed_operation}</span>}
              </div>
              {phase.blocking_reasons.length > 0 && (
                <div className="mt-1 text-[11px] text-red-400">
                  BLOCKED -- Missing: {phase.blocking_reasons.join(', ')}
                </div>
              )}
              <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-[11px] text-slate-500">
                <span>run_id: {phase.run_id ?? 'N/A'}</span>
                <span>git_sha: {phase.git_sha.slice(0, 12)}</span>
                <span>protocol_version: {phase.protocol_version ?? 'N/A'}</span>
                <span>paper_section: {phase.paper_section}</span>
                <span>real_data: {phase.real_data_available ? 'yes' : 'no'}</span>
              </div>
              {phase.artifacts.length > 0 && (
                <div className="mt-1 text-[11px] text-slate-600">artifacts: {phase.artifacts.join(', ')}</div>
              )}
            </div>
          ))}
        </div>
      )}

      <HardwareQualificationLauncher onCompleted={refresh} />
    </div>
  );
}

function HardwareQualificationLauncher({ onCompleted }: { onCompleted: () => void }) {
  const [physicalUnitId, setPhysicalUnitId] = useState('');
  const [channel, setChannel] = useState(37);
  const [durationSeconds, setDurationSeconds] = useState(180);
  const [job, setJob] = useState<HardwareQualificationJob | null>(null);
  const [busy, setBusy] = useState(false);

  const start = async () => {
    if (!physicalUnitId) return;
    setBusy(true);
    setJob(null);
    try {
      const started = await sciApi.startHardwareQualification({ physical_unit_id: physicalUnitId, channel, duration_seconds: durationSeconds });
      const finished = await pollJob(started.job_id, setJob);
      if (finished.state === 'completed') onCompleted();
    } finally {
      setBusy(false);
    }
  };

  const cancel = () => {
    if (job) sciApi.cancelHardwareQualificationJob(job.job_id).then(setJob);
  };

  const preflight = job?.result?.preflight_report as { overall_status?: string; items?: Record<string, { status: string; detail: unknown }> } | undefined;

  return (
    <div className="rounded border border-slate-800 bg-slate-900/40 p-4">
      <div className="text-sm font-semibold text-slate-200">RUN REAL HARDWARE QUALIFICATION</div>
      <div className="mt-1 text-xs text-slate-500">
        B200 real -&gt; adquisicion real de I/Q -&gt; decodificacion BLE + CRC -&gt; Eq.(6)-(7) smoke test -&gt; estado real de
        asociacion/RQ3/RQ4 -&gt; campaign_qualification_preflight_report.json. Ningun paso se simula.
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <div>
          <label className="mb-1 block text-xs text-slate-500">physical_unit_id</label>
          <input
            className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none"
            value={physicalUnitId} onChange={(e) => setPhysicalUnitId(e.target.value)} placeholder="UNIT-01" disabled={busy}
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-slate-500">canal BLE</label>
          <input
            type="number" className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none"
            value={channel} onChange={(e) => setChannel(Number(e.target.value))} disabled={busy}
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-slate-500">duracion (s)</label>
          <input
            type="number" className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-cyan-600 focus:outline-none"
            value={durationSeconds} onChange={(e) => setDurationSeconds(Number(e.target.value))} disabled={busy}
          />
        </div>
      </div>

      <div className="mt-3 flex gap-2">
        <button
          className="rounded bg-cyan-700 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-600 disabled:cursor-not-allowed disabled:bg-slate-700"
          disabled={busy || !physicalUnitId} onClick={start}
        >
          {busy ? 'Ejecutando...' : 'RUN REAL HARDWARE QUALIFICATION'}
        </button>
        {busy && job && !JOB_TERMINAL.has(job.state) && (
          <button className="rounded border border-red-800 px-4 py-2 text-sm text-red-400 hover:bg-red-950" onClick={cancel}>
            Cancelar
          </button>
        )}
      </div>

      {job && (
        <div className="mt-4 space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <StatusBadge status={job.state.toUpperCase()} />
            <span className="text-slate-500">stage: {job.stage ?? 'N/A'}</span>
            <span className="text-slate-500">progress: {Math.round(job.overall_progress * 100)}%</span>
          </div>
          {job.message && <div className="text-xs text-slate-400">{job.message}</div>}
          {job.error && <div className="text-xs text-red-400">error: {job.error}</div>}

          {preflight && (
            <div className="mt-2 rounded border border-slate-800 bg-slate-950 p-3">
              <div className="flex items-center gap-2 text-xs">
                <span className="text-slate-500">overall_status</span>
                <StatusBadge status={preflight.overall_status ?? 'NOT_STARTED'} />
              </div>
              {preflight.items && (
                <div className="mt-2 grid gap-1 text-[11px] sm:grid-cols-2">
                  {Object.entries(preflight.items).map(([name, item]) => (
                    <div key={name} className="flex items-center justify-between gap-2 rounded border border-slate-800 bg-slate-900 px-2 py-1">
                      <span className="text-slate-400">{name}</span>
                      <StatusBadge status={item.status} />
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          <details className="rounded border border-slate-800 bg-slate-950">
            <summary className="cursor-pointer px-3 py-2 text-xs font-semibold text-slate-400">JSON crudo (fuente exacta persistida)</summary>
            <pre className="max-h-[50vh] overflow-auto p-3 text-[11px] text-slate-300">{JSON.stringify(job, null, 2)}</pre>
          </details>
        </div>
      )}
    </div>
  );
}
