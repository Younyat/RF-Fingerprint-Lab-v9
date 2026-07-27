import axios from 'axios';

export type StudioDeviceSource = 'ISOLATION_DECLARED' | 'ADDRESS_MATCH' | 'MULTIPLE_ADDRESS_MATCHES' | 'ENVIRONMENT_NO_MATCH' | 'NOT_ANALYZED';
export type StudioCapturePurpose = 'TARGET_DEVICE' | 'BACKGROUND_ENVIRONMENT';
export type StudioTargetState = 'POWERED_ON' | 'OPERATOR_DECLARED_POWERED_OFF_OR_REMOVED';
export type StudioDatasetRole = 'POSITIVE_CANDIDATE' | 'NEGATIVE_CANDIDATE';
export type StudioCaptureDecision = 'ELIGIBLE_AS_POSITIVE' | 'ELIGIBLE_AS_BACKGROUND' | 'QUARANTINED' | 'REJECTED' | 'NOT_ANALYZED_YET';
export interface StudioLegacyCapture extends Record<string, unknown> {
  capture_id: string;
  execution_id?: string | null;
  campaign_id?: string | null;
  condition_id?: string | null;
  created_at_utc?: string | null;
  duration_seconds?: number | null;
  ble_channel?: number;
  center_frequency_hz?: number;
  sample_rate_sps?: number;
  target_address?: string | null;
  acquisition_quality?: string;
  replay?: Record<string, unknown> | null;
  /** One-glance "whose recording is this" -- never leave the operator
   * guessing between a real device's session and pure environmental noise
   * from an opaque capture_id alone. */
  device_label?: string;
  device_source?: StudioDeviceSource;
  /** Human-facing "Tipo de captura" (Dispositivo encendido / Entorno --
   * dispositivo apagado / Entorno general / Sin clasificar / Sintetica de
   * pruebas) -- what the operator declared this capture was FOR, distinct
   * from device_label (which device it turned out to be). */
  capture_type_label?: string;
  capture_decision?: StudioCaptureDecision;
}
export interface StudioLegacyCaptureListing {
  captures: StudioLegacyCapture[];
  classification: Record<string, string | null>;
}

export interface StudioPhysicalUnit extends Record<string, unknown> {
  physical_unit_id: string;
  project_id: string;
  device_family: string;
  manufacturer?: string | null;
  model?: string | null;
  status: string;
  first_registered_at: string;
}
export interface StudioAddressBinding extends Record<string, unknown> {
  binding_id: string;
  project_id: string;
  address: string;
  address_type: string;
  bound_physical_unit_id?: string | null;
  binding_status: string;
  first_seen: string;
  last_seen: string;
}

export interface StudioCaptureRecord extends Record<string, unknown> {
  capture_id: string;
  project_id: string;
  campaign_id: string;
  session_id: string;
  execution_id: string;
  physical_unit_id?: string | null;
  capture_purpose?: StudioCapturePurpose | null;
  target_state?: StudioTargetState | null;
  target_reference_id?: string | null;
  dataset_role?: StudioDatasetRole | null;
  sample_rate_sps: number;
  center_frequency_hz: number;
  sample_count: number;
  iq_sha256: string;
  acquisition_quality: string;
  replay_status: string;
  created_at: string;
}

export interface StudioExample extends Record<string, unknown> {
  example_id: string;
  capture_id: string;
  physical_unit_id?: string | null;
  association_status: string;
  quality_status: string;
  dataset_eligibility: string;
}

export type StudioJobState = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
export interface StudioJob extends Record<string, unknown> {
  job_id: string;
  job_type: 'EVIDENCE_BUILD' | 'TRAINING_RUN' | 'PREPARE_AND_TRAIN' | 'CAMPAIGN_SESSION';
  state: StudioJobState;
  phase?: string | null;
  overall_progress?: number;
  message?: string | null;
  result_summary?: Record<string, unknown>;
  training_run_id?: string;
  error?: string;
}

export type StudioDataOrigin = 'REAL_B200' | 'SYNTHETIC_TEST_ONLY';
export type StudioOperationalUse = 'ALLOWED' | 'FORBIDDEN';

export interface StudioDatasetManifest extends Record<string, unknown> {
  dataset_id: string;
  dataset_version: string;
  data_origin: StudioDataOrigin;
  frozen: boolean;
  physical_units: string[];
  captures: string[];
  sessions: string[];
  example_ids: string[];
  class_distribution: Record<string, number>;
  dataset_manifest_sha256?: string | null;
}
export interface StudioDatasetBuildResult {
  dataset: StudioDatasetManifest;
  n_selected: number;
  n_excluded: number;
  excluded_reasons: Record<string, string>;
}

