import axios from 'axios';

// Fase 1 (frozen protocol, chained holdout access log, paper runs,
// two-tier scientific preflight) + Fase 2 (canonical records, campaign
// accounting, descriptive quality summaries, figures). RQ1-4/S1-S2/power-
// simulation/LaTeX/export types and methods are added in later phases,
// once the backend endpoints behind them exist -- this file intentionally
// does not declare types for capabilities that are not implemented yet.

export type GitDirtyState = 'CLEAN' | 'DIRTY';

export interface AnalysisContract {
  schema_version: string;
  protocol_id: string;
  protocol_version: number;
  creation_timestamp_utc: string;
  git_commit: string;
  git_dirty_state: GitDirtyState;
  software_environment_digest: string;
  hardware_profile_id: string;
  receiver_profile_hash: string;
  device_population: Record<string, unknown>;
  device_ids: string[];
  firmware_hashes: Record<string, string>;
  channels: number[];
  campaign_schedule: Record<string, unknown>;
  intervention_schedule: Record<string, unknown>;
  content_variants: string[];
  association_policy_hash: string;
  quality_policy_hash: string;
  dataset_policy_hash: string;
  split_manifest_hash: string;
  model_branch_definitions: Record<string, unknown>[];
  feature_policy: Record<string, unknown>;
  signal_region_policy: Record<string, unknown>;
  phase_compensation_policy: Record<string, unknown>;
  hyperparameter_search_space: Record<string, unknown>;
  model_selection_rule: string;
  random_seeds: number[];
  number_of_restarts: number;
  threshold_selection_rule: string;
  abstention_rule: string;
  calibration_rule: string;
  multiplicity_family: Record<string, unknown>;
  statistical_tests: string[];
  effect_thresholds: Record<string, unknown>;
  non_inferiority_margins: Record<string, unknown>;
  minimum_independent_blocks: Record<string, unknown>;
  interpretation_matrix_hash: string;
}

export interface FreezeProtocolRequest {
  protocol_id?: string;
  project_id?: string;
  protocol_name?: string;
  hardware_profile_id: string;
  receiver_profile_hash: string;
  interpretation_matrix_hash: string;
  device_population?: Record<string, unknown>;
  device_ids?: string[];
  channels?: number[];
  split_manifest_hash?: string;
}

export interface HoldoutAccessLogEntry {
  sequence_number: number;
  previous_entry_hash: string | null;
  entry_hash: string;
  analysis_contract_hash: string | null;
  paper_run_id: string | null;
  actor: string;
  process: string;
  access_type: string;
  access_path: string;
  resource_id: string;
  resource_hash: string | null;
  timestamp_utc: string;
  reason: string;
}

export type HoldoutChainStatus = 'VALID' | 'BROKEN' | 'EMPTY';
export interface HoldoutChainVerificationResult {
  status: HoldoutChainStatus;
  entry_count: number;
  broken_at_sequence: number | null;
  findings: string[];
}

export interface PaperRunRecord {
  paper_run_id: string;
  campaign_id: string;
  protocol_id: string;
  protocol_version: number;
  dataset_id: string;
  dataset_version: string;
  scientific_task: string;
  dataset_fingerprint: string | null;
  split_fingerprint: string | null;
  model_set_fingerprint: string | null;
  analysis_code_commit: string;
  analysis_environment_hash: string;
  storage_path: string;
  created_at: string;
}

export interface CreateRunRequest {
  protocol_id: string;
  protocol_version?: number;
  campaign_id: string;
  dataset_id: string;
  dataset_version: string;
  scientific_task: string;
}

export type PreflightCategoryStatus = 'PASSED' | 'BLOCKED';
export interface PreflightCategoryResult {
  status: PreflightCategoryStatus;
  findings: string[];
  [key: string]: unknown;
}

// Two-tier: a dataset can be internally coherent without the whole PAPER
// campaign satisfying everything the frozen protocol declares -- never a
// single generic "passed" step. DATASET_STRUCTURAL_PREFLIGHT_PASSED must
// never be presented as "ready for the paper".
export type PreflightStatus = 'DATASET_STRUCTURAL_PREFLIGHT_PASSED' | 'PAPER_CAMPAIGN_PREFLIGHT_PASSED' | 'PREFLIGHT_BLOCKED';

