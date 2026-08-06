import { useState } from 'react';
import {
  BleScientificResultsApiService,
  CapabilityFlag,
  GuidedValidationJob,
  GuidedValidationStage,
  GuidedValidationSummary,
} from '../../../app/services/bleScientificResultsApi';

const api = new BleScientificResultsApiService();
const JOB_TERMINAL = new Set(['completed', 'failed', 'cancelled']);

const STAGE_STATUS_STYLE: Record<string, string> = {
  NOT_STARTED: 'border-slate-700 bg-slate-900/40 text-slate-400',
  RUNNING: 'border-cyan-700 bg-cyan-950/30 text-cyan-300',
  PASSED: 'border-emerald-700 bg-emerald-950/40 text-emerald-300',
  COMPLETED: 'border-emerald-700 bg-emerald-950/40 text-emerald-300',
  PARTIALLY_SUPPORTED: 'border-amber-700 bg-amber-950/30 text-amber-300',
  BLOCKED: 'border-red-800 bg-red-950/40 text-red-300',
  REQUIRES_PHYSICAL_ACTION: 'border-amber-700 bg-amber-950/30 text-amber-300',
};

export default function GuidedValidationTab() {
  const [job, setJob] = useState<GuidedValidationJob | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showTechnical, setShowTechnical] = useState(false);

  const summary: GuidedValidationSummary | undefined = job?.result;

  const start = async () => {
    setRunning(true);
    setError(null);
    setJob(null);
    try {
      let current = await api.startGuidedValidation();
      setJob(current);
      while (!JOB_TERMINAL.has(current.state)) {
        await new Promise((resolve) => setTimeout(resolve, 800));
        current = await api.getGuidedValidationJob(current.job_id);
        setJob(current);
      }
      if (current.state === 'failed') {
        setError(current.error || 'La validacion guiada fallo.');
      }
    } catch (err: unknown) {
      const message = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(message || 'No se pudo iniciar la validacion guiada.');
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-6 p-4">
      <IntroBlock />

      <div className="flex items-center gap-3">
        <button
          className="rounded bg-cyan-700 px-5 py-2.5 text-sm font-semibold text-white hover:bg-cyan-600 disabled:cursor-not-allowed disabled:bg-slate-700"
          disabled={running}
          onClick={start}
        >
          {running ? 'Ejecutando validacion guiada...' : 'Iniciar validacion cientifica BLE guiada'}
        </button>
        {job && !running && (
          <span className="text-xs text-slate-500">
            job_id: <span className="font-mono text-slate-400">{job.job_id}</span> -- estado: {job.state}
          </span>
        )}
      </div>

      {running && job && (
        <div className="rounded border border-cyan-800 bg-cyan-950/20 px-3 py-2 text-xs text-cyan-300">
          [{job.stage ?? '...'}] {job.message ?? 'Procesando'} -- {Math.round((job.overall_progress ?? 0) * 100)}%
        </div>
      )}

      {error && <div className="rounded border border-red-800 bg-red-950/40 px-3 py-2 text-sm text-red-300">{error}</div>}

      {summary && (
        <div className="space-y-6">
          <Stepper stages={summary.stages} />
          <DeviceSummaryTable summary={summary} />
          <AssociationResultCard summary={summary} />
          <CapabilityFlags flags={summary.capability_flags} />
          <ConclusionCard summary={summary} />
          <HardwareActionsCard />
          <TechnicalDrilldown summary={summary} show={showTechnical} onToggle={() => setShowTechnical((v) => !v)} />
        </div>
      )}
    </div>
  );
}

