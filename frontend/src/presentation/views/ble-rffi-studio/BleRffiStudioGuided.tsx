import { useEffect, useState } from 'react';
import { CheckCircle2, ChevronRight, Circle, Loader2 } from 'lucide-react';
import {
  BleNativeScanApiService,
  BleRffiStudioApiService,
  NativeBleDevice,
  StudioAddressBinding,
  StudioBundleManifest,
  StudioCampaignDeviceStatus,
  StudioCampaignSessionResult,
  StudioCaptureDecision,
  StudioCapturePurpose,
  StudioCaptureRecord,
  StudioFeasibility,
  StudioJob,
  StudioDeviceSource,
  StudioLegacyCapture,
  StudioLegacyCaptureListing,
  StudioPhysicalUnit,
  StudioPrepareAndTrainSummary,
  StudioTaskRecommendation,
  StudioTrainingRun,
  NATIVE_DEVICE_FRESHNESS_SECONDS,
  describeApiError,
  describeCampaignSessionError,
  isDeviceActiveNow,
} from '../../../app/services/bleRffiStudioApi';
import { ensureOperation, updateOperation, finishOperation, failOperation } from '../../../app/operations/operationTelemetry';

const api = new BleRffiStudioApiService();
const nativeScan = new BleNativeScanApiService();
const JOB_TERMINAL = new Set(['completed', 'failed', 'cancelled']);

const inputClass = 'h-9 rounded-md border border-slate-700 bg-slate-900 px-2 text-sm text-slate-100';
const buttonClass = 'inline-flex h-10 items-center gap-2 rounded-md border border-cyan-600 bg-cyan-600/20 px-4 text-sm font-medium text-cyan-100 hover:bg-cyan-600/30 disabled:cursor-not-allowed disabled:opacity-40';
const secondaryButtonClass = 'inline-flex h-9 items-center gap-2 rounded-md border border-slate-700 px-3 text-sm text-slate-300 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40';

// Guided mode is real-hardware-only: no synthetic/demo path is offered or
// displayed here (SYNTHETIC_DEMO still exists as a backend regression
// fixture and remains reachable from Advanced mode for engineers).
type DataSource = 'real' | null;

// Human-facing "Tipo de captura" text -- must match StudioRepository's own
// _capture_type_and_decision() mapping exactly, since it is displayed
// alongside rows the backend already labelled this way.
const CAPTURE_TYPE_DEVICE = 'Dispositivo encendido';
const CAPTURE_TYPE_ENVIRONMENT_DECLARED = 'Entorno -- dispositivo apagado';
const CAPTURE_TYPE_ENVIRONMENT_GENERAL = 'Entorno general';
const CAPTURE_TYPE_UNCLASSIFIED = 'Sin clasificar';

type CaptureListFilter = 'ALL' | 'DEVICE' | 'ENVIRONMENT' | 'UNANALYZED';

function matchesCaptureFilter(row: StudioLegacyCapture, filter: CaptureListFilter): boolean {
  if (filter === 'ALL') return true;
  if (filter === 'DEVICE') return row.capture_type_label === CAPTURE_TYPE_DEVICE;
  if (filter === 'ENVIRONMENT') return row.capture_type_label === CAPTURE_TYPE_ENVIRONMENT_DECLARED || row.capture_type_label === CAPTURE_TYPE_ENVIRONMENT_GENERAL;
  return row.capture_decision === 'NOT_ANALYZED_YET' || !row.capture_type_label || row.capture_type_label === CAPTURE_TYPE_UNCLASSIFIED;
}

function StepHeader({ index, title, done, active }: { index: number; title: string; done: boolean; active: boolean }) {
  return (
    <div className="flex items-center gap-3">
      {done ? <CheckCircle2 className="h-5 w-5 text-emerald-400" /> : active ? <Loader2 className="h-5 w-5 animate-spin text-cyan-400" /> : <Circle className="h-5 w-5 text-slate-600" />}
      <span className={`text-sm font-semibold ${active ? 'text-cyan-200' : done ? 'text-emerald-200' : 'text-slate-500'}`}>Paso {index}. {title}</span>
    </div>
  );
}

function previewDatasetIdFor(projectId: string, captureIds: string[]): string {
  // A dataset manifest is immutable once frozen (DATASET_ALREADY_FROZEN on a
  // second attempt), and a fixed "PREVIEW-DS" id collided with itself the
  // moment more than one feasibility check ran for the same operator (the
  // automatic recommendation and the manual "Comprobar" button, or simply
  // adding more captures between two checks). Folding a short, deterministic
  // hash of the actual capture set into the id gives each distinct set of
  // captures its own preview dataset, so recomputing feasibility for the
  // SAME captures reuses it (no collision) and a DIFFERENT set gets a fresh
  // one (reflects what was actually just captured).
  const sortedIds = [...captureIds].sort().join(',');
  let hash = 0;
  for (let i = 0; i < sortedIds.length; i++) hash = (hash * 31 + sortedIds.charCodeAt(i)) >>> 0;
  return `${projectId}-PREVIEW-DS-${hash.toString(36)}`.replace(/[^A-Za-z0-9._-]/g, '');
}

/** Idempotent: a dataset manifest is immutable once frozen, so re-checking
 * feasibility for the exact same capture set must reuse the existing
 * preview dataset (DATASET_ALREADY_FROZEN from api.createDataset is
 * expected and swallowed here) rather than error out. */
async function ensurePreviewDataset(projectId: string, campaignId: string, captureIds: string[]): Promise<string> {
  const previewDatasetId = previewDatasetIdFor(projectId, captureIds);
  try {
    await api.createDataset({ dataset_id: previewDatasetId, dataset_version: '0.0.0', project_id: projectId, campaign_id: campaignId, capture_ids: captureIds });
  } catch (e) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '';
    if (!detail.includes('DATASET_ALREADY_FROZEN')) throw e;
  }
  return previewDatasetId;
}

function formatCaptureTimestamp(iso: string | null | undefined): string {
  if (!iso) return 'fecha desconocida';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return 'fecha desconocida';
  return date.toLocaleString('es-ES', { dateStyle: 'medium', timeStyle: 'medium' });
}

function DeviceLabelBadge({ label, source }: { label?: string; source?: StudioDeviceSource }) {
  if (!label || !source) return <span className="text-slate-600">--</span>;
  const toneClass: Record<StudioDeviceSource, string> = {
    ISOLATION_DECLARED: 'border-cyan-500/40 bg-cyan-500/10 text-cyan-200',
    ADDRESS_MATCH: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200',
    MULTIPLE_ADDRESS_MATCHES: 'border-amber-500/40 bg-amber-500/10 text-amber-200',
    ENVIRONMENT_NO_MATCH: 'border-slate-600 bg-slate-800 text-slate-400',
    NOT_ANALYZED: 'border-slate-700 text-slate-500',
  };
  return <span className={`rounded-full border px-2 py-0.5 text-xs ${toneClass[source]}`}>{label}</span>;
}

const CAPTURE_DECISION_TONE: Record<StudioCaptureDecision, string> = {
  ELIGIBLE_AS_POSITIVE: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200',
  ELIGIBLE_AS_BACKGROUND: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200',
  QUARANTINED: 'border-amber-500/40 bg-amber-500/10 text-amber-200',
  REJECTED: 'border-rose-500/40 bg-rose-500/10 text-rose-200',
  NOT_ANALYZED_YET: 'border-slate-700 text-slate-500',
};
const CAPTURE_DECISION_TEXT: Record<StudioCaptureDecision, string> = {
  ELIGIBLE_AS_POSITIVE: 'ELEGIBLE COMO POSITIVO',
  ELIGIBLE_AS_BACKGROUND: 'ELEGIBLE COMO ENTORNO',
  QUARANTINED: 'CUARENTENA',
  REJECTED: 'RECHAZADA',
  NOT_ANALYZED_YET: 'SIN ANALIZAR',
};

function CaptureDecisionBadge({ decision }: { decision?: StudioCaptureDecision | string | null }) {
  const key = (decision as StudioCaptureDecision) || 'NOT_ANALYZED_YET';
  const toneClass = CAPTURE_DECISION_TONE[key] || 'border-slate-700 text-slate-500';
  const text = CAPTURE_DECISION_TEXT[key] || String(decision || 'SIN ANALIZAR');
  return <span className={`rounded-full border px-2 py-0.5 text-xs ${toneClass}`}>{text}</span>;
}

function DataSourceBadge({ source }: { source: DataSource }) {
  if (!source) return null;
  return <span className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-200">REAL</span>;
}