export interface StudioQualityReport extends Record<string, unknown> {
  dataset_id: string;
  dataset_version: string;
  exact_duplicates: { status: string; duplicate_groups: string[][] };
  sample_overlap: { status: string; overlapping_pairs: string[][] };
  near_duplicates: { status: string; flagged_pairs: string[][]; note?: string };
  gate_decision: 'ACCEPTED_FOR_TRAINING' | 'ACCEPTED_WITH_LIMITATIONS' | 'NOT_ACCEPTED_FOR_TRAINING';
  gate_reasons: string[];
}

export interface StudioSplitManifest extends Record<string, unknown> {
  dataset_id: string;
  dataset_version: string;
  scientific_task: string;
  split_status: 'READY' | 'NOT_FEASIBLE';
  infeasibility_reason?: string | null;
  assignments: { example_id: string; physical_unit_id?: string | null; session_id: string; split: string }[];
  leakage_check: { status: string; overlapping_keys: Record<string, string[]> };
  split_manifest_sha256?: string | null;
}

export interface StudioTrainingRun extends Record<string, unknown> {
  training_run_id: string;
  status: string;
  model_type: string;
  scientific_task: string;
  dataset_id: string;
  dataset_version: string;
  data_origin: StudioDataOrigin;
  operational_use: StudioOperationalUse;
  metrics?: Record<string, { accuracy: number | null; n_examples: number }> | null;
  label_classes?: string[] | null;
  error?: Record<string, unknown> | null;
}

export interface StudioSplitEvaluationReport {
  split: string;
  n_examples: number;
  n_comparable_to_known_classes: number;
  accuracy: number | null;
  precision_per_class: Record<string, number>;
  recall_per_class: Record<string, number>;
  f1_per_class: Record<string, number>;
  confusion_matrix: Record<string, Record<string, number>>;
}
export interface StudioEvaluationResult {
  evaluation_report: Record<string, StudioSplitEvaluationReport>;
  calibration: { acceptance_threshold: number | null; calibrated_on: string; min_identified_precision: number };
}

export interface StudioBundleManifest extends Record<string, unknown> {
  bundle_id: string;
  training_run_id: string;
  data_origin: StudioDataOrigin;
  operational_use: StudioOperationalUse;
  artifact_hashes: Record<string, string>;
  bundle_sha256?: string | null;
  approval_status: 'DRAFT' | 'EVALUATED' | 'SYNTHETIC_PIPELINE_VERIFIED' | 'APPROVED_FOR_LIVE_PILOT' | 'REJECTED';
}
export interface StudioExportResult {
  bundle: StudioBundleManifest;
  gate_reasons: string[];
}
export interface StudioInferenceDecision {
  example_id: string;
  distance: number | null;
  class_probability: number | null;
  acceptance_threshold: number | null;
  predicted_class: string | null;
  final_decision: 'IDENTIFIED' | 'UNKNOWN' | 'INSUFFICIENT_EVIDENCE';
}

export class BleRffiStudioApiService {
  constructor(private readonly baseURL = 'http://localhost:8000') {}
  // A getter, not a field initializer: a `= ${this.baseURL}/...` class field
  // initializer runs before TypeScript assigns constructor parameter
  // properties, so `this.baseURL` reads as undefined at that point -- every
  // request silently became a same-origin relative "undefined/api/..." URL.
  private get root() { return `${this.baseURL}/api/ble-rffi-studio`; }

  async legacyCaptures() { return (await axios.get<StudioLegacyCaptureListing>(`${this.root}/legacy-captures`)).data; }

  async physicalUnits() { return (await axios.get<StudioPhysicalUnit[]>(`${this.root}/physical-units`)).data; }
  async createPhysicalUnit(body: { physical_unit_id: string; project_id: string; device_family: string; manufacturer?: string; model?: string; operator_declaration_id: string }) {
    return (await axios.post<StudioPhysicalUnit>(`${this.root}/physical-units`, body)).data;
  }
  async addressBindings() { return (await axios.get<StudioAddressBinding[]>(`${this.root}/address-bindings`)).data; }
  async createAddressBinding(body: { project_id: string; address: string; address_type?: string; physical_unit_id: string; reason?: string; decision_artifact_id?: string }) {
    return (await axios.post<StudioAddressBinding>(`${this.root}/address-bindings`, body)).data;
  }