export interface ScientificPreflightReport {
  paper_run_id: string;
  protocol_id: string;
  protocol_version: number;
  generated_at: string;
  integrity: PreflightCategoryResult;
  leakage: PreflightCategoryResult;
  population_separation: PreflightCategoryResult & { population_counts: Record<string, number> };
  quality: PreflightCategoryResult;
  design_completeness: PreflightCategoryResult;
  paper_campaign_completeness: PreflightCategoryResult & { checked_requirements: string[] };
  overall_status: PreflightStatus;
}

export interface ReadinessResponse {
  paper_run_id: string;
  overall_status: PreflightStatus | null;
  message?: string;
  [key: string]: unknown;
}

export interface ScientificResultsJob {
  job_id: string;
  job_type: string;
  paper_run_id: string;
  state: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  stage: string | null;
  overall_progress: number;
  message: string | null;
  overall_status?: PreflightStatus;
  error?: string;
  started_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------------
// Fase 2: canonical records, campaign accounting, quality, figures
// ---------------------------------------------------------------------

export interface RecordBuildResult {
  paper_run_id: string;
  generated_at: string;
  capture_record_count: number;
  burst_record_count: number;
  decision_window_record_count: number;
  campaign_deviation_count: number;
  captures_without_replay: string[];
}

export interface RecordsStatusResponse {
  paper_run_id: string;
  built: boolean;
  [key: string]: unknown;
}

export type BurstClass = 'RF_ACTIVITY' | 'BLE_SYNC_CANDIDATE' | 'CRC_VALID_PACKET' | 'TARGET_ASSOCIATED_PACKET';

export interface ScientificCaptureRecord extends Record<string, unknown> {
  capture_id: string;
  physical_unit_id: string | null;
  channel: number | null;
  capture_quality: string | null;
  label_status: string | null;
  experimental_role: string | null;
  split: string | null;
  eligible: boolean | null;
  exclusion_reason_codes: string[];
  not_documented_fields: string[];
}

export interface ScientificBurstRecord extends Record<string, unknown> {
  burst_id: string;
  capture_id: string;
  burst_class: BurstClass;
  decision_window_id: string;
  crc_status: string | null;
  association_status: string | null;
  eligible: boolean | null;
  exclusion_reason_codes: string[];
  not_documented_fields: string[];
}

export interface ScientificDecisionWindowRecord extends Record<string, unknown> {
  decision_window_id: string;
  capture_id: string;
  active: boolean;
  eligible_burst_count: number;
  decision_eligible: boolean;
  ineligibility_reason_codes: string[];
}

export interface ScientificCampaignDeviationRecord extends Record<string, unknown> {
  deviation_id: string;
  affected_object_type: string;
  affected_object_id: string;
  deviation_type: string;
  description: string;
  severity: string;
  blocking: boolean;
  action: string;
  scientific_impact: string;
  source_artifact_ids: string[];
}

export interface CampaignAccountingResponse {
  counters: Record<string, number | boolean>;
  balance: Record<string, Record<string, Record<string, number>>>;
  exclusion_reason_row_count: number;
  missingness_row_count: number;
}

export interface QualitySummaryResponse {
  capture_field_summary: Record<string, unknown>[];
  window_field_summary: Record<string, unknown>[];
  unit_day_summary: Record<string, unknown>[];
  association_summary: Record<string, unknown>[];
}

export interface RunArtifactsResponse {
  paper_run_id: string;
  files: string[];
}

// ---------------------------------------------------------------------
// Guided BLE Scientific Validation -- one orchestrator job spanning every
// enrolled device's existing dataset. Mirrors guided_validation/contracts.py
// exactly; the frontend never computes any of these numbers itself.
// ---------------------------------------------------------------------

export type GuidedValidationStageStatus =
  | 'NOT_STARTED' | 'RUNNING' | 'PASSED' | 'PARTIALLY_SUPPORTED' | 'BLOCKED' | 'REQUIRES_PHYSICAL_ACTION' | 'COMPLETED';

export interface GuidedValidationStage {
  stage_id: string;
  label: string;
  status: GuidedValidationStageStatus;
  plain_explanation: string;
  technical_details: Record<string, unknown>;
  evidence_artifacts: string[];
  next_action: string | null;
}

export interface CapabilityFlag {
  capability: string;
  supported: boolean;
  plain_explanation: string;
}

export interface GuidedValidationSummary {
  run_id: string;
  generated_at: string;
  overall_status: string;
  stages: GuidedValidationStage[];
  capability_flags: CapabilityFlag[];
  device_summary: Record<string, {
    capture_count: number;
    calibration_eligible_or_better_captures: number;
    native_event_count: number;
    crc_valid_packet_count: number;
    strong_association_count: number;
    active_windows: number;
    eligible_windows: number;
  }>;
  capture_totals: {
    total_captures: number;
    association_calibration_eligible: number;
    qualification_pilot_eligible: number;
    diagnostic_only: number;
  };
  association_summary: {
    total_calibration_events: number;
    by_status: Record<string, number>;
    by_status_percent: Record<string, number>;
    matched_target_count: number;
  };
  target_absence_summary: {
    candidates_checked: number;
    valid_reinforced_controls: Record<string, unknown>[];
    has_valid_control: boolean;
    invalid_reasons_by_capture: Record<string, string>;
  };
  association_policy_summary: Record<string, unknown> | null;
  simplified_conclusion: string;
  next_required_action: string;
  artifact_index: Record<string, unknown>;
}

export interface GuidedValidationJob {
  job_id: string;
  job_type: string;
  state: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  stage: string | null;
  overall_progress: number;
  message: string | null;
  error?: string;
  result?: GuidedValidationSummary;
  started_at: string;
  updated_at: string;
}

export interface TimingDiagnosticResult {
  action_id: string;
  physical_unit_id: string;
  capture_id: string;
  session_id: string;
  native_scanner_running_time_s: number;
  native_event_count: number;
  target_native_event_count: number;
  sdr_candidate_count: number;
  crc_valid_packet_count: number;
  target_address_packet_count: number;
  candidate_pair_count: number;
  narrow_window_valid_count: number;
  narrow_window_ambiguous_count: number;
  best_residual_ms_median: number | null;
  best_residual_ms_p95: number | null;
  diagnosis_code: string;
  diagnosis_explanation: string;
  diagnosis_next_action: string;
}

export interface TargetAbsenceControlResult {
  action_id: string;
  status: string;
  capture_id: string;
  session_id: string;
  native_event_count: number;
  devices_detected: string[];
  false_strong_associations_by_threshold_ms: Record<string, number>;
  false_strong_associations_total: number;
}

export interface GuidedValidationActionJob {
  job_id: string;
  job_type: string;
  state: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  stage: string | null;
  overall_progress: number;
  message: string | null;
  error?: string;
  result?: TimingDiagnosticResult | TargetAbsenceControlResult;
  started_at: string;
  updated_at: string;
}

export interface CapturableDevice {
  physical_unit_id: string;
  has_bound_address: boolean;
  has_dataset: boolean;
  existing_capture_count: number;
}

export interface NewCaptureSessionResponse {
  run_id: string;
}

export interface CleanupRunEntry {
  run_id: string;
  kind: 'FULL_RUN' | 'CAPTURE_ONLY' | 'UNKNOWN';
  generated_at: string | null;
  overall_status: string | null;
  paper_run_count: number;
  size_bytes: number;
}

export interface DeleteCleanupRunResponse {
  deleted: boolean;
  run_id: string;
  deleted_paper_runs: string[];
}

export interface StartTimingDiagnosticRequest {
  physical_unit_id: string;
  capture_duration_s: number;
  channel: number;
  receiver_profile?: string;
  operator_id?: string;
}

export interface StartTargetAbsenceControlRequest {
  confirmed_devices_off: Record<string, boolean>;
  capture_duration_s: number;
  channel: number;
  operator_id?: string;
}

// Paper progress dashboard (2026-08-10) -- pure reporting types. Every
// shape below mirrors a real backend dict exactly (get_study_status,
// get_paper_readiness, paper_export.py's manifest); `NoDataResponse` is
// what every "no real artifact yet" endpoint returns instead of an empty
// object or a zeroed one.

export interface NoDataResponse {
  status: 'NO_DATA';
}

export interface StudyStatusResponse {
  git_sha: string;
  git_dirty_state: GitDirtyState;
  protocol_id: string | null;
  all_protocol_ids: string[];
  protocol_version: number | null;
  contract_status: 'NO_DATA' | 'INCOMPLETE' | 'COMPLETE' | 'FROZEN';
  contract_sha256: string | null;
  missing_confirmatory_readiness_fields: string[];
  association_policy_status: 'NONE' | 'FROZEN';
  protected_future_test_status: 'UNTOUCHED' | 'OPENED';
  protocol_freeze_status: 'NOT_STARTED' | 'COMPLETE';
  real_capture_count: number;
  current_phase: string;
  generated_at: string;
}

export interface PaperReadinessRow {
  paper_element: string;
  status: 'DATA_PENDING' | 'PRELIMINARY' | 'COMPLETE';
  required_artifact: string;
  available: boolean;
  confirmatory: boolean;
  table_ready: boolean;
  figure_ready: boolean;
  text_ready: boolean;
}

export interface ProtocolFreezeStatusResponse {
  status: 'NOT_STARTED' | 'COMPLETE';
  entries: { protocol_id: string; protocol_version: number; contract_sha256: string; frozen_at: string; new_version_reason: string | null; is_new_version_of: number | null }[];
}

export interface AssociationPolicyStatusResponse {
  status: 'NONE' | 'FROZEN';
  policy?: Record<string, unknown>;
}

export interface PaperExportManifestEntry {
  file: string;
  status: 'GENERATED' | 'SKIPPED_NO_DATA';
  detail?: string;
  would_be_derived_from?: string;
}

export interface PaperExportManifest {
  schema_version: string;
  generated_at: string;
  generated_count: number;
  skipped_count: number;
  entries: PaperExportManifestEntry[];
}

export class BleScientificResultsApiService {
  constructor(private readonly baseURL = 'http://localhost:8000') {}
  private get root() { return `${this.baseURL}/api/ble-scientific-results`; }

