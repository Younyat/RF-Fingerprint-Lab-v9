import axios from 'axios';

export type BleJobState = 'created' | 'queued' | 'validating_input' | 'starting_worker' | 'running' | 'validating_artifacts' | 'completed' | 'completed_with_diagnostics' | 'cancel_requested' | 'cancelled' | 'failed' | 'timed_out';
export interface BleCapabilities { enabled: boolean; capability_status: string; scientific_status: string; normative_conformance: string; worker_commit: string; gates: Record<string, string | boolean>; available_input_modes: string[]; unavailable_input_modes: string[] }
export interface BleJob { job_id: string; state: BleJobState; input_mode?: string; processing_duration_seconds?: number; result_summary?: Record<string, unknown>; worker?: Record<string, unknown>; error?: { code?: string; message?: string } | null }
export interface BlePacket extends Record<string, unknown> { packet_id?: string; pdu_type?: string; channel_index?: number; crc_valid?: boolean }
export interface BleAdvertisement extends Record<string, unknown> { packet_id?: string; pdu_type?: string; advertiser_address?: string; ad_structures?: unknown[] }
export interface BleAdvertiser extends Record<string, unknown> { address?: string; address_type?: string; packet_count?: number }
export interface BleJobEvent extends Record<string, unknown> { sequence?: number; timestamp_utc?: string; previous_state?: string; new_state?: string; reason?: string }

// Gate 2A.2 -- separate, experimental, NOT the frozen Gate 1B replay pipeline above.
export interface BleGate2a2Status extends Record<string, unknown> {
  available: boolean;
  reason?: string;
  gate?: string;
  gate_2a1_status?: string;
  gate_2a2_status?: string;
  dsp_gate?: string;
  receiver_candidate?: string;
  candidate_frozen?: boolean;
  development_timing_sweep?: { cases?: number; byte_exact?: number; result?: string; holdout_eligible?: boolean };
  residual_failures?: number;
  holdout_b_created?: boolean;
  iq_recovery_validated?: boolean;
  ota_validated?: boolean;
  worker_repository_commit?: string;
  receiver_commit?: string;
  frozen_bitstream_commit?: string;
  disabled_reason?: string;
}
export type BleGate2a2JobState = 'created' | 'queued' | 'starting_worker' | 'running' | 'cancel_requested' | 'completed' | 'cancelled' | 'failed' | 'timed_out';
export interface BleGate2a2Job { job_id: string; state: BleGate2a2JobState; request?: Record<string, unknown>; error?: string | null; updated_at_utc?: string }
export interface BleGate2a2Candidate extends Record<string, unknown> { receiver_trace_id?: number | string; channel_index?: number; estimated_cfo_hz?: number; estimated_timing_phase?: number; winning_timing_hypothesis_id?: string; timing_hypotheses_evaluated?: number; merged_timing_hypothesis_ids?: string[]; detector_score?: number }
export interface BleGate2a2ConfirmedPacket extends Record<string, unknown> { packet_sha256?: string; pdu_type_name?: string; channel_index?: number; crc_valid?: boolean; crc_computed?: number; crc_received?: number }

const unwrap = <T>(data: T | Record<string, T>): T => {
  if (data && typeof data === 'object' && !Array.isArray(data)) {
    const wrapped = data as Record<string, T>;
    return wrapped.items ?? wrapped.packets ?? wrapped.advertisements ?? wrapped.advertisers ?? wrapped.events ?? data as T;
  }
  return data as T;
};