  async captures() { return (await axios.get<StudioCaptureRecord[]>(`${this.root}/captures`)).data; }
  async createCapture(body: { capture_id: string; project_id: string; campaign_id: string; execution_id?: string }) {
    return (await axios.post<StudioCaptureRecord>(`${this.root}/captures`, body)).data;
  }
  async getCapture(captureId: string) { return (await axios.get<StudioCaptureRecord>(`${this.root}/captures/${encodeURIComponent(captureId)}`)).data; }

  async startEvidenceJob(captureId: string, body: { project_id: string; ble_channel: number; replay_run_id?: string }) {
    return (await axios.post<StudioJob>(`${this.root}/captures/${encodeURIComponent(captureId)}/evidence-jobs`, body)).data;
  }
  async examples(captureId: string) { return (await axios.get<StudioExample[]>(`${this.root}/captures/${encodeURIComponent(captureId)}/examples`)).data; }
  async job(jobId: string) { return (await axios.get<StudioJob>(`${this.root}/jobs/${encodeURIComponent(jobId)}`)).data; }

  async datasets() { return (await axios.get<StudioDatasetManifest[]>(`${this.root}/datasets`)).data; }
  async createDataset(body: { dataset_id: string; dataset_version: string; project_id: string; campaign_id: string; capture_ids: string[] }) {
    return (await axios.post<StudioDatasetBuildResult>(`${this.root}/datasets`, body)).data;
  }
  async buildQualityReport(datasetId: string, version: string, runNearDuplicates = false) {
    return (await axios.post<StudioQualityReport>(`${this.root}/datasets/${encodeURIComponent(datasetId)}/${encodeURIComponent(version)}/quality-report`, { run_near_duplicates: runNearDuplicates })).data;
  }
  async getQualityReport(datasetId: string, version: string) {
    return (await axios.get<StudioQualityReport>(`${this.root}/datasets/${encodeURIComponent(datasetId)}/${encodeURIComponent(version)}/quality-report`)).data;
  }

  async buildSplit(datasetId: string, version: string, scientificTask: string) {
    return (await axios.post<StudioSplitManifest>(`${this.root}/datasets/${encodeURIComponent(datasetId)}/${encodeURIComponent(version)}/splits/${encodeURIComponent(scientificTask)}`)).data;
  }
  async getSplit(datasetId: string, version: string, scientificTask: string) {
    return (await axios.get<StudioSplitManifest>(`${this.root}/datasets/${encodeURIComponent(datasetId)}/${encodeURIComponent(version)}/splits/${encodeURIComponent(scientificTask)}`)).data;
  }

  async startTraining(body: {
    training_run_id: string; project_id: string; campaign_id: string; dataset_id: string; dataset_version: string;
    dataset_manifest_sha256: string; split_manifest_sha256: string; scientific_task: string; model_type: string;
    representation_profile_id: string; base_preprocessing_profile_id?: string; random_seed?: number;
  }) {
    return (await axios.post<StudioJob>(`${this.root}/training-runs`, body)).data;
  }
  async trainingRuns() { return (await axios.get<StudioTrainingRun[]>(`${this.root}/training-runs`)).data; }
  async getTrainingRun(id: string) { return (await axios.get<StudioTrainingRun>(`${this.root}/training-runs/${encodeURIComponent(id)}`)).data; }

  async evaluate(trainingRunId: string, minIdentifiedPrecision = 0.9) {
    return (await axios.post<StudioEvaluationResult>(`${this.root}/training-runs/${encodeURIComponent(trainingRunId)}/evaluation`, { min_identified_precision: minIdentifiedPrecision })).data;
  }
  async getEvaluation(trainingRunId: string) {
    return (await axios.get<StudioEvaluationResult>(`${this.root}/training-runs/${encodeURIComponent(trainingRunId)}/evaluation`)).data;
  }

  async exportBundle(trainingRunId: string, body: { bundle_id: string; acceptance_criteria?: Record<string, number>; model_card_text?: string }) {
    return (await axios.post<StudioExportResult>(`${this.root}/training-runs/${encodeURIComponent(trainingRunId)}/export`, body)).data;
  }
  async bundles() { return (await axios.get<StudioBundleManifest[]>(`${this.root}/bundles`)).data; }
  async getBundle(id: string) { return (await axios.get<StudioBundleManifest>(`${this.root}/bundles/${encodeURIComponent(id)}`)).data; }
  async approveBundle(id: string) { return (await axios.post<StudioBundleManifest>(`${this.root}/bundles/${encodeURIComponent(id)}/approve`)).data; }

  async runInference(bundleId: string, captureId: string) {
    return (await axios.post<StudioInferenceDecision[]>(`${this.root}/bundles/${encodeURIComponent(bundleId)}/inference`, { capture_id: captureId })).data;
  }