function StatusRow({ label, value, tone }: { label: string; value: string; tone: 'ok' | 'warn' | 'muted' }) {
  const toneClass = tone === 'ok' ? 'text-emerald-300' : tone === 'warn' ? 'text-amber-300' : 'text-slate-400';
  return (
    <div className="flex items-center justify-between border-b border-slate-800/60 py-1 text-xs last:border-b-0">
      <span className="text-slate-400">{label}</span>
      <span className={`font-semibold ${toneClass}`}>{value}</span>
    </div>
  );
}

interface CampaignSessionRecord {
  session_index: number;
  capture_id: string;
  session_id: string;
  condition_label: string;
  capture_purpose: StudioCapturePurpose;
  target_state?: string;
  eligible_examples: number;
  total_examples: number;
  discontinuities: number;
  acquisition_quality?: string;
  capture_type_label?: string;
  capture_decision?: StudioCaptureDecision;
  started_at_utc: string;
  error?: string;
}

function PipelineStatusBlock({ bundles, trainingRuns }: { bundles: StudioBundleManifest[]; trainingRuns: StudioTrainingRun[] }) {
  const realCompletedRun = trainingRuns.some((r) => r.data_origin === 'REAL_B200' && r.status === 'COMPLETED');
  const realModelAvailable = bundles.some((b) => b.data_origin === 'REAL_B200' && (b.approval_status === 'EVALUATED' || b.approval_status === 'APPROVED_FOR_LIVE_PILOT'));
  const liveMonitorApproved = bundles.some((b) => b.approval_status === 'APPROVED_FOR_LIVE_PILOT');

  return (
    <section className="rounded-lg border border-slate-700 bg-slate-950 p-3">
      <StatusRow label="Pipeline de software" value="OPERATIVO" tone="ok" />
      <StatusRow label="Dataset real disponible" value={realCompletedRun ? 'SUFICIENTE' : 'INSUFICIENTE'} tone={realCompletedRun ? 'ok' : 'warn'} />
      <StatusRow label="Modelo BLE-RFFI con datos reales" value={realModelAvailable ? 'DISPONIBLE' : 'NO DISPONIBLE'} tone={realModelAvailable ? 'ok' : 'warn'} />
      <StatusRow label="Integracion Live Monitor" value={liveMonitorApproved ? 'LISTA (bundle aprobado)' : 'PENDIENTE'} tone={liveMonitorApproved ? 'ok' : 'muted'} />
    </section>
  );
}

