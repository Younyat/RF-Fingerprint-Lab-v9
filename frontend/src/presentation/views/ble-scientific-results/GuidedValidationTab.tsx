import { useState } from 'react';
import {
  BleScientificResultsApiService,
  GuidedValidationActionJob,
  GuidedValidationJob,
  GuidedValidationStage,
  GuidedValidationSummary,
  TargetAbsenceControlResult,
  TimingDiagnosticResult,
} from '../../../app/services/bleScientificResultsApi';

const api = new BleScientificResultsApiService();
const JOB_TERMINAL = new Set(['completed', 'failed', 'cancelled']);

async function pollAction(runId: string, jobId: string, onUpdate: (job: GuidedValidationActionJob) => void): Promise<GuidedValidationActionJob> {
  let current = await api.getGuidedValidationAction(runId, jobId);
  onUpdate(current);
  while (!JOB_TERMINAL.has(current.state)) {
    await new Promise((resolve) => setTimeout(resolve, 800));
    current = await api.getGuidedValidationAction(runId, jobId);
    onUpdate(current);
  }
  return current;
}

// ---------------------------------------------------------------------
// Spanish copy -- pure presentation-layer translation. Every value shown
// here is read from the SAME GuidedValidationSummary/TimingDiagnosticResult/
// TargetAbsenceControlResult the backend already computed; nothing here
// recomputes a scientific result.
// ---------------------------------------------------------------------

const STAGE_LABEL_ES: Record<string, string> = {
  objective: 'Objetivo',
  available_data: 'Datos disponibles',
  capture_integrity: 'Integridad de las grabaciones',
  packet_recovery: 'Recuperación de paquetes',
  source_association: 'Relación con el dispositivo',
  negative_control: 'Control sin dispositivos',
  association_policy: 'Preparación de la identificación',
  next_required_action: 'Siguiente paso',
};

const STAGE_STATUS_LABEL_ES: Record<string, string> = {
  NOT_STARTED: 'No iniciado',
  RUNNING: 'En curso',
  PASSED: 'Completado',
  COMPLETED: 'Completado',
  PARTIALLY_SUPPORTED: 'Parcialmente disponible',
  BLOCKED: 'Acción necesaria',
  REQUIRES_PHYSICAL_ACTION: 'Acción física necesaria',
};

const DIAGNOSIS_ES: Record<string, { title: string; explanation: string }> = {
  NATIVE_SCANNER_NOT_RUNNING: {
    title: 'El escáner BLE no estaba funcionando',
    explanation: 'La captura de radio se realizó, pero no se obtuvieron observaciones del adaptador BLE.',
  },
  NATIVE_SCANNER_COVERAGE_INSUFFICIENT: {
    title: 'El escáner BLE perdió parte de la prueba',
    explanation: 'El adaptador BLE no observó el dispositivo de forma continua durante la captura.',
  },
  TIMESTAMP_DOMAINS_INCOMPATIBLE: {
    title: 'Las dos fuentes utilizan tiempos incompatibles',
    explanation: 'El adaptador BLE y el USRP registraron actividad, pero sus marcas de tiempo no pueden compararse directamente.',
  },
  TIME_GATE_TOO_NARROW: {
    title: 'Los eventos parecen corresponder, pero llegan con más retraso del esperado',
    explanation: 'La diferencia temporal es consistente, pero queda fuera del límite utilizado actualmente.',
  },
  DECODED_FIELDS_DO_NOT_MATCH: {
    title: 'Los paquetes recuperados no corresponden al dispositivo seleccionado',
    explanation: 'Verifica que el dispositivo elegido es realmente el que está transmitiendo.',
  },
  MULTIPLE_COMPETING_CANDIDATES: {
    title: 'Hay varias observaciones posibles para el mismo paquete',
    explanation: 'No se puede asignar el paquete a una única observación de forma inequívoca todavía.',
  },
  ASSOCIATION_CALIBRATION_POSSIBLE: {
    title: 'La sincronización es suficiente',
    explanation: 'Ya existen coincidencias utilizables para calcular la política de asociación.',
  },
};