export class BleApiService {
  constructor(private readonly baseURL = 'http://localhost:8000') {}
  async capabilities() { return (await axios.get<BleCapabilities>(`${this.baseURL}/api/ble/capabilities`)).data; }
  async createReplayJob() { return (await axios.post<BleJob>(`${this.baseURL}/api/ble/jobs`, { contract_version: 'ble-job-v1', profile: 'ble_le1m_primary_advertising', input_mode: 'validated_bitstream_replay', source: { type: 'gate1b_fixture', fixture_id: 'gate1b-campaign-001', source_commit: '7b685f7fb0d161be6577d862711456532dcb3528' }, passive_only: true, expected_worker_commit: '7b685f7fb0d161be6577d862711456532dcb3528' })).data; }
  async job(id: string) { return (await axios.get<BleJob>(`${this.baseURL}/api/ble/jobs/${encodeURIComponent(id)}`)).data; }
  async cancel(id: string) { return (await axios.post<BleJob>(`${this.baseURL}/api/ble/jobs/${encodeURIComponent(id)}/cancel`)).data; }
  async retry(id: string) { return (await axios.post<BleJob>(`${this.baseURL}/api/ble/jobs/${encodeURIComponent(id)}/retry`)).data; }
  async packets(id: string) { return unwrap((await axios.get<BlePacket[]>(`${this.baseURL}/api/ble/jobs/${encodeURIComponent(id)}/packets`)).data); }
  async advertisements(id: string) { return unwrap((await axios.get<BleAdvertisement[]>(`${this.baseURL}/api/ble/jobs/${encodeURIComponent(id)}/advertisements`)).data); }
  async advertisers(id: string) { return unwrap((await axios.get<BleAdvertiser[]>(`${this.baseURL}/api/ble/jobs/${encodeURIComponent(id)}/advertisers`)).data); }
  async resource<T>(id: string, name: 'channels' | 'diagnostics' | 'events' | 'artifacts') { return unwrap((await axios.get<T>(`${this.baseURL}/api/ble/jobs/${encodeURIComponent(id)}/${name}`)).data); }
  bundleUrl(id: string) { return `${this.baseURL}/api/ble/jobs/${encodeURIComponent(id)}/bundle`; }

  // Gate 2A.2 -- experimental offline IQ analysis, entirely separate from Gate 1B above.
  async gate2a2Status() { return (await axios.get<BleGate2a2Status>(`${this.baseURL}/api/ble/gate2a2/status`)).data; }
  async createGate2a2Job(payload: { iq_file_path: string; channel_index: number; dc_removal?: boolean; channel_filter?: boolean; cfo_correction?: boolean; timing_recovery?: boolean }) {
    return (await axios.post<BleGate2a2Job>(`${this.baseURL}/api/ble/gate2a2/jobs`, payload)).data;
  }
  async gate2a2Job(id: string) { return (await axios.get<BleGate2a2Job>(`${this.baseURL}/api/ble/gate2a2/jobs/${encodeURIComponent(id)}`)).data; }
  async cancelGate2a2Job(id: string) { return (await axios.post<BleGate2a2Job>(`${this.baseURL}/api/ble/gate2a2/jobs/${encodeURIComponent(id)}/cancel`)).data; }
  async gate2a2Candidates(id: string) { const data = (await axios.get<Record<string, BleGate2a2Candidate[]>>(`${this.baseURL}/api/ble/gate2a2/jobs/${encodeURIComponent(id)}/candidates`)).data; return data.candidates ?? []; }
  async gate2a2ConfirmedPackets(id: string) { const data = (await axios.get<Record<string, BleGate2a2ConfirmedPacket[]>>(`${this.baseURL}/api/ble/gate2a2/jobs/${encodeURIComponent(id)}/confirmed-packets`)).data; return data['confirmed-packets'] ?? []; }
  async gate2a2Resource<T>(id: string, name: 'semantic-packets' | 'events' | 'rejections' | 'known-limitations' | 'result-summary') { return (await axios.get<T>(`${this.baseURL}/api/ble/gate2a2/jobs/${encodeURIComponent(id)}/${name}`)).data; }
  gate2a2BundleUrl(id: string) { return `${this.baseURL}/api/ble/gate2a2/jobs/${encodeURIComponent(id)}/bundle`; }
}