  async freezeProtocol(body: FreezeProtocolRequest) { return (await axios.post<AnalysisContract>(`${this.root}/protocols`, body)).data; }
  async getProtocol(protocolId: string, version?: number) {
    return (await axios.get<AnalysisContract>(`${this.root}/protocols/${encodeURIComponent(protocolId)}`, { params: version ? { version } : {} })).data;
  }
  async listProtocolVersions(protocolId: string) {
    return (await axios.get<AnalysisContract[]>(`${this.root}/protocols/${encodeURIComponent(protocolId)}/versions`)).data;
  }

  async holdoutAccessLog() { return (await axios.get<HoldoutAccessLogEntry[]>(`${this.root}/holdout-access-log`)).data; }
  async verifyHoldoutAccessChain() { return (await axios.get<HoldoutChainVerificationResult>(`${this.root}/holdout-access-log/verify`)).data; }

  async createRun(body: CreateRunRequest) { return (await axios.post<PaperRunRecord>(`${this.root}/runs`, body)).data; }
  async listRuns() { return (await axios.get<PaperRunRecord[]>(`${this.root}/runs`)).data; }
  async getRun(paperRunId: string) { return (await axios.get<PaperRunRecord>(`${this.root}/runs/${encodeURIComponent(paperRunId)}`)).data; }