function overallStatusEs(hasSummary: boolean, jobFailed: boolean, status: string | undefined): { label: string; classes: string } {
  if (jobFailed) return { label: 'ERROR TÉCNICO', classes: 'border-red-700 bg-red-950/40 text-red-300' };
  if (!hasSummary) return { label: 'TODAVÍA NO EVALUADO', classes: 'border-slate-700 bg-slate-900/40 text-slate-400' };
  if (status === 'PASSED') return { label: 'IDENTIFICACIÓN FÍSICA DISPONIBLE', classes: 'border-emerald-700 bg-emerald-950/40 text-emerald-300' };
  return { label: 'SE NECESITA UNA PRUEBA ADICIONAL', classes: 'border-amber-700 bg-amber-950/30 text-amber-300' };
}

interface CapabilityCopy { title: string; workingText: string; notWorkingText: string }
const CAPABILITY_ES: Record<string, CapabilityCopy> = {
  'RF capture': {
    title: 'Captura de radio',
    workingText: 'El USRP B200 ha grabado señales BLE reales correctamente.',
    notWorkingText: 'El USRP B200 no ha grabado señales BLE todavía.',
  },
  'BLE packet recovery': {
    title: 'Recuperación de paquetes',
    workingText: 'La plataforma ha recuperado paquetes BLE válidos desde las grabaciones.',
    notWorkingText: 'La plataforma no ha recuperado paquetes BLE válidos todavía.',
  },
  'Physical-source association': {
    title: 'Identificación del dispositivo',
    workingText: 'Los paquetes recuperados ya pueden relacionarse con un dispositivo físico concreto.',
    notWorkingText: 'Los paquetes recuperados aún no pueden relacionarse de forma fiable con un dispositivo físico concreto.',
  },
};

function stageStatus(summary: GuidedValidationSummary, stageId: string): string | undefined {
  return summary.stages.find((stage) => stage.stage_id === stageId)?.status;
}