function IntroBlock() {
  return (
    <div className="space-y-3 rounded border border-slate-700 bg-slate-900/40 p-4 text-sm text-slate-300">
      <div>
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Que estamos comprobando</div>
        <p className="mt-1">
          El USRP B200 puede recuperar paquetes BLE a partir de muestras de radio grabadas. Un adaptador BLE nativo
          puede observar de forma independiente los dispositivos cercanos. Esta validacion comprueba si ambas
          observaciones pueden vincularse de forma suficientemente fiable como para asignar una etiqueta de
          dispositivo fisico a un paquete del SDR.
        </p>
      </div>
      <div>
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Por que es necesario</div>
        <p className="mt-1">
          Un paquete BLE con CRC valido demuestra que un paquete se recupero correctamente. No demuestra que
          dispositivo fisico lo transmitio. Una etiqueta fuerte requiere una asociacion verificada de forma
          independiente.
        </p>
      </div>
      <div>
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Que pasa si la asociacion falla</div>
        <p className="mt-1">
          La grabacion sigue siendo util para calidad de senal, evaluacion del decodificador y reconstruccion de
          ventanas, pero no se admite como dato de entrenamiento RFFI con etiqueta fisica fuerte.
        </p>
      </div>
    </div>
  );
}

function Stepper({ stages }: { stages: GuidedValidationStage[] }) {
  return (
    <div>
      <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Etapas</div>
      <div className="space-y-2">
        {stages.map((stage) => (
          <StageCard key={stage.stage_id} stage={stage} />
        ))}
      </div>
    </div>
  );
}

function StageCard({ stage }: { stage: GuidedValidationStage }) {
  const [open, setOpen] = useState(false);
  const style = STAGE_STATUS_STYLE[stage.status] ?? 'border-slate-700 bg-slate-900/40 text-slate-400';
  return (
    <div className={`rounded border p-3 ${style}`}>
      <div className="flex items-center justify-between">
        <div className="text-sm font-semibold text-slate-100">{stage.label}</div>
        <span className="rounded bg-black/20 px-2 py-0.5 text-xs font-medium">{stage.status}</span>
      </div>
      <p className="mt-1 text-xs text-slate-300">{stage.plain_explanation}</p>
      {stage.next_action && <p className="mt-1 text-xs font-medium text-slate-200">Siguiente accion: {stage.next_action}</p>}
      {Object.keys(stage.technical_details).length > 0 && (
        <button className="mt-2 text-[11px] text-slate-400 underline hover:text-slate-200" onClick={() => setOpen((v) => !v)}>
          {open ? 'Ocultar detalle tecnico' : 'Ver detalle tecnico'}
        </button>
      )}
      {open && (
        <pre className="mt-2 max-h-64 overflow-auto rounded bg-black/30 p-2 text-[10px] text-slate-400">
          {JSON.stringify(stage.technical_details, null, 2)}
        </pre>
      )}
    </div>
  );
}