export default function BleRffiStudioGuided() {
  const [backendError, setBackendError] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  // Step 1: que quieres capturar (the very first question -- never forces a
  // device to be picked before this, since a background/environment capture
  // may not need one at all).
  const [capturePurpose, setCapturePurpose] = useState<StudioCapturePurpose | null>(null);

  // Step 2a: device (mandatory for TARGET_DEVICE, optional/documentary for
  // BACKGROUND_ENVIRONMENT)
  const [units, setUnits] = useState<StudioPhysicalUnit[]>([]);
  const [selectedUnitId, setSelectedUnitId] = useState('');
  const [newUnitId, setNewUnitId] = useState('');
  const [newUnitFamily, setNewUnitFamily] = useState('');
  const [newUnitManufacturer, setNewUnitManufacturer] = useState('');
  const [newBindingAddress, setNewBindingAddress] = useState('');
  const [showRegisterForm, setShowRegisterForm] = useState(false);
  const [showIdentityHelp, setShowIdentityHelp] = useState(false);
  const [addressBindings, setAddressBindings] = useState<StudioAddressBinding[]>([]);
  const [activeDevices, setActiveDevices] = useState<NativeBleDevice[]>([]);
  const [detectingDevices, setDetectingDevices] = useState(false);
  const [devicesDetectedAt, setDevicesDetectedAt] = useState<Date | null>(null);
  // Filters for the detected-devices dropdown (see unregisteredActiveDevices
  // below) -- a real BLE scan in a populated area easily returns dozens of
  // far-away devices; without these, the operator has to scroll past all of
  // them to find the one they actually want to register.
  const [deviceFilterName, setDeviceFilterName] = useState('');
  const [deviceFilterMac, setDeviceFilterMac] = useState('');
  // -127 dBm is the practical floor of the RSSI scale -- nothing is excluded
  // by default. Real far-away devices commonly report well below -100 dBm,
  // so defaulting the floor any higher silently hid devices the operator
  // used to see; the filter is opt-in, only tightened when the operator
  // actually wants to cut out distant devices.
  const [deviceFilterMinRssiDbm, setDeviceFilterMinRssiDbm] = useState(-127);
  const [deviceFilterMaxAgeSeconds, setDeviceFilterMaxAgeSeconds] = useState(NATIVE_DEVICE_FRESHNESS_SECONDS);

  // Step 2b: condicion experimental / operator declaration
  const [isolationDeclared, setIsolationDeclared] = useState(false);
  const [operatorConfirmedTargetAbsent, setOperatorConfirmedTargetAbsent] = useState(false);

  // Data selected/captured so far
  const [dataSource, setDataSource] = useState<DataSource>(null);
  const [legacy, setLegacy] = useState<StudioLegacyCaptureListing | null>(null);
  const [selectedLegacyIds, setSelectedLegacyIds] = useState<string[]>([]);
  const [captureListFilter, setCaptureListFilter] = useState<CaptureListFilter>('ALL');
  const [projectId, setProjectId] = useState('');
  const [campaignId, setCampaignId] = useState('');
  const [captureIds, setCaptureIds] = useState<string[]>([]);

  // Step 3: iniciar captura (real campaign session via B200)
  const [campaignDeviceStatus, setCampaignDeviceStatus] = useState<StudioCampaignDeviceStatus | null>(null);
  const [campaignBleChannel, setCampaignBleChannel] = useState(37);
  const [campaignDurationSeconds, setCampaignDurationSeconds] = useState(10);
  const [campaignGainDb, setCampaignGainDb] = useState(20);
  const [campaignConditionLabel, setCampaignConditionLabel] = useState('');
  const [campaignTargetEligibleExamples, setCampaignTargetEligibleExamples] = useState(60);
  const [campaignMaxSessions, setCampaignMaxSessions] = useState(6);
  const [campaignJob, setCampaignJob] = useState<StudioJob | null>(null);
  const [campaignSessions, setCampaignSessions] = useState<CampaignSessionRecord[]>([]);
  const campaignJobRunning = !!campaignJob && !JOB_TERMINAL.has(campaignJob.state);
  const campaignEligibleTotal = campaignSessions.reduce((sum, s) => sum + s.eligible_examples, 0);

  // Progress counted separately per capture_purpose -- an operator with one
  // physical unit and no environment recordings yet needs to see exactly
  // that gap, not a single conflated number.
  const deviceSessions = campaignSessions.filter((s) => s.capture_purpose === 'TARGET_DEVICE' && !s.error);
  const backgroundSessions = campaignSessions.filter((s) => s.capture_purpose === 'BACKGROUND_ENVIRONMENT' && !s.error);
  const deviceEligibleSessions = deviceSessions.filter((s) => s.capture_decision === 'ELIGIBLE_AS_POSITIVE');
  const backgroundEligibleSessions = backgroundSessions.filter((s) => s.capture_decision === 'ELIGIBLE_AS_BACKGROUND');
  const deviceEligibleExamples = deviceSessions.reduce((sum, s) => sum + s.eligible_examples, 0);
  const backgroundEligibleExamples = backgroundSessions.reduce((sum, s) => sum + s.eligible_examples, 0);

  // Step 4: objetivo (scientific task)
  const [scientificTasks, setScientificTasks] = useState<Record<string, string>>({});
  const [scientificTask, setScientificTask] = useState('SAME_MODEL_UNIT_IDENTIFICATION');

  // Step 5: prepare + train
  const [speedProfile, setSpeedProfile] = useState<'quick_pilot' | 'normal'>('quick_pilot');
  const [job, setJob] = useState<StudioJob | null>(null);
  const [result, setResult] = useState<StudioPrepareAndTrainSummary | null>(null);

  // Step 6: export
  const [bundleId, setBundleId] = useState('');
  const [exportedBundle, setExportedBundle] = useState<StudioBundleManifest | null>(null);

  // Pipeline-wide status block (top of page)
  const [bundles, setBundles] = useState<StudioBundleManifest[]>([]);
  const [allTrainingRuns, setAllTrainingRuns] = useState<StudioTrainingRun[]>([]);

  const refreshStatusBlock = async () => {
    const [bundlesRes, runsRes] = await Promise.all([api.bundles(), api.trainingRuns()]);
    setBundles(Array.isArray(bundlesRes) ? bundlesRes : []);
    setAllTrainingRuns(Array.isArray(runsRes) ? runsRes : []);
  };

  useEffect(() => {
    (async () => {
      try {
        const [unitsRes, legacyRes, tasksRes, bindingsRes] = await Promise.all([api.physicalUnits(), api.legacyCaptures(), api.scientificTasks(), api.addressBindings()]);
        setUnits(Array.isArray(unitsRes) ? unitsRes : []);
        setLegacy(legacyRes);
        setScientificTasks(tasksRes || {});
        setAddressBindings(Array.isArray(bindingsRes) ? bindingsRes : []);
        await refreshStatusBlock();
        try {
          setCampaignDeviceStatus(await api.campaignDeviceStatus());
        } catch {
          // No B200/hybrid manager available in this environment -- the
          // campaign launcher below stays disabled with an explanation
          // instead of silently pretending hardware is reachable.
          setCampaignDeviceStatus(null);
        }
      } catch (e) {
        setBackendError(describeApiError(e));
      }
    })();
  }, []);

  const run = async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    setError('');
    try {
      await fn();
    } catch (e) {
      setError(describeApiError(e));
    } finally {
      setBusy('');
    }
  };

  // --- Step 1 action ---
  const chooseCapturePurpose = (purpose: StudioCapturePurpose) => {
    setCapturePurpose(purpose);
    setOperatorConfirmedTargetAbsent(false);
    setIsolationDeclared(false);
    if (purpose === 'BACKGROUND_ENVIRONMENT') {
      setSelectedUnitId('');
    }
  };

  // --- Step 2 device actions ---
  const selectExistingUnit = (unit: StudioPhysicalUnit) => {
    setSelectedUnitId(unit.physical_unit_id);
    setProjectId(unit.project_id);
  };

  const clearSelectedUnit = () => setSelectedUnitId('');

  const boundAddressesFor = (physicalUnitId: string): string[] =>
    addressBindings.filter((b) => b.bound_physical_unit_id === physicalUnitId).map((b) => String(b.address).toUpperCase());

  const isUnitActiveNow = (unit: StudioPhysicalUnit): boolean => {
    const addresses = boundAddressesFor(unit.physical_unit_id);
    return activeDevices.some((d) => addresses.includes(d.address.toUpperCase()) && isDeviceActiveNow(d));
  };

  const boundAddressSet = new Set(addressBindings.map((b) => String(b.address).toUpperCase()));
  const unregisteredActiveDevices = activeDevices.filter((d) => isDeviceActiveNow(d) && !boundAddressSet.has(d.address.toUpperCase()));

  const filteredUnregisteredActiveDevices = unregisteredActiveDevices.filter((d) => {
    if (deviceFilterName.trim() && !(d.local_name || '').toLowerCase().includes(deviceFilterName.trim().toLowerCase())) return false;
    if (deviceFilterMac.trim() && !d.address.toLowerCase().includes(deviceFilterMac.trim().toLowerCase())) return false;
    if (typeof d.rssi_dbm === 'number' && d.rssi_dbm < deviceFilterMinRssiDbm) return false;
    if (d.last_seen_utc) {
      const ageSeconds = (Date.now() - new Date(d.last_seen_utc).getTime()) / 1000;
      if (!Number.isNaN(ageSeconds) && ageSeconds > deviceFilterMaxAgeSeconds) return false;
    }
    return true;
  });

  // Real BLE scan (existing native adapter): start it, let advertisements
  // arrive for a few seconds, stop it. This is the same mechanism a real
  // capture session uses -- never simulated/fabricated presence.
  const detectActiveDevices = () => run('detect-devices', async () => {
    setDetectingDevices(true);
    try {
      await nativeScan.start();
      await new Promise((resolve) => setTimeout(resolve, 8000));
      const devices = await nativeScan.devices();
      setActiveDevices(devices);
      setDevicesDetectedAt(new Date());
    } finally {
      await nativeScan.stop().catch(() => {});
      setDetectingDevices(false);
    }
  });

  const registerAndBind = () => run('register-device', async () => {
    const autoProjectId = `BLE-RFFI-${newUnitFamily.trim().toUpperCase().replace(/\s+/g, '_') || 'DEVICE'}`;
    const unit = await api.createPhysicalUnit({ physical_unit_id: newUnitId, project_id: autoProjectId, device_family: newUnitFamily, manufacturer: newUnitManufacturer || undefined, operator_declaration_id: `guided-decl-${newUnitId}` });
    if (newBindingAddress.trim()) {
      await api.createAddressBinding({ project_id: autoProjectId, address: newBindingAddress.trim(), address_type: 'public', physical_unit_id: unit.physical_unit_id, reason: 'Declaracion del operador (modo guiado)' });
    }
    setUnits(await api.physicalUnits());
    setAddressBindings(await api.addressBindings());
    setSelectedUnitId(unit.physical_unit_id);
    setProjectId(unit.project_id);
    setShowRegisterForm(false);
  });

  // Derives the same capture_purpose/target_state/target_reference_id/
  // dataset_role fields the backend contract expects, from what the
  // operator declared in Step 1/2 -- kept in one place so the live-campaign
  // path and the existing-capture path can never diverge on this mapping.
  const deriveCaptureFields = () => {
    if (capturePurpose === 'BACKGROUND_ENVIRONMENT') {
      return {
        capture_purpose: 'BACKGROUND_ENVIRONMENT' as const,
        target_state: 'OPERATOR_DECLARED_POWERED_OFF_OR_REMOVED' as const,
        target_reference_id: selectedUnitId || undefined,
        dataset_role: 'NEGATIVE_CANDIDATE' as const,
      };
    }
    return {
      capture_purpose: 'TARGET_DEVICE' as const,
      target_state: 'POWERED_ON' as const,
      target_reference_id: selectedUnitId || undefined,
      dataset_role: 'POSITIVE_CANDIDATE' as const,
    };
  };

  // --- Step 2/3: use already-existing real captures instead of a live launch ---
  const useRealCaptures = () => run('use-real', async () => {
    const autoCampaignId = `${projectId || 'BLE-RFFI-PROJECT'}-CAMPAIGN-${new Date().toISOString().slice(0, 10)}`;
    const effectiveProjectId = projectId || 'BLE-RFFI-PROJECT';
    setProjectId(effectiveProjectId);
    setCampaignId(autoCampaignId);
    const fields = deriveCaptureFields();
    const built: CampaignSessionRecord[] = [];
    for (const legacyId of selectedLegacyIds) {
      // Always (re)build rather than reusing a previously-built
      // CaptureRecord: the operator's just-declared capture_purpose/
      // target_state/dataset_role must govern this capture, never a stale
      // declaration from an earlier session that happened to reuse the same
      // underlying legacy capture_id. build_capture is idempotent -- it only
      // re-derives the record from the legacy manifest plus these fields.
      const capture: StudioCaptureRecord = await api.createCapture({
        capture_id: legacyId, project_id: effectiveProjectId, campaign_id: autoCampaignId, ...fields,
      });
      // Evidence must be (re)built against the CaptureRecord that was just
      // (re)declared -- the eligibility verdict for a BACKGROUND_ENVIRONMENT
      // capture depends on the suppression rule in EvidenceStage, which only
      // applies at build time. Reusing stale evidence built under a
      // different (or no) declared purpose would silently ignore whatever
      // the operator just confirmed here.
      let evidenceJob = await api.startEvidenceJob(capture.capture_id, { project_id: effectiveProjectId, ble_channel: campaignBleChannel });
      while (!JOB_TERMINAL.has(evidenceJob.state)) {
        await new Promise((resolve) => setTimeout(resolve, 500));
        evidenceJob = await api.job(evidenceJob.job_id);
      }
      const examples = await api.examples(capture.capture_id).catch(() => []);
      const eligible = examples.filter((e) => e.dataset_eligibility === 'ELIGIBLE').length;
      const freshLegacy = await api.legacyCaptures().catch(() => legacy);
      const row = freshLegacy?.captures.find((r) => r.capture_id === capture.capture_id);
      built.push({
        session_index: campaignSessions.length + built.length + 1, capture_id: capture.capture_id, session_id: capture.session_id,
        condition_label: campaignConditionLabel || 'Captura ya existente (seleccionada manualmente)',
        capture_purpose: fields.capture_purpose, target_state: fields.target_state,
        eligible_examples: eligible, total_examples: examples.length,
        discontinuities: 0, acquisition_quality: capture.acquisition_quality,
        capture_type_label: row?.capture_type_label, capture_decision: row?.capture_decision,
        started_at_utc: capture.created_at,
      });
      if (freshLegacy) setLegacy(freshLegacy);
    }
    setCampaignSessions((prev) => [...prev, ...built]);
    setCaptureIds((prev) => [...prev, ...built.map((b) => b.capture_id)]);
    setDataSource('real');
    setResult(null);
    setJob(null);
  });

  const launchCampaignSession = () => run('launch-campaign-session', async () => {
    if (!capturePurpose) return;
    const effectiveProjectId = projectId || 'BLE-RFFI-PROJECT';
    setProjectId(effectiveProjectId);
    if (!campaignId) setCampaignId(`${effectiveProjectId}-CAMPAIGN-${new Date().toISOString().slice(0, 10)}`);
    const effectiveCampaignId = campaignId || `${effectiveProjectId}-CAMPAIGN-${new Date().toISOString().slice(0, 10)}`;
    setCampaignId(effectiveCampaignId);
    const startedJob = await api.startCampaignSession({
      ble_channel: campaignBleChannel, duration_seconds: campaignDurationSeconds, gain_db: campaignGainDb,
      condition_label: campaignConditionLabel || 'Sin condicion declarada por el operador',
      physical_unit_id: selectedUnitId || null, project_id: effectiveProjectId, campaign_id: effectiveCampaignId,
      session_index: campaignSessions.length + 1,
      capture_purpose: capturePurpose,
      isolation_declared: capturePurpose === 'TARGET_DEVICE' ? isolationDeclared : false,
      operator_confirmed_target_absent: capturePurpose === 'BACKGROUND_ENVIRONMENT' ? operatorConfirmedTargetAbsent : undefined,
    });
    setCampaignJob(startedJob);
  });

  useEffect(() => {
    if (!campaignJob || JOB_TERMINAL.has(campaignJob.state)) return;
    const operationId = `ble-rffi-studio-campaign-${campaignJob.job_id}`;
    ensureOperation({ operationId, kind: 'processing', title: 'CAPTURANDO SESION REAL (B200)', phase: campaignJob.phase || 'Iniciando', progressPercent: (campaignJob.overall_progress || 0) * 100, target: campaignConditionLabel, detail: campaignJob.message || '' });
    const timer = window.setInterval(async () => {
      try {
        const next = await api.job(campaignJob.job_id);
        setCampaignJob(next);
        updateOperation(operationId, { phase: next.phase || '', progressPercent: (next.overall_progress || 0) * 100, detail: next.message || '' });
        if (JOB_TERMINAL.has(next.state)) {
          window.clearInterval(timer);
          if (next.state === 'completed') {
            finishOperation(operationId, 'Sesion completada');
            const sessionResult = next.result_summary as unknown as StudioCampaignSessionResult;
            const examples = await api.examples(sessionResult.capture_id).catch(() => []);
            const eligible = examples.filter((e) => e.dataset_eligibility === 'ELIGIBLE').length;
            const capture = await api.getCapture(sessionResult.capture_id).catch(() => null);
            const freshLegacy = await api.legacyCaptures().catch(() => null);
            const row = freshLegacy?.captures.find((r) => r.capture_id === sessionResult.capture_id);
            setCampaignSessions((prev) => [...prev, {
              session_index: prev.length + 1, capture_id: sessionResult.capture_id, session_id: sessionResult.session_id,
              condition_label: sessionResult.condition_label,
              capture_purpose: sessionResult.capture_purpose || 'TARGET_DEVICE', target_state: sessionResult.target_state,
              eligible_examples: eligible, total_examples: examples.length,
              discontinuities: Number(capture?.discontinuities ?? 0), acquisition_quality: capture?.acquisition_quality,
              capture_type_label: row?.capture_type_label, capture_decision: row?.capture_decision,
              started_at_utc: String(capture?.created_at ?? new Date().toISOString()),
            }]);
            setCaptureIds((prev) => [...prev, sessionResult.capture_id]);
            setDataSource('real');
            setResult(null);
            setJob(null);
            // A new real capture just finished -- the "capturas ya
            // existentes" picker must show it without a manual page reload.
            // Best-effort: never let a refresh failure break the session
            // that just genuinely succeeded.
            if (freshLegacy) setLegacy(freshLegacy);
          } else {
            failOperation(operationId, next.error || 'La sesion de captura fallo');
            const errorText = next.error || 'La sesion de captura fallo de forma inesperada.';
            setError(errorText);
            setCampaignSessions((prev) => [...prev, {
              session_index: prev.length + 1, capture_id: '', session_id: '', condition_label: campaignConditionLabel,
              capture_purpose: capturePurpose || 'TARGET_DEVICE',
              eligible_examples: 0, total_examples: 0, discontinuities: 0, started_at_utc: new Date().toISOString(), error: errorText,
            }]);
          }
        }
      } catch (e) {
        window.clearInterval(timer);
        failOperation(operationId, describeApiError(e));
      }
    }, 1000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [campaignJob?.job_id, campaignJob?.state]);

  // --- Step 4: feasibility preview (best-effort, dataset may not exist yet) ---
  const [feasibilityPreview, setFeasibilityPreview] = useState<StudioFeasibility | null>(null);
  const [taskRecommendation, setTaskRecommendation] = useState<StudioTaskRecommendation | null>(null);
  const [recommending, setRecommending] = useState(false);

  // An operator with no RF-fingerprinting background has no way to know
  // e.g. that one physical unit rules out "identificar unidades del mismo
  // modelo" (needs two) -- recommend the best-fitting task automatically
  // instead of leaving the default (SAME_MODEL_UNIT_IDENTIFICATION)
  // selected regardless of what was actually captured.
  useEffect(() => {
    const stepTwoIsDone = captureIds.length > 0 && dataSource !== null;
    if (!stepTwoIsDone) { setTaskRecommendation(null); return; }
    let cancelled = false;
    (async () => {
      setRecommending(true);
      try {
        const previewDatasetId = await ensurePreviewDataset(projectId, campaignId, captureIds);
        const recommendation = await api.taskRecommendation(previewDatasetId, '0.0.0');
        if (cancelled) return;
        setTaskRecommendation(recommendation);
        setScientificTask(recommendation.recommended_task);
        setFeasibilityPreview(recommendation.candidates.find((c) => c.scientific_task === recommendation.recommended_task) ?? null);
      } catch {
        // Best-effort only -- the operator can still pick a task manually
        // and press "Comprobar si hay datos suficientes" themselves.
      } finally {
        if (!cancelled) setRecommending(false);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [captureIds.length, dataSource]);

  // --- Step 5 action ---
  const startPrepareAndTrain = () => run('prepare-and-train', async () => {
    setResult(null);
    setFeasibilityPreview(null);
    const startedJob = await api.prepareAndTrain({
      capture_ids: captureIds, project_id: projectId, campaign_id: campaignId, scientific_task: scientificTask,
      dataset_id: `${projectId}-${scientificTask}-DS`.replace(/[^A-Za-z0-9._-]/g, ''), speed_profile: speedProfile,
    });
    setJob(startedJob);
  });

  useEffect(() => {
    if (!job || JOB_TERMINAL.has(job.state)) return;
    const operationId = `ble-rffi-studio-guided-${job.job_id}`;
    ensureOperation({ operationId, kind: 'processing', title: 'PREPARANDO DATASET Y ENTRENANDO', phase: job.phase || 'Iniciando', progressPercent: (job.overall_progress || 0) * 100, target: scientificTask, detail: job.message || '' });
    const timer = window.setInterval(async () => {
      try {
        const next = await api.job(job.job_id);
        setJob(next);
        updateOperation(operationId, { phase: next.phase || '', progressPercent: (next.overall_progress || 0) * 100, detail: next.message || '' });
        if (JOB_TERMINAL.has(next.state)) {
          window.clearInterval(timer);
          if (next.state === 'completed') {
            finishOperation(operationId, next.result_summary?.stopped_at ? 'Detenido con explicacion' : 'Completado');
            setResult((next.result_summary as unknown as StudioPrepareAndTrainSummary) ?? null);
            const summary = next.result_summary as unknown as StudioPrepareAndTrainSummary | undefined;
            if (summary?.recommended_training_run_id) setBundleId(`${summary.recommended_training_run_id}-bundle`);
            await refreshStatusBlock();
          } else {
            failOperation(operationId, next.error || 'Fallo desconocido');
            setError(next.error || 'El proceso fallo de forma inesperada.');
          }
        }
      } catch (e) {
        window.clearInterval(timer);
        failOperation(operationId, describeApiError(e));
      }
    }, 1000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.job_id, job?.state]);

  // --- Step 6 action ---
  const exportRecommended = () => run('export', async () => {
    if (!result?.recommended_training_run_id) return;
    const exported = await api.exportBundle(result.recommended_training_run_id, {
      bundle_id: bundleId, acceptance_criteria: { min_test_accuracy: 0.5 },
      model_card_text: `# ${bundleId}\nExportado desde el modo guiado de BLE-RFFI Studio (datos reales B200).`,
    });
    setExportedBundle(exported.bundle);
    await refreshStatusBlock();
  });

  const approveExported = () => run('approve', async () => {
    if (!exportedBundle) return;
    const approved = await api.approveBundle(exportedBundle.bundle_id);
    setExportedBundle(approved);
    await refreshStatusBlock();
  });

  const step1Done = capturePurpose !== null;
  const step2Done = step1Done && (capturePurpose === 'TARGET_DEVICE' ? !!selectedUnitId : operatorConfirmedTargetAbsent);
  const step3Done = captureIds.length > 0 && dataSource !== null;
  const step4Done = step3Done && !!scientificTask;
  const step5Done = !!result;
  const jobRunning = !!job && !JOB_TERMINAL.has(job.state);

  const canLaunchLiveSession = step2Done && !!campaignDeviceStatus && campaignDeviceStatus.status === 'AVAILABLE';
  const canUseExistingCaptures = step2Done && selectedLegacyIds.length > 0;

  const visibleCaptureRows = [...(legacy?.captures ?? [])]
    .filter((c) => matchesCaptureFilter(c, captureListFilter))
    .sort((a, b) => new Date(b.created_at_utc ?? 0).getTime() - new Date(a.created_at_utc ?? 0).getTime());

  if (backendError) {
    return (
      <div className="p-6">
        <div className="rounded-md border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-200">
          <div className="font-semibold">No se pudo acceder al servicio BLE-RFFI Studio.</div>
          <div className="mt-1">{backendError}</div>
          <div className="mt-2 text-xs text-rose-300">Verifica que el backend este en ejecucion (puerto 8000) y vuelve a cargar la pagina.</div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5 p-4 text-slate-100">
      <PipelineStatusBlock bundles={bundles} trainingRuns={allTrainingRuns} />
      {error && <div className="rounded-md border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">{error}</div>}

      {/* Step 1: que quieres capturar ahora */}
      <section className="rounded-lg border border-slate-700 bg-slate-950 p-4">
        <StepHeader index={1} title="¿Que quieres capturar ahora?" done={step1Done} active={!step1Done} />
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <button
            className={`rounded-md border p-4 text-left text-sm transition-colors ${capturePurpose === 'TARGET_DEVICE' ? 'border-cyan-500 bg-cyan-500/10' : 'border-slate-700 hover:bg-slate-900'}`}
            onClick={() => chooseCapturePurpose('TARGET_DEVICE')}
          >
            <div className="font-semibold text-slate-100">CAPTURAR MI DISPOSITIVO ENCENDIDO</div>
            <div className="mt-1 text-xs text-slate-400">El dispositivo objetivo esta encendido y transmitiendo. Esta captura podra convertirse en un ejemplo positivo si la evidencia lo confirma.</div>
          </button>
          <button
            className={`rounded-md border p-4 text-left text-sm transition-colors ${capturePurpose === 'BACKGROUND_ENVIRONMENT' ? 'border-cyan-500 bg-cyan-500/10' : 'border-slate-700 hover:bg-slate-900'}`}
            onClick={() => chooseCapturePurpose('BACKGROUND_ENVIRONMENT')}
          >
            <div className="font-semibold text-slate-100">CAPTURAR EL ENTORNO CON MI DISPOSITIVO APAGADO O RETIRADO</div>
            <div className="mt-1 text-xs text-slate-400">El dispositivo objetivo esta apagado o fuera del entorno. No hace falta seleccionar un dispositivo para esto.</div>
          </button>
        </div>
      </section>

      {/* Step 2: preparar la captura */}
      <section className={`rounded-lg border p-4 ${step1Done ? 'border-slate-700 bg-slate-950' : 'border-slate-800 bg-slate-950/50 opacity-50'}`}>
        <StepHeader index={2} title="Preparar la captura" done={step2Done} active={step1Done && !step2Done} />
        {step1Done && (
          <div className="mt-3 space-y-4">
            {capturePurpose === 'TARGET_DEVICE' ? (
              <div className="rounded-md border border-cyan-500/30 bg-cyan-500/5 p-2 text-xs text-cyan-200">
                Enciende el dispositivo y mantenlo en la condicion indicada.
              </div>
            ) : (
              <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-2 text-xs text-amber-200">
                Apaga o retira el dispositivo objetivo antes de comenzar.
              </div>
            )}

            {/* Device selection: mandatory for TARGET_DEVICE, optional/documentary for BACKGROUND_ENVIRONMENT */}
            <div className="space-y-3">
              <div className="text-xs font-semibold text-slate-300">
                {capturePurpose === 'TARGET_DEVICE' ? 'Selecciona la unidad fisica' : 'Que dispositivo se ha apagado (opcional, solo para documentar el experimento)'}
              </div>
              <div className="flex items-center gap-2">
                <button className={secondaryButtonClass} disabled={!!busy} onClick={detectActiveDevices}>
                  {detectingDevices ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                  Detectar dispositivos activos ahora (escaneo real, ~8s)
                </button>
                {devicesDetectedAt && <span className="text-xs text-slate-500">Ultimo escaneo: {devicesDetectedAt.toLocaleTimeString('es-ES')} -- {activeDevices.filter(isDeviceActiveNow).length} dispositivo(s) visto(s)</span>}
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                {capturePurpose === 'BACKGROUND_ENVIRONMENT' && (
                  <button onClick={clearSelectedUnit} className={`rounded-md border p-3 text-left text-sm transition-colors ${!selectedUnitId ? 'border-cyan-500 bg-cyan-500/10' : 'border-slate-700 hover:bg-slate-900'}`}>
                    <div className="font-semibold">Ninguno (entorno general)</div>
                    <div className="text-xs text-slate-400">No se declara un dispositivo especifico apagado.</div>
                  </button>
                )}
                {units.map((u) => {
                  const activeNow = devicesDetectedAt ? isUnitActiveNow(u) : null;
                  return (
                    <button key={u.physical_unit_id} onClick={() => selectExistingUnit(u)} className={`rounded-md border p-3 text-left text-sm transition-colors ${selectedUnitId === u.physical_unit_id ? 'border-cyan-500 bg-cyan-500/10' : 'border-slate-700 hover:bg-slate-900'}`}>
                      <div className="flex items-center justify-between">
                        <div className="font-semibold">{u.model || u.physical_unit_id}</div>
                        {activeNow !== null && (
                          <span className={`rounded-full border px-2 py-0.5 text-xs ${activeNow ? 'border-emerald-500/40 text-emerald-300' : 'border-amber-500/40 text-amber-300'}`}>
                            {activeNow ? 'ACTIVO AHORA' : 'no detectado -- enciendelo'}
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-slate-400">{u.manufacturer || 'Fabricante no declarado'} -- {u.device_family}</div>
                      <div className="mt-1 font-mono text-xs text-slate-500">{u.physical_unit_id}</div>
                    </button>
                  );
                })}
              </div>
              {devicesDetectedAt && unregisteredActiveDevices.length > 0 && (
                <details className="rounded-md border border-cyan-500/30 bg-cyan-500/5 p-2 text-xs">
                  <summary className="cursor-pointer font-semibold text-slate-300">
                    Dispositivos activos ahora sin registrar ({unregisteredActiveDevices.length}) -- click para ver y filtrar
                  </summary>
                  <div className="mt-2 space-y-2">
                    <div className="grid gap-2 sm:grid-cols-4">
                      <label className="flex flex-col gap-1 text-slate-400">Nombre
                        <input className={inputClass} value={deviceFilterName} onChange={(e) => setDeviceFilterName(e.target.value)} placeholder="Filtrar por nombre" />
                      </label>
                      <label className="flex flex-col gap-1 text-slate-400">Direccion MAC
                        <input className={inputClass} value={deviceFilterMac} onChange={(e) => setDeviceFilterMac(e.target.value)} placeholder="Filtrar por MAC" />
                      </label>
                      <label className="flex flex-col gap-1 text-slate-400">RSSI minimo (dBm)
                        <input type="number" className={inputClass} value={deviceFilterMinRssiDbm} onChange={(e) => setDeviceFilterMinRssiDbm(Number(e.target.value))} />
                      </label>
                      <label className="flex flex-col gap-1 text-slate-400">Visto hace menos de (s)
                        <input type="number" min={1} className={inputClass} value={deviceFilterMaxAgeSeconds} onChange={(e) => setDeviceFilterMaxAgeSeconds(Number(e.target.value))} />
                      </label>
                    </div>
                    <div className="text-slate-500">
                      {filteredUnregisteredActiveDevices.length} de {unregisteredActiveDevices.length} dispositivo(s) con estos filtros (direccion detectada por el escaneo real) -- sube el RSSI minimo para ignorar los mas lejanos.
                    </div>
                    <div className="max-h-48 space-y-1 overflow-auto">
                      {filteredUnregisteredActiveDevices.map((d) => (
                        <div key={d.address} className="flex items-center justify-between gap-2">
                          <span className="font-mono">{d.address}</span>
                          <span className="text-slate-500">
                            {d.local_name || 'sin nombre publico'} (rssi {d.rssi_dbm ?? 'N/D'} dBm, visto hace {d.last_seen_utc ? `${Math.round((Date.now() - new Date(d.last_seen_utc).getTime()) / 1000)}s` : 'N/D'})
                          </span>
                          <button className="text-cyan-300 underline" onClick={() => { setNewBindingAddress(d.address); setShowRegisterForm(true); }}>Usar esta direccion</button>
                        </div>
                      ))}
                    </div>
                  </div>
                </details>
              )}

              {!showRegisterForm && <button className={secondaryButtonClass} onClick={() => setShowRegisterForm(true)}>+ Registrar un dispositivo nuevo</button>}
              {showRegisterForm && (
                <div className="space-y-2 rounded-md border border-slate-800 p-3">
                  <div className="grid gap-2 sm:grid-cols-2">
                    <label className="flex flex-col gap-1 text-xs text-slate-400">Identificador de la unidad<input className={inputClass} value={newUnitId} onChange={(e) => setNewUnitId(e.target.value)} placeholder="CC2650-UNIT-01" /></label>
                    <label className="flex flex-col gap-1 text-xs text-slate-400">Modelo / familia<input className={inputClass} value={newUnitFamily} onChange={(e) => setNewUnitFamily(e.target.value)} placeholder="TI SensorTag CC2650" /></label>
                    <label className="flex flex-col gap-1 text-xs text-slate-400">Fabricante<input className={inputClass} value={newUnitManufacturer} onChange={(e) => setNewUnitManufacturer(e.target.value)} placeholder="Texas Instruments" /></label>
                    <label className="flex flex-col gap-1 text-xs text-slate-400">Direccion BLE observada (opcional)<input className={inputClass} value={newBindingAddress} onChange={(e) => setNewBindingAddress(e.target.value)} placeholder="B0:B4:48:C0:36:06" /></label>
                  </div>
                  <button className="text-xs text-cyan-300 underline" onClick={() => setShowIdentityHelp(!showIdentityHelp)}>¿Por que la direccion BLE no es lo mismo que el dispositivo?</button>
                  {showIdentityHelp && (
                    <div className="rounded-md border border-slate-800 bg-slate-900 p-2 text-xs text-slate-400">
                      Un dispositivo puede cambiar de direccion BLE (direcciones aleatorias) o compartir la misma direccion con otro por error de fabrica.
                      Por eso el sistema separa la identidad del dispositivo (que tu declaras) de las direcciones observadas (que el sistema vincula con evidencia).
                    </div>
                  )}
                  <button className={buttonClass} disabled={!!busy || !newUnitId || !newUnitFamily} onClick={registerAndBind}>Registrar dispositivo</button>
                </div>
              )}
            </div>

            {/* Common capture configuration */}
            <div className="rounded-md border border-slate-800 p-3">
              <div className="grid gap-2 sm:grid-cols-4">
                <label className="flex flex-col gap-1 text-xs text-slate-400">Canal BLE
                  <select className={inputClass} value={campaignBleChannel} onChange={(e) => setCampaignBleChannel(Number(e.target.value))}>
                    <option value={37}>37</option><option value={38}>38</option><option value={39}>39</option>
                  </select>
                </label>
                <label className="flex flex-col gap-1 text-xs text-slate-400">Duracion maxima (s)<input type="number" min={1} max={30} className={inputClass} value={campaignDurationSeconds} onChange={(e) => setCampaignDurationSeconds(Number(e.target.value))} /></label>
                <label className="flex flex-col gap-1 text-xs text-slate-400">Ganancia (dB)<input type="number" min={0} max={70} className={inputClass} value={campaignGainDb} onChange={(e) => setCampaignGainDb(Number(e.target.value))} /></label>
                <label className="flex flex-col gap-1 text-xs text-slate-400">Objetivo de ejemplos elegibles<input type="number" min={1} className={inputClass} value={campaignTargetEligibleExamples} onChange={(e) => setCampaignTargetEligibleExamples(Number(e.target.value))} /></label>
              </div>
              <label className="mt-2 flex flex-col gap-1 text-xs text-slate-400">Condicion experimental (declarada por el operador, ej. "encendido a 0.5m" / "apagado / ambiente")
                <input className={inputClass} value={campaignConditionLabel} onChange={(e) => setCampaignConditionLabel(e.target.value)} placeholder="Describe como esta fisicamente el dispositivo ahora mismo" />
              </label>

              {capturePurpose === 'TARGET_DEVICE' ? (
                <label className="mt-2 flex items-start gap-2 text-xs text-slate-400">
                  <input type="checkbox" className="mt-0.5" checked={isolationDeclared} onChange={(e) => setIsolationDeclared(e.target.checked)} />
                  <span>
                    Confirmo aislamiento fisico: solo esta unidad estaba transmitiendo cerca durante toda la captura.
                    <span className="block text-slate-500">
                      Usa esto cuando el dispositivo no tenga una direccion BLE fija (muchos dispositivos reales rotan su direccion, y entonces la coincidencia por direccion nunca funciona). Es una verdad de referencia mas debil que una coincidencia por direccion -- depende de que el aislamiento fisico sea correcto.
                    </span>
                  </span>
                </label>
              ) : (
                <label className="mt-2 flex items-start gap-2 text-xs text-slate-400">
                  <input type="checkbox" className="mt-0.5" checked={operatorConfirmedTargetAbsent} onChange={(e) => setOperatorConfirmedTargetAbsent(e.target.checked)} />
                  <span>
                    Confirmo que el dispositivo objetivo estaba apagado o fuera del entorno durante toda la captura.
                    <span className="block text-slate-500">
                      El sistema nunca deduce que el dispositivo estaba apagado por la ausencia de señal -- esta declaracion es la unica fuente de ese dato, y por eso es obligatoria antes de lanzar una captura de entorno.
                    </span>
                  </span>
                </label>
              )}
            </div>
          </div>
        )}
      </section>

      {/* Step 3: iniciar captura */}
      <section className={`rounded-lg border p-4 ${step2Done ? 'border-slate-700 bg-slate-950' : 'border-slate-800 bg-slate-950/50 opacity-50'}`}>
        <StepHeader index={3} title="Iniciar captura" done={step3Done} active={step2Done && !step3Done} />
        {step2Done && (
          <div className="mt-3 space-y-3">
            <div className="rounded-md border border-slate-800 p-3">
              <div className="mb-2 flex items-center justify-between text-xs">
                <span className="font-semibold text-slate-300">Captura real con B200</span>
                {campaignDeviceStatus ? (
                  <span className={`rounded-full border px-2 py-0.5 ${campaignDeviceStatus.status === 'AVAILABLE' ? 'border-emerald-500/40 text-emerald-300' : 'border-amber-500/40 text-amber-300'}`}>
                    B200: {campaignDeviceStatus.status}{campaignDeviceStatus.owner ? ` (en uso por ${campaignDeviceStatus.owner})` : ''}
                  </span>
                ) : (
                  <span className="rounded-full border border-rose-500/40 px-2 py-0.5 text-rose-300">B200 no disponible en este entorno</span>
                )}
              </div>
              {!campaignDeviceStatus && (
                <div className="mb-2 text-xs text-slate-500">
                  El orquestador de campaña real requiere que el modulo BLE Lab (con el B200 y el escaneo nativo) este activo en el backend. Mientras tanto puedes usar capturas reales ya existentes mas abajo.
                </div>
              )}
              <div className="flex items-center gap-2">
                <button className={buttonClass} disabled={!!busy || campaignJobRunning || !canLaunchLiveSession} onClick={launchCampaignSession}>
                  {campaignJobRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <ChevronRight className="h-4 w-4" />}
                  Iniciar captura real con B200
                </button>
                {campaignJob && <span className="text-xs text-slate-400">{campaignJob.message || campaignJob.state}</span>}
              </div>
            </div>

            <div className="flex items-center gap-2 text-xs text-slate-500"><div className="h-px flex-1 bg-slate-800" />o, alternativamente<div className="h-px flex-1 bg-slate-800" /></div>

            <div>
              <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-slate-400">
                <span>Capturas ya existentes, mas recientes primero (selecciona una o varias):</span>
                <span className="ml-auto flex gap-1">
                  {(['ALL', 'DEVICE', 'ENVIRONMENT', 'UNANALYZED'] as CaptureListFilter[]).map((f) => (
                    <button
                      key={f}
                      className={`rounded-full border px-2 py-0.5 text-xs ${captureListFilter === f ? 'border-cyan-500 bg-cyan-500/10 text-cyan-200' : 'border-slate-700 text-slate-400 hover:bg-slate-900'}`}
                      onClick={() => setCaptureListFilter(f)}
                    >
                      {f === 'ALL' ? 'Todas' : f === 'DEVICE' ? 'Dispositivo' : f === 'ENVIRONMENT' ? 'Entorno' : 'Sin analizar'}
                    </button>
                  ))}
                </span>
              </div>
              <div className="max-h-56 overflow-auto rounded border border-slate-800">
                <table className="w-full text-left text-xs">
                  <thead className="sticky top-0 bg-slate-900 text-slate-500"><tr><th className="p-1"></th><th className="p-1">Captura</th><th className="p-1">Hora</th><th className="p-1">Duracion</th><th className="p-1">Dispositivo</th><th className="p-1">Tipo de captura</th></tr></thead>
                  <tbody>
                    {visibleCaptureRows.map((c) => (
                      <tr key={c.capture_id} className="cursor-pointer border-t border-slate-800 hover:bg-slate-900" onClick={() => setSelectedLegacyIds((prev) => prev.includes(c.capture_id) ? prev.filter((id) => id !== c.capture_id) : [...prev, c.capture_id])}>
                        <td className="p-1"><input type="checkbox" checked={selectedLegacyIds.includes(c.capture_id)} onChange={() => {}} /></td>
                        <td className="p-1 font-mono">{c.capture_id}</td>
                        <td className="p-1 text-cyan-300">{formatCaptureTimestamp(c.created_at_utc)}</td>
                        <td className="p-1 text-slate-500">{typeof c.duration_seconds === 'number' ? `${c.duration_seconds.toFixed(1)}s` : 'N/D'}</td>
                        <td className="p-1"><DeviceLabelBadge label={c.device_label} source={c.device_source} /></td>
                        <td className="p-1 text-slate-400">{c.capture_type_label || CAPTURE_TYPE_UNCLASSIFIED}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <button className={`${buttonClass} mt-2`} disabled={!!busy || !canUseExistingCaptures} onClick={useRealCaptures}>Usar {selectedLegacyIds.length || ''} captura(s) real(es)</button>
            </div>

            {step3Done && <div className="text-xs text-slate-400">Origen seleccionado: <DataSourceBadge source={dataSource} /> -- {captureIds.length} captura(s), proyecto <span className="font-mono">{projectId}</span></div>}

            {campaignSessions.length > 0 && (
              <div className="mt-3 rounded-md border border-slate-800 p-2 text-xs">
                <div className="mb-1 font-semibold text-slate-300">
                  {campaignSessions.length} sesion(es) registrada(s) (max {campaignMaxSessions}) -- Ejemplos elegibles: {campaignEligibleTotal} / objetivo {campaignTargetEligibleExamples}
                </div>
                <label className="mb-1 flex items-center gap-1 text-slate-500">Maximo de sesiones (limite de seguridad)<input type="number" min={1} className={`${inputClass} h-7 w-16`} value={campaignMaxSessions} onChange={(e) => setCampaignMaxSessions(Number(e.target.value))} /></label>

                {/* Paso 4 del pedido del operador: resultado de cada sesion */}
                <table className="w-full text-left">
                  <thead className="text-slate-500"><tr><th className="p-1">#</th><th className="p-1">Captura</th><th className="p-1">Hora</th><th className="p-1">Tipo</th><th className="p-1">Estado declarado</th><th className="p-1">Condicion</th><th className="p-1">Paquetes</th><th className="p-1">Elegibles</th><th className="p-1">Calidad</th><th className="p-1">Decision</th></tr></thead>
                  <tbody>
                    {campaignSessions.map((s) => (
                      <tr key={s.session_index} className="border-t border-slate-800">
                        <td className="p-1">{s.session_index}</td>
                        <td className="p-1 font-mono text-slate-500">{s.capture_id || '--'}</td>
                        <td className="p-1 text-cyan-300">{formatCaptureTimestamp(s.started_at_utc)}</td>
                        <td className="p-1">{s.capture_type_label || (s.capture_purpose === 'TARGET_DEVICE' ? CAPTURE_TYPE_DEVICE : CAPTURE_TYPE_ENVIRONMENT_GENERAL)}</td>
                        <td className="p-1 text-slate-400">{s.target_state === 'POWERED_ON' ? 'Encendido' : s.target_state ? 'Apagado/retirado (declarado)' : '--'}</td>
                        <td className="p-1">{s.condition_label}</td>
                        <td className="p-1">{s.error ? '-' : s.total_examples}</td>
                        <td className="p-1">{s.error ? '-' : s.eligible_examples}</td>
                        <td className="p-1">{s.error ? '-' : (s.acquisition_quality || 'N/D')}</td>
                        <td className="p-1">
                          {s.error ? (
                            <details>
                              <summary className="cursor-pointer text-rose-300">Fallida (ver motivo)</summary>
                              <div className="mt-1 max-w-md whitespace-normal text-slate-300">{describeCampaignSessionError(s.error)}</div>
                              <div className="mt-1 max-w-md whitespace-normal break-all text-slate-600">Detalle tecnico: {s.error}</div>
                            </details>
                          ) : <CaptureDecisionBadge decision={s.capture_decision} />}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>

                {/* Progreso de la campaña, contado por separado */}
                <div className="mt-2 space-y-0.5 text-slate-400">
                  <div>Dispositivo{selectedUnitId ? ` ${selectedUnitId}` : ''}: {deviceSessions.length} sesion(es) realizada(s), {deviceEligibleSessions.length} elegible(s), {deviceEligibleExamples} ejemplo(s) elegible(s).</div>
                  <div>Entorno (dispositivo apagado): {backgroundSessions.length} sesion(es) realizada(s), {backgroundEligibleSessions.length} elegible(s), {backgroundEligibleExamples} ejemplo(s) negativo(s) elegible(s).</div>
                </div>

                {campaignEligibleTotal >= campaignTargetEligibleExamples ? (
                  <div className="mt-2 rounded-md border border-emerald-500/40 bg-emerald-500/10 p-2 text-emerald-200">Objetivo de ejemplos elegibles alcanzado. Puedes continuar al paso 4 o seguir capturando mas sesiones.</div>
                ) : campaignSessions.length >= campaignMaxSessions ? (
                  <div className="mt-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-amber-200">Se alcanzo el limite de seguridad de sesiones sin llegar al objetivo. Continuar puede resultar en un dataset insuficiente (se explicara en el paso 4).</div>
                ) : (
                  <div className="mt-2 text-slate-500">Todavia no se alcanza el objetivo ni el limite de seguridad -- puedes lanzar otra sesion.</div>
                )}
              </div>
            )}
          </div>
        )}
      </section>

      {/* Step 4 */}
      <section className={`rounded-lg border p-4 ${step3Done ? 'border-slate-700 bg-slate-950' : 'border-slate-800 bg-slate-950/50 opacity-50'}`}>
        <StepHeader index={4} title="Elegir el objetivo del entrenamiento" done={step4Done} active={step3Done} />
        {step3Done && (
          <div className="mt-3 space-y-2">
            {recommending && <div className="flex items-center gap-2 text-xs text-slate-400"><Loader2 className="h-3 w-3 animate-spin" />Calculando cual objetivo encaja mejor con lo que ya tienes...</div>}
            {taskRecommendation && !recommending && (
              <div className="rounded-md border border-cyan-500/30 bg-cyan-500/5 p-2 text-xs text-cyan-200">
                <span className="font-semibold">Recomendado: {taskRecommendation.recommended_task_display}.</span> {taskRecommendation.reason}
              </div>
            )}
            <select className={inputClass} value={scientificTask} onChange={(e) => { setScientificTask(e.target.value); setFeasibilityPreview(taskRecommendation?.candidates.find((c) => c.scientific_task === e.target.value) ?? null); }}>
              {Object.entries(scientificTasks).map(([key, label]) => <option key={key} value={key}>{label}{taskRecommendation?.recommended_task === key ? ' (recomendado)' : ''}</option>)}
            </select>
            <button className={secondaryButtonClass} disabled={!!busy} onClick={() => run('feasibility', async () => {
              // Feasibility needs a dataset; build a lightweight preview dataset from the selected captures.
              const previewDatasetId = await ensurePreviewDataset(projectId, campaignId, captureIds);
              const preview = await api.feasibility(previewDatasetId, '0.0.0', scientificTask);
              setFeasibilityPreview(preview);
            })}>Comprobar si hay datos suficientes</button>
            {feasibilityPreview && (
              <div className={`rounded-md border p-3 text-sm ${feasibilityPreview.feasible ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-100' : 'border-amber-500/40 bg-amber-500/10 text-amber-100'}`}>
                <div className="font-semibold">{feasibilityPreview.feasible ? 'Hay datos suficientes para esta tarea.' : 'Todavia no hay datos suficientes para entrenar este objetivo.'}</div>
                <div className="mt-1 whitespace-pre-line text-xs opacity-90">{feasibilityPreview.human_summary}</div>
                {feasibilityPreview.next_steps.length > 0 && (
                  <div className="mt-2 text-xs">
                    <div className="font-semibold opacity-90">Que hacer ahora:</div>
                    <ul className="mt-1 list-disc space-y-0.5 pl-4 opacity-90">
                      {feasibilityPreview.next_steps.map((step, i) => <li key={i}>{step}</li>)}
                    </ul>
                  </div>
                )}
                <details className="mt-2 text-xs opacity-70"><summary className="cursor-pointer">Detalles avanzados</summary>
                  <pre className="mt-1 overflow-auto">{JSON.stringify({ have: feasibilityPreview.have, need: feasibilityPreview.need }, null, 2)}</pre>
                </details>
              </div>
            )}
          </div>
        )}
      </section>

      {/* Step 5 */}
      <section className={`rounded-lg border p-4 ${step4Done ? 'border-slate-700 bg-slate-950' : 'border-slate-800 bg-slate-950/50 opacity-50'}`}>
        <StepHeader index={5} title="Preparar dataset y entrenar" done={step5Done} active={step4Done && !step5Done} />
        {step4Done && (
          <div className="mt-3 space-y-3">
            <div className="flex items-center gap-3">
              <label className="flex items-center gap-2 text-xs text-slate-400"><input type="radio" checked={speedProfile === 'quick_pilot'} onChange={() => setSpeedProfile('quick_pilot')} />Piloto rapido (solo modelos base, mas rapido)</label>
              <label className="flex items-center gap-2 text-xs text-slate-400"><input type="radio" checked={speedProfile === 'normal'} onChange={() => setSpeedProfile('normal')} />Entrenamiento normal (incluye CNN si hay datos suficientes)</label>
            </div>
            <button className={buttonClass} disabled={!!busy || jobRunning} onClick={startPrepareAndTrain}>
              {jobRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <ChevronRight className="h-4 w-4" />}
              Preparar dataset y entrenar
            </button>
            {job && <div className="text-xs text-slate-400">{job.message || job.state}</div>}
          </div>
        )}
      </section>

      {/* Step 6 */}
      {result && (
        <section className="rounded-lg border border-slate-700 bg-slate-950 p-4">
          <StepHeader index={6} title="Resultado" done={!!exportedBundle} active={!exportedBundle} />
          <div className="mt-3 space-y-3">
            <div className="flex items-center gap-2 text-xs text-slate-400">Origen: <DataSourceBadge source={dataSource} /></div>

            {result.stopped_at && result.stopped_at === 'model_selection' && (
              <div className="rounded-md border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">
                <div className="font-semibold">NO_MODEL_ACCEPTED: ningun modelo candidato paso el criterio minimo de aceptacion.</div>
                <div className="mt-1 whitespace-pre-line text-xs opacity-90">{result.stopped_reason}</div>
                <div className="mt-1 text-xs opacity-70">
                  Los datos eran suficientes para entrenar (todos los candidatos se entrenaron y se compararon en VALIDATION); ninguno alcanzo la calidad minima para recomendarse. No se exporta automaticamente el modelo menos malo.
                </div>
                {!!result.trained_models.length && (
                  <table className="mt-2 w-full text-left text-xs">
                    <thead className="text-slate-400"><tr><th className="p-1">Modelo</th><th className="p-1">Puntuacion (VALIDATION)</th></tr></thead>
                    <tbody>
                      {result.trained_models.map((m) => (
                        <tr key={m.training_run_id} className="border-t border-slate-800"><td className="p-1">{m.model_type}</td><td className="p-1">{m.composite_score.toFixed(3)}</td></tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}

            {result.stopped_at && result.stopped_at !== 'model_selection' && (
              <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-100">
                <div className="font-semibold">Todavia no hay datos suficientes para entrenar este objetivo.</div>
                <div className="mt-1 whitespace-pre-line text-xs opacity-90">{result.stopped_reason}</div>
                {!!result.feasibility?.next_steps?.length && (
                  <div className="mt-2 text-xs">
                    <div className="font-semibold opacity-90">Que hacer ahora:</div>
                    <ul className="mt-1 list-disc space-y-0.5 pl-4 opacity-90">
                      {result.feasibility.next_steps.map((step, i) => <li key={i}>{step}</li>)}
                    </ul>
                  </div>
                )}
                <details className="mt-2 text-xs opacity-70"><summary className="cursor-pointer">Detalles avanzados</summary>
                  <pre>stopped_at: {result.stopped_at}{'\n'}split_status: {result.split_status}</pre>
                </details>
              </div>
            )}

            {!result.stopped_at && (
              <>
                <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 p-2 text-xs font-semibold text-emerald-200">
                  MODELO ENTRENADO CON B200 REAL
                </div>
                <table className="w-full text-left text-xs">
                  <thead className="text-slate-400"><tr><th className="p-1">Modelo</th><th className="p-1">Estado</th><th className="p-1">Puntuacion (VALIDATION)</th></tr></thead>
                  <tbody>
                    {result.trained_models.map((m) => (
                      <tr key={m.training_run_id} className={`border-t border-slate-800 ${m.training_run_id === result.recommended_training_run_id ? 'bg-cyan-500/10' : ''}`}>
                        <td className="p-1">{m.model_type}</td>
                        <td className="p-1">{m.training_run_id === result.recommended_training_run_id ? 'Recomendado' : 'Completado'}</td>
                        <td className="p-1">{m.composite_score.toFixed(3)}</td>
                      </tr>
                    ))}
                    {result.skipped_models.map((m) => (
                      <tr key={m.model_type} className="border-t border-slate-800 text-slate-500">
                        <td className="p-1">{m.model_type}</td><td className="p-1" colSpan={2}>No disponible: {m.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>

                {result.recommended_training_run_id ? (
                  <div className="rounded-md border border-cyan-500/40 bg-cyan-500/10 p-3 text-sm text-cyan-100">
                    <div className="font-semibold">Modelo recomendado: {result.trained_models.find((m) => m.training_run_id === result.recommended_training_run_id)?.model_type}</div>
                    <div className="mt-1 text-xs opacity-90">Motivo (VALIDATION): {result.recommended_reason}</div>
                    {result.final_test_evaluation ? (
                      <div className="mt-2 border-t border-cyan-500/30 pt-2 text-xs">
                        <div className="font-semibold opacity-90">Evaluacion final (TEST, unica, tras congelar el modelo)</div>
                        <div className="mt-1 opacity-90">
                          exactitud: {typeof result.final_test_evaluation.accuracy === 'number' ? result.final_test_evaluation.accuracy.toFixed(3) : 'N/D'}
                          {'  '}| ejemplos: {String(result.final_test_evaluation.n_examples ?? 'N/D')}
                        </div>
                        <details className="mt-1 opacity-70"><summary className="cursor-pointer">Detalle por clase</summary>
                          <pre className="whitespace-pre-wrap">{JSON.stringify(result.final_test_evaluation, null, 2)}</pre>
                        </details>
                      </div>
                    ) : (
                      <div className="mt-2 border-t border-cyan-500/30 pt-2 text-xs opacity-70">Evaluacion final sobre TEST aun no disponible para esta ejecucion.</div>
                    )}
                  </div>
                ) : (
                  <div className="rounded-md border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">Ningun modelo cumple los criterios de aceptacion.</div>
                )}

                {result.recommended_training_run_id && !exportedBundle && (
                  <div className="flex items-end gap-2">
                    <label className="flex flex-col gap-1 text-xs text-slate-400">bundle_id<input className={inputClass} value={bundleId} onChange={(e) => setBundleId(e.target.value)} /></label>
                    <button className={buttonClass} disabled={!!busy} onClick={exportRecommended}>Exportar modelo</button>
                  </div>
                )}
                {exportedBundle && exportedBundle.approval_status === 'EVALUATED' && (
                  <div className="space-y-2 rounded-md border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm text-emerald-100">
                    <div>Bundle exportado correctamente. Estado: EVALUATED (datos reales B200)</div>
                    <button className={secondaryButtonClass} onClick={approveExported}>Aprobar para piloto en Live Monitor</button>
                  </div>
                )}
                {exportedBundle && exportedBundle.approval_status === 'APPROVED_FOR_LIVE_PILOT' && (
                  <div className="space-y-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm text-emerald-100">
                    <div>Aprobado para piloto en Live Monitor.</div>
                    <div className="text-xs text-amber-200">
                      La seleccion de modelos BLE-RFFI dentro de Live Monitor, y la inferencia sobre I/Q en vivo (no solo PSD), todavia no estan conectadas -- ver "funciones no conectadas".
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