export default function GuidedValidationTab() {
  const [job, setJob] = useState<GuidedValidationJob | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [advanced, setAdvanced] = useState(false);
  const [showDeviceTable, setShowDeviceTable] = useState(false);
  const [showTechnical, setShowTechnical] = useState(false);
  const [diagnosticResult, setDiagnosticResult] = useState<TimingDiagnosticResult | null>(null);
  const [absenceResult, setAbsenceResult] = useState<TargetAbsenceControlResult | null>(null);

  const summary: GuidedValidationSummary | undefined = job?.result;
  const jobFailed = job?.state === 'failed';

  const start = async () => {
    setRunning(true);
    setError(null);
    setJob(null);
    setDiagnosticResult(null);
    setAbsenceResult(null);
    try {
      let current = await api.startGuidedValidation();
      setJob(current);
      while (!JOB_TERMINAL.has(current.state)) {
        await new Promise((resolve) => setTimeout(resolve, 800));
        current = await api.getGuidedValidationJob(current.job_id);
        setJob(current);
      }
      if (current.state === 'failed') setError(current.error || 'No se pudieron revisar las grabaciones.');
    } catch (err: unknown) {
      const message = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(message || 'No se pudieron revisar las grabaciones.');
    } finally {
      setRunning(false);
    }
  };

  const diagnosticPassedLocally = diagnosticResult?.diagnosis_code === 'ASSOCIATION_CALIBRATION_POSSIBLE';
  const absencePassedLocally = absenceResult?.status === 'VALID';
  const syncReady = !!summary && (stageStatus(summary, 'source_association') === 'PASSED' || diagnosticPassedLocally);
  const absenceReady = !!summary && (stageStatus(summary, 'negative_control') === 'PASSED' || absencePassedLocally);
  const policyReady = !!summary && stageStatus(summary, 'association_policy') === 'PASSED';
  const overall = overallStatusEs(!!summary, jobFailed, summary?.overall_status);

  return (
    <div className="space-y-6 p-4">
      {/* 1. Título y estado general */}
      <div>
        <h2 className="text-lg font-bold text-slate-100">Validación de identidad física BLE</h2>
        <p className="mt-1 max-w-3xl text-sm text-slate-400">
          Esta prueba comprueba si las señales BLE capturadas por el USRP B200 pueden relacionarse de forma fiable
          con uno de tus dispositivos físicos.
        </p>
        <div className={`mt-3 inline-block rounded border px-3 py-1.5 text-xs font-bold tracking-wide ${overall.classes}`}>
          RESULTADO ACTUAL: {overall.label}
        </div>
      </div>

      {!summary && (
        <div className="rounded border border-slate-700 bg-slate-900/40 p-4">
          <button
            className="rounded bg-cyan-700 px-5 py-2.5 text-sm font-semibold text-white hover:bg-cyan-600 disabled:cursor-not-allowed disabled:bg-slate-700"
            disabled={running}
            onClick={start}
          >
            {running ? 'Revisando grabaciones...' : 'Comprobar mis grabaciones BLE'}
          </button>
          {running && job && (
            <div className="mt-2 text-xs text-cyan-300">[{job.stage ?? '...'}] {job.message ?? 'Procesando'} -- {Math.round((job.overall_progress ?? 0) * 100)}%</div>
          )}
          {error && <div className="mt-2 rounded border border-red-800 bg-red-950/40 px-3 py-2 text-sm text-red-300">{error}</div>}
        </div>
      )}

      {summary && (
        <div className="space-y-6">
          {/* 2. Tres tarjetas: captura / paquetes / identidad */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {summary.capability_flags.map((flag) => {
              const copy = CAPABILITY_ES[flag.capability] ?? { title: flag.capability, workingText: flag.plain_explanation, notWorkingText: flag.plain_explanation };
              return (
                <div key={flag.capability} className={`rounded border p-3 ${flag.supported ? 'border-emerald-700 bg-emerald-950/20' : 'border-amber-700 bg-amber-950/20'}`}>
                  <div className="text-xs font-semibold text-slate-300">{copy.title}</div>
                  <div className={`mt-1 text-sm font-bold ${flag.supported ? 'text-emerald-300' : 'text-amber-300'}`}>
                    {flag.supported ? 'FUNCIONA' : 'TODAVÍA NO DISPONIBLE'}
                  </div>
                  <p className="mt-1 text-[11px] text-slate-400">{flag.supported ? copy.workingText : copy.notWorkingText}</p>
                </div>
              );
            })}
          </div>

          {/* 3. Explicación humana de lo ocurrido */}
          <WhatHappenedCard summary={summary} />

          {/* 4. Única acción recomendada */}
          <NextStepFlow
            summary={summary}
            syncReady={syncReady}
            absenceReady={absenceReady}
            policyReady={policyReady}
            diagnosticResult={diagnosticResult}
            setDiagnosticResult={setDiagnosticResult}
            absenceResult={absenceResult}
            setAbsenceResult={setAbsenceResult}
          />

          {/* 5. Progreso en cuatro pasos */}
          <SimpleStepper syncReady={syncReady} absenceReady={absenceReady} policyReady={policyReady} />

          {/* 6. Resultados resumidos */}
          <ResultsSummary summary={summary} show={showDeviceTable} onToggle={() => setShowDeviceTable((v) => !v)} />

          {/* 7. Detalles técnicos cerrados */}
          <div className="rounded border border-slate-700 bg-slate-900/20 p-3">
            <button className="text-xs font-semibold text-slate-400 underline hover:text-slate-200" onClick={() => setShowTechnical((v) => !v)}>
              {showTechnical ? 'Ocultar detalles técnicos' : 'Ver detalles técnicos'}
            </button>
            {showTechnical && (
              <div className="mt-3 space-y-4">
                <AssociationDistributionCard summary={summary} />
                <label className="flex items-center gap-2 text-xs text-slate-400">
                  <input type="checkbox" checked={advanced} onChange={(e) => setAdvanced(e.target.checked)} />
                  Vista científica avanzada
                </label>
                {advanced && <AdvancedView summary={summary} />}
                <TechnicalDrilldown summary={summary} />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function WhatHappenedCard({ summary }: { summary: GuidedValidationSummary }) {
  const matched = summary.association_summary.matched_target_count;
  return (
    <div className="rounded border border-slate-700 bg-slate-900/40 p-4">
      <div className="text-sm font-semibold text-slate-100">¿Qué ha ocurrido?</div>
      {matched > 0 ? (
        <p className="mt-2 text-sm text-slate-300">
          Encontramos señales BLE, recuperamos sus paquetes y logramos relacionar {matched} de ellos con un
          dispositivo físico concreto.
        </p>
      ) : (
        <>
          <p className="mt-2 text-sm text-slate-300">
            Encontramos señales BLE y recuperamos correctamente sus paquetes. Sin embargo, las observaciones del
            adaptador BLE y las capturas del USRP B200 no coinciden todavía en el tiempo. Por ese motivo, no podemos
            afirmar qué dispositivo físico transmitió cada paquete.
          </p>
          <div className="mt-3 rounded border border-slate-700 bg-slate-950 px-3 py-2">
            <div className="text-xs font-semibold text-slate-300">Esto no significa que el B200 haya fallado.</div>
            <p className="mt-1 text-xs text-slate-400">El problema está en relacionar las dos fuentes de observación, no en capturar o decodificar la señal.</p>
          </div>
        </>
      )}
    </div>
  );
}

function NextStepFlow({
  summary, syncReady, absenceReady, policyReady, diagnosticResult, setDiagnosticResult, absenceResult, setAbsenceResult,
}: {
  summary: GuidedValidationSummary; syncReady: boolean; absenceReady: boolean; policyReady: boolean;
  diagnosticResult: TimingDiagnosticResult | null; setDiagnosticResult: (r: TimingDiagnosticResult | null) => void;
  absenceResult: TargetAbsenceControlResult | null; setAbsenceResult: (r: TargetAbsenceControlResult | null) => void;
}) {
  const deviceIds = Object.keys(summary.device_summary);

  if (!syncReady) {
    return (
      <div className="space-y-3">
        <ActiveStepCard title="Comprobar la sincronización con un dispositivo">
          <p className="text-sm text-slate-300">
            Realizaremos una prueba corta con un único dispositivo encendido. La plataforma comprobará
            automáticamente si el adaptador BLE y el USRP B200 están registrando el mismo evento en tiempos
            compatibles.
          </p>
          <TimingDiagnosticWizard runId={summary.run_id} deviceIds={deviceIds} onResult={setDiagnosticResult} result={diagnosticResult} />
        </ActiveStepCard>
        <DisabledPreviewCard title="Paso posterior: comprobar el entorno sin los dispositivos inscritos." />
      </div>
    );
  }

  if (!absenceReady) {
    return (
      <ActiveStepCard title="Comprobar el entorno sin los dispositivos inscritos">
        <p className="text-sm text-slate-300">
          Esta prueba comprueba que la plataforma no atribuye por error el tráfico BLE ambiental a uno de tus cinco
          dispositivos.
        </p>
        <TargetAbsenceWizard runId={summary.run_id} deviceIds={deviceIds} onResult={setAbsenceResult} result={absenceResult} />
      </ActiveStepCard>
    );
  }

  if (!policyReady) {
    return (
      <ActiveStepCard title="Identificación física -- PENDIENTE" tone="gray">
        <p className="text-sm text-slate-300">Primero debe completarse la prueba de sincronización y el control sin dispositivos.</p>
      </ActiveStepCard>
    );
  }

  return (
    <ActiveStepCard title="Identificación física disponible" tone="green">
      <p className="text-sm text-slate-300">La plataforma ya puede relacionar paquetes recuperados con dispositivos físicos concretos.</p>
    </ActiveStepCard>
  );
}

function ActiveStepCard({ title, tone = 'amber', children }: { title: string; tone?: 'amber' | 'green' | 'gray'; children: React.ReactNode }) {
  const toneClasses = tone === 'green' ? 'border-emerald-700 bg-emerald-950/20' : tone === 'gray' ? 'border-slate-700 bg-slate-900/40' : 'border-amber-700 bg-amber-950/10';
  return (
    <div className={`rounded border p-4 ${toneClasses}`}>
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Siguiente paso</div>
      <div className="mt-1 text-base font-bold text-slate-100">{title}</div>
      <div className="mt-3 space-y-3">{children}</div>
    </div>
  );
}

function DisabledPreviewCard({ title }: { title: string }) {
  return (
    <div className="rounded border border-slate-800 bg-slate-950/60 p-3 text-xs text-slate-600">
      {title}
    </div>
  );
}

function TimingDiagnosticWizard({ runId, deviceIds, onResult, result }: { runId: string; deviceIds: string[]; onResult: (r: TimingDiagnosticResult | null) => void; result: TimingDiagnosticResult | null }) {
  const [expanded, setExpanded] = useState(false);
  const [deviceId, setDeviceId] = useState(deviceIds[0] ?? '');
  const [durationMinutes, setDurationMinutes] = useState(3);
  const [channel, setChannel] = useState(37);
  const [operatorName, setOperatorName] = useState('');
  const [showAdvancedFields, setShowAdvancedFields] = useState(false);
  const [receiverProfile, setReceiverProfile] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [job, setJob] = useState<GuidedValidationActionJob | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const start = async () => {
    setRunning(true);
    setError(null);
    onResult(null);
    try {
      const started = await api.startTimingDiagnostic(runId, {
        physical_unit_id: deviceId, capture_duration_s: durationMinutes * 60, channel,
        receiver_profile: receiverProfile || undefined, operator_id: operatorName || undefined,
      });
      const finished = await pollAction(runId, started.job_id, setJob);
      if (finished.state === 'failed') setError(finished.error || 'La prueba de sincronización falló.');
      else onResult((finished.result as TimingDiagnosticResult) ?? null);
    } catch (err: unknown) {
      const message = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(message || 'No se pudo iniciar la prueba de sincronización.');
    } finally {
      setRunning(false);
    }
  };

  if (!expanded) {
    return (
      <button className="rounded bg-cyan-700 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-600" onClick={() => setExpanded(true)}>
        Iniciar prueba guiada
      </button>
    );
  }

  const diagnosis = result ? DIAGNOSIS_ES[result.diagnosis_code] : null;

  return (
    <div className="space-y-3 rounded border border-slate-700 bg-slate-950 p-3 text-sm">
      <div>
        <label className="mb-1 block text-xs text-slate-400">Dispositivo que vas a probar</label>
        <select className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-slate-100" value={deviceId} onChange={(e) => setDeviceId(e.target.value)}>
          <option value="">Selecciona...</option>
          {deviceIds.map((id) => <option key={id} value={id}>{id}</option>)}
        </select>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="mb-1 block text-xs text-slate-400">Duración de la prueba (minutos)</label>
          <input type="number" className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-slate-100" value={durationMinutes} onChange={(e) => setDurationMinutes(Number(e.target.value))} />
        </div>
        <div>
          <label className="mb-1 block text-xs text-slate-400">Canal BLE</label>
          <input type="number" className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-slate-100" value={channel} onChange={(e) => setChannel(Number(e.target.value))} />
        </div>
      </div>
      <div>
        <label className="mb-1 block text-xs text-slate-400">Nombre del operador (opcional)</label>
        <input className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-slate-100" value={operatorName} onChange={(e) => setOperatorName(e.target.value)} />
      </div>
      <div>
        <button className="text-xs text-slate-400 underline hover:text-slate-200" onClick={() => setShowAdvancedFields((v) => !v)}>
          {showAdvancedFields ? 'Ocultar opciones avanzadas' : 'Opciones avanzadas'}
        </button>
        {showAdvancedFields && (
          <div className="mt-2">
            <label className="mb-1 block text-xs text-slate-400">Perfil de receptor</label>
            <input className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-slate-100" value={receiverProfile} onChange={(e) => setReceiverProfile(e.target.value)} placeholder="opcional" />
          </div>
        )}
      </div>

      <div className="rounded border border-slate-700 bg-slate-900/60 p-3">
        <div className="text-xs font-semibold text-slate-300">Antes de comenzar</div>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-xs text-slate-300">
          <li>Deja encendido únicamente el dispositivo seleccionado.</li>
          <li>Comprueba que aparece en el escáner BLE.</li>
          <li>Comprueba que el USRP B200 está conectado.</li>
          <li>Cierra cualquier otra captura que esté utilizando el B200.</li>
        </ol>
        <label className="mt-3 flex items-center gap-2 text-xs text-slate-200">
          <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
          He completado los cuatro pasos.
        </label>
      </div>

      <p className="text-xs text-slate-400">
        La prueba durará aproximadamente {durationMinutes} minutos. La plataforma iniciará el escáner BLE y la
        captura de radio, analizará los paquetes recuperados y te explicará automáticamente el resultado.
      </p>

      <button
        className="w-full rounded bg-cyan-700 px-3 py-2 text-sm font-semibold text-white hover:bg-cyan-600 disabled:cursor-not-allowed disabled:bg-slate-700"
        disabled={!confirmed || !deviceId || running}
        onClick={start}
      >
        {running ? 'Realizando la prueba...' : 'Comenzar prueba de sincronización'}
      </button>
      {running && job && <div className="text-xs text-cyan-300">[{job.stage}] {job.message} -- {Math.round((job.overall_progress ?? 0) * 100)}%</div>}
      {error && <div className="rounded border border-red-800 bg-red-950/40 px-2 py-1 text-xs text-red-300">{error}</div>}
      {result && diagnosis && (
        <div className={`space-y-1 rounded border p-3 ${result.diagnosis_code === 'ASSOCIATION_CALIBRATION_POSSIBLE' ? 'border-emerald-700 bg-emerald-950/20' : 'border-amber-700 bg-amber-950/20'}`}>
          <div className="text-sm font-bold text-slate-100">{diagnosis.title}</div>
          <div className="text-xs text-slate-300">{diagnosis.explanation}</div>
          <div className="mt-1 text-[10px] text-slate-600">código: {result.diagnosis_code}</div>
        </div>
      )}
    </div>
  );
}

function TargetAbsenceWizard({ runId, deviceIds, onResult, result }: { runId: string; deviceIds: string[]; onResult: (r: TargetAbsenceControlResult | null) => void; result: TargetAbsenceControlResult | null }) {
  const [confirmed, setConfirmed] = useState<Record<string, boolean>>({});
  const [durationMinutes, setDurationMinutes] = useState(3);
  const [channel, setChannel] = useState(37);
  const [operatorName, setOperatorName] = useState('');
  const [job, setJob] = useState<GuidedValidationActionJob | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const allConfirmed = deviceIds.length > 0 && deviceIds.every((id) => confirmed[id]);

  const start = async () => {
    setRunning(true);
    setError(null);
    onResult(null);
    try {
      const started = await api.startTargetAbsenceControl(runId, { confirmed_devices_off: confirmed, capture_duration_s: durationMinutes * 60, channel, operator_id: operatorName || undefined });
      const finished = await pollAction(runId, started.job_id, setJob);
      if (finished.state === 'failed') setError(finished.error || 'El control sin dispositivos falló.');
      else onResult((finished.result as TargetAbsenceControlResult) ?? null);
    } catch (err: unknown) {
      const message = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(message || 'No se pudo iniciar el control sin dispositivos.');
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-3 rounded border border-slate-700 bg-slate-950 p-3 text-sm">
      <p className="text-xs text-slate-400">Ambiente BLE ambiental puede seguir presente. Confirma cada dispositivo por separado antes de continuar.</p>
      <div className="space-y-1 rounded border border-slate-700 bg-slate-900/60 p-2">
        {deviceIds.map((id) => (
          <label key={id} className="flex items-center gap-2 text-xs text-slate-300">
            <input type="checkbox" checked={!!confirmed[id]} onChange={(e) => setConfirmed((prev) => ({ ...prev, [id]: e.target.checked }))} />
            <span className="font-mono">{id} está apagado o retirado.</span>
          </label>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="mb-1 block text-xs text-slate-400">Duración de la prueba (minutos)</label>
          <input type="number" className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-slate-100" value={durationMinutes} onChange={(e) => setDurationMinutes(Number(e.target.value))} />
        </div>
        <div>
          <label className="mb-1 block text-xs text-slate-400">Canal BLE</label>
          <input type="number" className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-slate-100" value={channel} onChange={(e) => setChannel(Number(e.target.value))} />
        </div>
      </div>
      <div>
        <label className="mb-1 block text-xs text-slate-400">Nombre del operador (opcional)</label>
        <input className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-slate-100" value={operatorName} onChange={(e) => setOperatorName(e.target.value)} />
      </div>
      <button
        className="w-full rounded bg-cyan-700 px-3 py-2 text-sm font-semibold text-white hover:bg-cyan-600 disabled:cursor-not-allowed disabled:bg-slate-700"
        disabled={!allConfirmed || running}
        onClick={start}
      >
        {running ? 'Realizando el control...' : 'Iniciar control sin dispositivos'}
      </button>
      {running && job && <div className="text-xs text-cyan-300">[{job.stage}] {job.message} -- {Math.round((job.overall_progress ?? 0) * 100)}%</div>}
      {error && <div className="rounded border border-red-800 bg-red-950/40 px-2 py-1 text-xs text-red-300">{error}</div>}
      {result && (
        <div className={`space-y-1 rounded border p-3 text-xs ${result.status === 'VALID' ? 'border-emerald-700 bg-emerald-950/20' : 'border-red-800 bg-red-950/20'}`}>
          <div className="font-bold text-slate-100">{result.status === 'VALID' ? 'Entorno limpio confirmado' : 'El control no es válido todavía'}</div>
          {result.devices_detected.length > 0 && <div className="text-red-300">Todavía se detectaron: {result.devices_detected.join(', ')}</div>}
        </div>
      )}
    </div>
  );
}

function SimpleStepper({ syncReady, absenceReady, policyReady }: { syncReady: boolean; absenceReady: boolean; policyReady: boolean }) {
  const doneFlags = [true, syncReady, absenceReady, policyReady]; // step 1 (reviewing recordings) is always done once a summary exists
  const labels = ['Revisar grabaciones existentes', 'Comprobar sincronización', 'Comprobar el entorno sin dispositivos', 'Preparar la identificación física'];
  let firstNotDone = doneFlags.findIndex((done) => !done);
  if (firstNotDone === -1) firstNotDone = labels.length;
  return (
    <div>
      <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Progreso</div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-4">
        {labels.map((label, index) => {
          const status = index < firstNotDone ? 'Completado' : index === firstNotDone ? 'Acción necesaria' : 'Pendiente';
          const classes = status === 'Completado' ? 'border-emerald-700 bg-emerald-950/20 text-emerald-300' : status === 'Acción necesaria' ? 'border-amber-700 bg-amber-950/20 text-amber-300' : 'border-slate-700 bg-slate-900/40 text-slate-500';
          return (
            <div key={label} className={`rounded border p-2 text-xs ${classes}`}>
              <div className="font-semibold">{index + 1}. {label}</div>
              <div className="mt-0.5 text-[11px]">{status}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ResultsSummary({ summary, show, onToggle }: { summary: GuidedValidationSummary; show: boolean; onToggle: () => void }) {
  const totals = summary.capture_totals;
  const usable = totals.association_calibration_eligible + totals.qualification_pilot_eligible;
  const deviceCount = Object.keys(summary.device_summary).length;
  const matched = summary.association_summary.matched_target_count;
  return (
    <div>
      <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
        <Metric label="grabaciones analizadas" value={String(totals.total_captures)} />
        <Metric label="técnicamente utilizables" value={String(usable)} />
        <Metric label="dispositivos incluidos" value={String(deviceCount)} />
        <Metric label="identificaciones físicas confirmadas" value={String(matched)} />
      </div>
      <button className="mt-2 text-xs text-slate-400 underline hover:text-slate-200" onClick={onToggle}>
        {show ? 'Ocultar resultados por dispositivo' : 'Ver resultados por dispositivo'}
      </button>
      {show && (
        <table className="mt-2 w-full text-left text-xs text-slate-300">
          <thead className="text-slate-500">
            <tr>
              <th className="py-1 pr-3">Dispositivo</th>
              <th className="py-1 pr-3">Grabaciones</th>
              <th className="py-1 pr-3">Paquetes recuperados</th>
              <th className="py-1 pr-3">Identificaciones confirmadas</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(summary.device_summary).map(([deviceId, row]) => (
              <tr key={deviceId} className="border-t border-slate-800">
                <td className="py-1 pr-3 font-mono">{deviceId}</td>
                <td className="py-1 pr-3">{row.capture_count}</td>
                <td className="py-1 pr-3">{row.crc_valid_packet_count}</td>
                <td className="py-1 pr-3">{row.strong_association_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
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

function AssociationDistributionCard({ summary }: { summary: GuidedValidationSummary }) {
  const [open, setOpen] = useState(false);
  const association = summary.association_summary;
  return (
    <div>
      <div className="text-xs font-semibold text-slate-300">Detalles técnicos de la asociación</div>
      <p className="mt-1 text-xs text-slate-400">
        En la mayoría de los casos, el adaptador BLE no registró una observación suficientemente cercana en el
        tiempo al paquete recuperado por el B200.
      </p>
      <button className="mt-2 text-[11px] text-slate-400 underline hover:text-slate-200" onClick={() => setOpen((v) => !v)}>
        {open ? 'Ocultar distribución técnica' : 'Ver distribución técnica'}
      </button>
      {open && (
        <table className="mt-2 w-full text-left text-xs text-slate-300">
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
      )}
    </div>
  );
}

function AdvancedView({ summary }: { summary: GuidedValidationSummary }) {
  return (
    <div className="space-y-2 border-t border-slate-800 pt-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Etapas (vista científica)</div>
      {summary.stages.map((stage) => <AdvancedStageCard key={stage.stage_id} stage={stage} />)}
    </div>
  );
}

function AdvancedStageCard({ stage }: { stage: GuidedValidationStage }) {
  const [open, setOpen] = useState(false);
  const label = STAGE_LABEL_ES[stage.stage_id] ?? stage.label;
  const statusLabel = STAGE_STATUS_LABEL_ES[stage.status] ?? stage.status;
  // point 13: association_policy's raw next_action text implies "freeze" is
  // the immediate next click, which is misleading before its prerequisites
  // pass -- overridden here with the corrected framing, same underlying data.
  const isPolicyStage = stage.stage_id === 'association_policy';
  const explanation = isPolicyStage && stage.status !== 'PASSED'
    ? 'Primero debe completarse la prueba de sincronización y el control sin dispositivos.'
    : stage.plain_explanation;
  return (
    <div className="rounded border border-slate-700 bg-slate-900/40 p-3">
      <div className="flex items-center justify-between">
        <div className="text-sm font-semibold text-slate-100">{label}</div>
        <span className="rounded bg-black/20 px-2 py-0.5 text-xs font-medium text-slate-300">{statusLabel}</span>
      </div>
      <p className="mt-1 text-xs text-slate-400">{explanation}</p>
      {Object.keys(stage.technical_details).length > 0 && (
        <button className="mt-2 text-[11px] text-slate-500 underline hover:text-slate-300" onClick={() => setOpen((v) => !v)}>
          {open ? 'Ocultar detalle técnico' : 'Ver detalle técnico'}
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

function TechnicalDrilldown({ summary }: { summary: GuidedValidationSummary }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button className="text-xs font-semibold text-slate-400 underline hover:text-slate-200" onClick={() => setOpen((v) => !v)}>
        {open ? 'Ocultar evidencia JSON' : 'Ver evidencia JSON'}
      </button>
      {open && (
        <div className="mt-2 space-y-2 rounded border border-slate-700 bg-slate-950 p-3 text-xs text-slate-300">
          <div>identificador de la ejecución: <span className="font-mono">{summary.run_id}</span></div>
          <div>generado: <span className="font-mono">{summary.generated_at}</span></div>
          <div className="mt-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">artifact_index</div>
          <pre className="max-h-72 overflow-auto rounded bg-black/30 p-2 text-[10px] text-slate-400">{JSON.stringify(summary.artifact_index, null, 2)}</pre>
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">target_absence_summary</div>
          <pre className="max-h-72 overflow-auto rounded bg-black/30 p-2 text-[10px] text-slate-400">{JSON.stringify(summary.target_absence_summary, null, 2)}</pre>
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">association_policy_summary</div>
          <pre className="max-h-72 overflow-auto rounded bg-black/30 p-2 text-[10px] text-slate-400">{JSON.stringify(summary.association_policy_summary, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}