  async scientificTasks() { return (await axios.get<Record<string, string>>(`${this.root}/scientific-tasks`)).data; }
  async feasibility(datasetId: string, version: string, scientificTask: string) {
    return (await axios.get<StudioFeasibility>(`${this.root}/datasets/${encodeURIComponent(datasetId)}/${encodeURIComponent(version)}/feasibility`, { params: { scientific_task: scientificTask } })).data;
  }
  async taskRecommendation(datasetId: string, version: string) {
    return (await axios.get<StudioTaskRecommendation>(`${this.root}/datasets/${encodeURIComponent(datasetId)}/${encodeURIComponent(version)}/task-recommendation`)).data;
  }
  async prepareAndTrain(body: {
    capture_ids: string[]; project_id: string; campaign_id: string; scientific_task: string;
    ble_channel?: number; dataset_id?: string; dataset_version?: string; speed_profile?: 'quick_pilot' | 'normal';
  }) {
    return (await axios.post<StudioJob>(`${this.root}/prepare-and-train`, body)).data;
  }
  async seedSyntheticDemo() { return (await axios.post<StudioSyntheticDemoSeed>(`${this.root}/synthetic-demo/seed`)).data; }

  async campaignDeviceStatus() { return (await axios.get<StudioCampaignDeviceStatus>(`${this.root}/campaign/device-status`)).data; }
  async startCampaignSession(body: {
    ble_channel?: number; duration_seconds?: number; gain_db?: number; condition_label: string;
    physical_unit_id?: string | null; project_id: string; campaign_id: string; session_index?: number; device_id?: string;
    isolation_declared?: boolean;
    /** "Que quieres capturar?" -- defaults to TARGET_DEVICE server-side.
     * BACKGROUND_ENVIRONMENT requires operator_confirmed_target_absent. */
    capture_purpose?: StudioCapturePurpose;
    operator_confirmed_target_absent?: boolean;
  }) {
    return (await axios.post<StudioJob>(`${this.root}/campaign/sessions`, body)).data;
  }
}

export interface StudioCampaignDeviceStatus {
  device_id: string;
  status: 'AVAILABLE' | 'ACQUIRED' | string;
  owner?: string | null;
  operation_id?: string | null;
  acquired_at?: string | null;
  lease_expires_at?: string | null;
}
export interface StudioCampaignSessionResult extends Record<string, unknown> {
  session_id: string;
  capture_id: string;
  replay_run_id: string;
  condition_label: string;
  physical_unit_id?: string | null;
  capture_purpose?: StudioCapturePurpose;
  target_state?: StudioTargetState;
  dataset_role?: StudioDatasetRole;
  evidence_summary?: Record<string, unknown>;
}

export interface StudioFeasibility {
  scientific_task: string;
  scientific_task_display: string;
  feasible: boolean;
  have: Record<string, number>;
  need: Record<string, number>;
  human_summary: string;
  /** Concrete "do this next" sentences (e.g. "Anade 2 sesion(es) mas del
   * dispositivo objetivo") -- empty once feasible is true. Never leave the
   * operator to infer an action from the have/need numbers alone. */
  next_steps: string[];
  /** 0..1, how close this task is to feasible -- used to rank candidates. */
  progress: number;
}
export interface StudioTaskRecommendation {
  recommended_task: string;
  recommended_task_display: string;
  reason: string;
  candidates: StudioFeasibility[];
}
export interface StudioSyntheticDemoSeed {
  project_id: string;
  campaign_id: string;
  capture_ids: string[];
  physical_unit_ids: string[];
}
export interface StudioPrepareAndTrainSummary {
  stopped_at: string | null;
  stopped_reason: string | null;
  dataset_id: string | null;
  dataset_version: string | null;
  data_origin: StudioDataOrigin | null;
  split_status: string | null;
  feasibility: StudioFeasibility | null;
  trained_models: { training_run_id: string; model_type: string; composite_score: number }[];
  skipped_models: { model_type: string; reason: string }[];
  recommended_training_run_id: string | null;
  recommended_reason: string | null;
  /** Evaluated exactly once, only for recommended_training_run_id, only
   * after model+hyperparameters+preprocessing+UNKNOWN threshold were frozen
   * via VALIDATION-only selection. Null when NO_MODEL_ACCEPTED or no model
   * was recommended -- TEST is never touched in that case either. */
  final_test_evaluation: Record<string, unknown> | null;
}

/** Never show a raw AxiosError to an operator: always resolve to a
 * plain-language sentence naming the endpoint and what happened. */