function DeviceSummaryTable({ summary }: { summary: GuidedValidationSummary }) {
  const devices = Object.entries(summary.device_summary);
  return (
    <div>
      <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
        Resumen de datos existentes -- {summary.capture_totals.total_captures} capturas totales
        ({summary.capture_totals.association_calibration_eligible} elegibles para calibracion,{' '}
        {summary.capture_totals.qualification_pilot_eligible} elegibles para piloto,{' '}
        {summary.capture_totals.diagnostic_only} solo diagnostico)
      </div>
      {devices.length === 0 ? (
        <div className="rounded border border-amber-700 bg-amber-950/20 px-3 py-2 text-xs text-amber-300">
          No se encontro ningun dispositivo inscrito con un dataset listo.
        </div>
      ) : (
        <table className="w-full text-left text-xs text-slate-300">
          <thead className="text-slate-500">
            <tr>
              <th className="py-1 pr-3">Dispositivo</th>
              <th className="py-1 pr-3">Capturas</th>
              <th className="py-1 pr-3">Eventos nativos</th>
              <th className="py-1 pr-3">Paquetes CRC-validos</th>
              <th className="py-1 pr-3">Asociaciones fuertes</th>
              <th className="py-1 pr-3">Ventanas activas</th>
              <th className="py-1 pr-3">Ventanas elegibles</th>
            </tr>
          </thead>
          <tbody>
            {devices.map(([deviceId, row]) => (
              <tr key={deviceId} className="border-t border-slate-800">
                <td className="py-1 pr-3 font-mono">{deviceId}</td>
                <td className="py-1 pr-3">{row.capture_count}</td>
                <td className="py-1 pr-3">{row.native_event_count}</td>
                <td className="py-1 pr-3">{row.crc_valid_packet_count}</td>
                <td className="py-1 pr-3">{row.strong_association_count}</td>
                <td className="py-1 pr-3">{row.active_windows}</td>
                <td className="py-1 pr-3">{row.eligible_windows}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function AssociationResultCard({ summary }: { summary: GuidedValidationSummary }) {
  const association = summary.association_summary;
  const matched = association.matched_target_count;
  const policyFrozen = summary.association_policy_summary?.status === 'FROZEN' || summary.association_policy_summary?.status === 'FROZEN_STRATIFIED';
  return (
    <div className={`rounded border p-4 ${matched > 0 ? 'border-emerald-700 bg-emerald-950/20' : 'border-red-800 bg-red-950/20'}`}>
      <div className="text-sm font-semibold text-slate-100">Resultado actual de asociacion de fuente</div>
      <div className="mt-2 grid grid-cols-3 gap-3 text-xs">
        <Metric label="Asociaciones fuertes con el target" value={String(matched)} />
        <Metric label="Politica de asociacion" value={policyFrozen ? 'Disponible' : 'No disponible'} />
        <Metric label="Entrenamiento con etiquetas fisicas fuertes" value={matched > 0 && policyFrozen ? 'Permitido' : 'Bloqueado'} />
      </div>
      <p className="mt-3 text-xs text-slate-300">
        Las grabaciones existentes contienen paquetes BLE validos y ventanas analiticas utilizables, pero ningun
        paquete del SDR fue emparejado con una observacion nativa del dispositivo declarado bajo las reglas
        actuales de tiempo y coincidencia de campos.
      </p>
      <div className="mt-3">
        <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Distribucion de resultados de asociacion</div>
        <table className="mt-1 w-full text-left text-xs text-slate-300">
          <tbody>
            {Object.entries(association.by_status).map(([status, count]) => (
              <tr key={status} className="border-t border-slate-800">
                <td className="py-1 pr-3 font-mono">{status}</td>
                <td className="py-1 pr-3">{count}</td>
                <td className="py-1 pr-3">{association.by_status_percent[status]}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs italic text-slate-400">
        La mayoria de los fallos ocurre porque no se encontro ningun evento nativo BLE dentro de la ventana temporal
        actual. Esto apunta principalmente a cobertura del escaner, alineacion de marcas de tiempo o retardo de
        callback, mas que a un fallo en la recuperacion de paquetes del SDR.
      </p>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-slate-700 bg-slate-900/60 px-2 py-1.5">
      <div className="text-slate-500">{label}</div>
      <div className="font-mono text-sm text-slate-100">{value}</div>
    </div>
  );
}

function CapabilityFlags({ flags }: { flags: CapabilityFlag[] }) {
  return (
    <div className="grid grid-cols-3 gap-3">
      {flags.map((flag) => (
        <div key={flag.capability} className={`rounded border p-3 ${flag.supported ? 'border-emerald-700 bg-emerald-950/20' : 'border-red-800 bg-red-950/20'}`}>
          <div className="text-xs text-slate-400">{flag.plain_explanation}</div>
          <div className={`mt-1 text-sm font-bold ${flag.supported ? 'text-emerald-300' : 'text-red-300'}`}>{flag.supported ? 'SI' : 'NO'}</div>
          <div className="text-[11px] text-slate-500">{flag.capability}</div>
        </div>
      ))}
    </div>
  );
}

function ConclusionCard({ summary }: { summary: GuidedValidationSummary }) {
  return (
    <div className="rounded border border-slate-700 bg-slate-900/40 p-4">
      <div className="text-sm font-semibold text-slate-100">Conclusion cientifica</div>
      <p className="mt-2 text-xs text-slate-300">{summary.simplified_conclusion}</p>
      <div className="mt-3 rounded border border-cyan-800 bg-cyan-950/20 px-3 py-2 text-xs font-semibold text-cyan-300">
        Proxima accion: {summary.next_required_action}
      </div>
    </div>
  );
}

function HardwareActionsCard() {
  return (
    <div className="rounded border border-slate-700 bg-slate-900/30 p-4">
      <div className="text-sm font-semibold text-slate-100">Acciones que requieren hardware fisico</div>
      <p className="mt-1 text-xs text-slate-500">
        Estas acciones reutilizan <code>CampaignOrchestrator</code>/<code>PaperCampaignRunner</code> para ejecutar una
        captura real corta. Requieren un operador presente para colocar/retirar dispositivos fisicos antes de
        iniciar -- no se ejecutan automaticamente desde esta pantalla en esta entrega.
      </p>
      <div className="mt-3 flex flex-wrap gap-3">
        <HardwareActionButton
          label="Ejecutar diagnostico de tiempo en vivo"
          steps={['Selecciona un dispositivo inscrito', 'Manten solo ese dispositivo controlado activo', 'Confirma que el escaner nativo lo detecta', 'Manten el B200 y el adaptador conectados', 'Inicia el diagnostico (3-5 min)']}
        />
        <HardwareActionButton
          label="Ejecutar control reforzado de ausencia de target"
          steps={['Apaga o retira los cinco dispositivos inscritos', 'El trafico BLE ambiental puede permanecer presente', 'Confirma que el escaner nativo y el SDR estan activos']}
        />
      </div>
    </div>
  );
}

function HardwareActionButton({ label, steps }: { label: string; steps: string[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        className="rounded border border-amber-700 bg-amber-950/20 px-3 py-2 text-xs font-medium text-amber-300 hover:bg-amber-900/30"
        onClick={() => setOpen((v) => !v)}
      >
        {label}
      </button>
      {open && (
        <div className="mt-2 max-w-sm rounded border border-slate-700 bg-slate-950 p-3 text-xs text-slate-300">
          <ol className="list-decimal space-y-1 pl-4">
            {steps.map((step, index) => <li key={index}>{step}</li>)}
          </ol>
          <div className="mt-2 rounded border border-amber-800 bg-amber-950/30 px-2 py-1 text-[11px] text-amber-300">
            BLOQUEADO -- requiere accion fisica. No disponible desde esta interfaz en esta entrega.
          </div>
        </div>
      )}
    </div>
  );
}

function TechnicalDrilldown({ summary, show, onToggle }: { summary: GuidedValidationSummary; show: boolean; onToggle: () => void }) {
  return (
    <div>
      <button className="text-xs font-semibold text-slate-400 underline hover:text-slate-200" onClick={onToggle}>
        {show ? 'Ocultar evidencia tecnica' : 'Mostrar evidencia tecnica'}
      </button>
      {show && (
        <div className="mt-2 space-y-2 rounded border border-slate-700 bg-slate-950 p-3 text-xs text-slate-300">
          <div>run_id: <span className="font-mono">{summary.run_id}</span></div>
          <div>generated_at: <span className="font-mono">{summary.generated_at}</span></div>
          <div className="mt-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">artifact_index</div>
          <pre className="max-h-72 overflow-auto rounded bg-black/30 p-2 text-[10px] text-slate-400">
            {JSON.stringify(summary.artifact_index, null, 2)}
          </pre>
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">target_absence_summary</div>
          <pre className="max-h-72 overflow-auto rounded bg-black/30 p-2 text-[10px] text-slate-400">
            {JSON.stringify(summary.target_absence_summary, null, 2)}
          </pre>
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">association_policy_summary</div>
          <pre className="max-h-72 overflow-auto rounded bg-black/30 p-2 text-[10px] text-slate-400">
            {JSON.stringify(summary.association_policy_summary, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}