  async startPreflight(paperRunId: string) { return (await axios.post<ScientificResultsJob>(`${this.root}/preflight`, { paper_run_id: paperRunId })).data; }
  async getJob(jobId: string) { return (await axios.get<ScientificResultsJob>(`${this.root}/jobs/${encodeURIComponent(jobId)}`)).data; }
  async cancelJob(jobId: string) { return (await axios.post<ScientificResultsJob>(`${this.root}/jobs/${encodeURIComponent(jobId)}/cancel`)).data; }
  async readiness(paperRunId: string) { return (await axios.get<ReadinessResponse>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/readiness`)).data; }

  async startBuildRecords(paperRunId: string) { return (await axios.post<ScientificResultsJob>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/build-records`)).data; }
  async recordsStatus(paperRunId: string) { return (await axios.get<RecordsStatusResponse>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/records/status`)).data; }
  async campaignAccounting(paperRunId: string) { return (await axios.get<CampaignAccountingResponse>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/campaign-accounting`)).data; }
  async deviations(paperRunId: string, limit = 200, offset = 0) {
    return (await axios.get<ScientificCampaignDeviationRecord[]>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/deviations`, { params: { limit, offset } })).data;
  }
  async qualitySummary(paperRunId: string) { return (await axios.get<QualitySummaryResponse>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/quality-summary`)).data; }
  async captures(paperRunId: string, limit = 100, offset = 0) {
    return (await axios.get<ScientificCaptureRecord[]>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/captures`, { params: { limit, offset } })).data;
  }
  async captureDetail(paperRunId: string, captureId: string) {
    return (await axios.get<ScientificCaptureRecord>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/captures/${encodeURIComponent(captureId)}`)).data;
  }
  async bursts(paperRunId: string, limit = 100, offset = 0, captureId?: string) {
    return (await axios.get<ScientificBurstRecord[]>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/bursts`, { params: { limit, offset, capture_id: captureId } })).data;
  }
  async windows(paperRunId: string, limit = 100, offset = 0, captureId?: string) {
    return (await axios.get<ScientificDecisionWindowRecord[]>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/windows`, { params: { limit, offset, capture_id: captureId } })).data;
  }
  async artifacts(paperRunId: string) { return (await axios.get<RunArtifactsResponse>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/artifacts`)).data; }

  async startGuidedValidation() { return (await axios.post<GuidedValidationJob>(`${this.root}/guided-validation`)).data; }
  async getGuidedValidationJob(jobId: string) { return (await axios.get<GuidedValidationJob>(`${this.root}/guided-validation/${encodeURIComponent(jobId)}`)).data; }

  async listCapturableDevices() { return (await axios.get<CapturableDevice[]>(`${this.root}/guided-validation/capturable-devices`)).data; }
  async newCaptureSession() { return (await axios.post<NewCaptureSessionResponse>(`${this.root}/guided-validation/new-capture-session`)).data; }

  async listCleanupRuns() { return (await axios.get<CleanupRunEntry[]>(`${this.root}/guided-validation/cleanup/runs`)).data; }
  async deleteCleanupRun(runId: string) {
    return (await axios.delete<DeleteCleanupRunResponse>(`${this.root}/guided-validation/cleanup/runs/${encodeURIComponent(runId)}`)).data;
  }

  async startTimingDiagnostic(runId: string, body: StartTimingDiagnosticRequest) {
    return (await axios.post<GuidedValidationActionJob>(`${this.root}/guided-validation/${encodeURIComponent(runId)}/timing-diagnostic`, body)).data;
  }
  async startTargetAbsenceControl(runId: string, body: StartTargetAbsenceControlRequest) {
    return (await axios.post<GuidedValidationActionJob>(`${this.root}/guided-validation/${encodeURIComponent(runId)}/target-absence-control`, body)).data;
  }
  async getGuidedValidationAction(runId: string, actionJobId: string) {
    return (await axios.get<GuidedValidationActionJob>(`${this.root}/guided-validation/${encodeURIComponent(runId)}/actions/${encodeURIComponent(actionJobId)}`)).data;
  }

  // Paper progress dashboard (2026-08-10) -- read-only. `runPaperExport()`
  // is the one method here that writes files server-side; it never mutates
  // the protocol/science, only generates the export manifest.
  async studyStatus(protocolId?: string) {
    return (await axios.get<StudyStatusResponse>(`${this.root}/study-status`, { params: protocolId ? { protocol_id: protocolId } : {} })).data;
  }
  async paperReadiness() { return (await axios.get<PaperReadinessRow[]>(`${this.root}/paper-readiness`)).data; }
  async campaignQualificationPreflightLatest() {
    return (await axios.get<Record<string, unknown> | NoDataResponse>(`${this.root}/campaign-qualification-preflight/latest`)).data;
  }
  async associationPolicyStatus() { return (await axios.get<AssociationPolicyStatusResponse>(`${this.root}/association-policy-status`)).data; }
  async protocolFreezeStatus(protocolId?: string) {
    return (await axios.get<ProtocolFreezeStatusResponse>(`${this.root}/protocol-freeze-status`, { params: protocolId ? { protocol_id: protocolId } : {} })).data;
  }
  async confirmatoryStatisticalPlan(paperRunId: string) {
    return (await axios.get<Record<string, unknown> | NoDataResponse>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/confirmatory-statistical-plan`)).data;
  }
  async confirmatoryFutureAnalysis(paperRunId: string) {
    return (await axios.get<Record<string, unknown> | NoDataResponse>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/confirmatory-future-analysis`)).data;
  }
  async rq1AcquisitionDependence(paperRunId: string) {
    return (await axios.get<Record<string, unknown> | NoDataResponse>(`${this.root}/runs/${encodeURIComponent(paperRunId)}/rq1-acquisition-dependence`)).data;
  }
  async runPaperExport() { return (await axios.post<PaperExportManifest>(`${this.root}/paper-exports`)).data; }
  async getPaperExportManifest() { return (await axios.get<PaperExportManifest | NoDataResponse>(`${this.root}/paper-exports`)).data; }
}