export function describeApiError(error: unknown): string {
  const withResponse = error as { response?: { status?: number; data?: { detail?: string } }; config?: { url?: string; method?: string }; message?: string };
  const status = withResponse?.response?.status;
  const url = withResponse?.config?.url;
  const detail = withResponse?.response?.data?.detail;
  if (status === 404) {
    return `No se pudo acceder al servicio BLE-RFFI Studio. Ruta solicitada: ${url ?? '(desconocida)'}. Codigo: 404.`;
  }
  if (status) {
    return `El servicio respondio con un error (codigo ${status}) en ${url ?? '(ruta desconocida)'}${detail ? `: ${detail}` : '.'}`;
  }
  if (withResponse?.message?.toLowerCase().includes('network')) {
    return 'No se pudo contactar con el backend de BLE-RFFI Studio. Verifica que el servidor este en ejecucion en el puerto 8000.';
  }
  return withResponse?.message || 'Ocurrio un error inesperado al comunicarse con el backend.';
}

/** A campaign session job's raw `error` string is an internal exception
 * chain (CampaignSessionError -> HYBRID_SESSION_FAILED -> RuntimeError ->
 * CAPTURE_FAILED, etc.) -- never show that chain verbatim to an operator.
 * Translates the known cases; falls back to the raw text (still better
 * than nothing) only for a case not yet mapped here. */
export function describeCampaignSessionError(rawError: string | undefined | null): string {
  const text = rawError || '';
  if (text.includes('CAPTURE_FAILED') || text.includes('CAPTURE_WORKER_FAILED')) {
    return 'La captura de radio fallo por una interrupcion real de la adquisicion (overflow o discontinuidad de muestras) -- el USRP B200 no pudo mantener el ritmo de escritura durante toda la ventana de captura. No es un error de software; es una variacion normal del hardware en este entorno (ocurre en una fraccion significativa de las capturas reales). Puedes simplemente reintentar.';
  }
  if (text.includes('B200_BUSY')) {
    return 'El USRP B200 esta siendo usado por otra operacion en este momento (otra captura o el monitor en vivo). Espera a que termine y reintenta.';
  }
  if (text.includes('HYBRID_SESSION_FAILED')) {
    return 'La sesion de captura (escaneo nativo + B200) no se completo correctamente. Revisa que el dispositivo SDR siga conectado y reintenta.';
  }
  if (text.includes('OFFLINE_REPLAY_DID_NOT_REACH_FULLY_PROCESSED')) {
    return 'El analisis de la captura no termino de procesarse dentro del limite de reintentos automaticos. La captura real fue exitosa, pero el analisis completo requiere mas tiempo del disponible.';
  }
  if (text.includes('OFFLINE_REPLAY_FAILED')) {
    return 'El analisis (decodificacion) de la captura fallo despues de una adquisicion exitosa. Puede requerir revisión tecnica.';
  }
  if (text.includes('REAL_CAMPAIGN_NOT_AVAILABLE')) {
    return 'El modulo de captura real (BLE Lab / B200) no esta activo en el backend en este momento.';
  }
  return text || 'La sesion fallo por una razon no reconocida.';
}

export interface NativeBleDevice extends Record<string, unknown> {
  address: string;
  local_name?: string | null;
  rssi_dbm?: number | null;
  last_seen_utc?: string | null;
}

/** Thin client for the existing native Windows BLE scan (a different
 * module, /api/ble/native/*) -- used only to detect which registered
 * physical units are broadcasting right now, so the operator never has to
 * guess or manually re-type a MAC address for a device already on. */
export class BleNativeScanApiService {
  constructor(private readonly baseURL = 'http://localhost:8000') {}
  private get root() { return `${this.baseURL}/api/ble/native`; }

  async start() { return (await axios.post<{ state: string; scan_session_id?: string }>(`${this.root}/scan/start`, {})).data; }
  async stop() { return (await axios.post<{ state: string }>(`${this.root}/scan/stop`)).data; }
  async devices() { return (await axios.get<{ devices: NativeBleDevice[] }>(`${this.root}/devices`)).data.devices; }
}

/** A device counts as "active now" if seen within this many seconds --
 * matches one native-scan detection cycle, not a stale historical entry
 * from a previous, unrelated capture session. */
export const NATIVE_DEVICE_FRESHNESS_SECONDS = 45;

export function isDeviceActiveNow(device: NativeBleDevice): boolean {
  if (!device.last_seen_utc) return false;
  const seenAt = new Date(device.last_seen_utc).getTime();
  if (Number.isNaN(seenAt)) return false;
  return (Date.now() - seenAt) / 1000 < NATIVE_DEVICE_FRESHNESS_SECONDS;
}
