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
export interface BleGate2a2ConfirmedPacket extends Record<string, unknown> { packet_sha256?: string; pdu_type_name?: string; channel_index?: number; crc_valid?: boolean; crc_computed?: number; crc_received?: number; address?: string|null; address_type?: string|null; payload_octets?: string; advertising_data_hex?: string|null; local_name?: string|null; power_dbfs?: number|null; snr_db?: number|null }
export interface BleSdrDevice { device_id: string; driver: string; label: string; serial_masked?: string | null; rx_channels: number; frequency_ranges_hz: { minimum: number; maximum: number }[]; sample_rate_ranges_sps: { minimum: number; maximum: number }[]; bandwidth_ranges_hz: { minimum: number; maximum: number }[]; gain_elements: string[]; antenna_options: string[]; stream_formats?: string[]; clock_sources?: string[]; time_sources?: string[]; available: boolean }
export interface BleCaptureCapabilities { available: boolean; capture_enabled: boolean; capture_and_decode_enabled: false; reason_code?: string; message?: string; devices: BleSdrDevice[]; default_duration_seconds: number; maximum_duration_seconds: number; supported_formats: string[]; ble_channels: Record<string, number> }
export interface BleCaptureJob { capture_id: string; state: 'queued'|'running'|'cancel_requested'|'completed'|'cancelled'|'failed'|'timed_out'; updated_at_utc?: string; error?: string; request?: Record<string, unknown>; capture_complete?: boolean }
export interface BleCaptureRecord extends Record<string, unknown> { capture_id: string; created_at_utc: string; device_driver: string; center_frequency_hz: number; ble_channel?: number; sample_rate_sps: number; bandwidth_hz: number; requested_duration_seconds: number; actual_size_bytes: number; overflow_count: number; capture_complete: boolean; analysis_status: string }
export interface BleCaptureLive { available: boolean; timestamp_utc?: string; samples_received?: number; bytes_written?: number; stream_overflows?: number; input_discontinuities?: number; average_power_dbfs?: number; peak_power_dbfs?: number; clipping_percentage?: number; frequencies_hz?: number[]; spectrum_dbfs?: number[]; i_preview?: number[]; q_preview?: number[] }
export interface BleNativeStatus { available: boolean; adapter_type: 'native_ble'; backend: string; scan_supported: boolean; gatt_supported: boolean; scanning: boolean; device_count: number; reason_code?: string; message?: string; diagnostic?: string }
export interface BleNativeMeasurement { measurement_id: string; device_id: string; measurement_type: string; value: number; unit: string; observed_at_utc: string; acquisition_mode: 'advertisement'|'gatt_read'|'gatt_notify'; source_uuid: string; source_raw_hex: string; parser_id: string; parser_version: string; conversion: { endianness: string; signed: boolean; scale: number; offset: number }; quality: { parsed: boolean; crc_available: boolean } }
export interface BleNativeCharacteristic { uuid: string; description?: string; properties: string[]; descriptors: { handle: number; uuid: string; description?: string }[] }
export interface BleNativeService { service_uuid: string; description?: string; known_name?: string|null; characteristics: BleNativeCharacteristic[] }
export interface BleGattDiagnostic { timestamp_utc: string; operation: string; attempt: number; duration_ms: number; cache_mode: string; status: string; exception_class?: string|null; exception_message?: string|null; winrt_code?: number|null; gatt_communication_status?: string|null; protocol_error?: number|null }
// TI CC2650 SensorTag -- environmental (AA20, humidity+temperature) and IR
// temperature (AA00) sensor sub-state. "available" is set only by the
// connected GATT fingerprint (phase 2); advertising alone never sets it.
export interface TiSensorReading { temperature_c?: number; relative_humidity_percent?: number; object_temperature_c?: number; ambient_temperature_c?: number; observed_at_utc: string; source_raw_hex: string; stale: boolean }
export interface TiSensorState { available: boolean; active: boolean; status?: 'available'|'unavailable'|'starting'|'starting_no_data_yet'|'active'|'disabled'|'disconnected'; data_uuid?: string; config_uuid?: string; period_uuid?: string; last_reading?: TiSensorReading | null }
export interface BleNativeDevice { device_id: string; address: string; address_type: string; local_name?: string|null; rssi_dbm?: number|null; tx_power_dbm?: number|null; manufacturer_data: Record<string,string>; service_data: Record<string,string>; service_uuids: string[]; first_seen_utc: string; last_seen_utc: string; observation_count: number; data_mode: 'ADVERTISEMENT_VALUE'|'GATT_READ'|'GATT_NOTIFY'|'UNKNOWN_FORMAT'; parser_available: boolean; connection: string; native_state?: string; native_status?: string; advertising_seen?: boolean; connection_attempted?: boolean; connection_established?: boolean; gatt_discovery_attempted?: boolean; gatt_discovery_succeeded?: boolean; profile_recognized?: boolean; measurement_available?: boolean; measurements: BleNativeMeasurement[]; gatt_services: BleNativeService[]; gatt_diagnostics?: BleGattDiagnostic[]; profile_id?: string|null; profile_label?: string|null; profile_detection_source?: 'gatt_fingerprint'|null; environmental_sensor?: TiSensorState; ir_temperature_sensor?: TiSensorState }

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
  async latestHybridPackets() { const sessions=(await axios.get<{sessions:{session_id:string}[]}>(`${this.baseURL}/api/ble/gate2a2/hybrid/sessions`)).data.sessions; if(!sessions.length)return []; return (await axios.get<{packets:BleGate2a2ConfirmedPacket[]}>(`${this.baseURL}/api/ble/gate2a2/hybrid/sessions/${encodeURIComponent(sessions[0].session_id)}/packets`)).data.packets; }
  async gate2a2Resource<T>(id: string, name: 'semantic-packets' | 'events' | 'rejections' | 'known-limitations' | 'result-summary') { return (await axios.get<T>(`${this.baseURL}/api/ble/gate2a2/jobs/${encodeURIComponent(id)}/${name}`)).data; }
  gate2a2BundleUrl(id: string) { return `${this.baseURL}/api/ble/gate2a2/jobs/${encodeURIComponent(id)}/bundle`; }

  async captureCapabilities() { return (await axios.get<BleCaptureCapabilities>(`${this.baseURL}/api/ble/capture/devices`)).data; }
  async createCapture(payload: Record<string, unknown>) { return (await axios.post<BleCaptureJob>(`${this.baseURL}/api/ble/capture/jobs`, payload)).data; }
  async captureJob(id: string) { return (await axios.get<BleCaptureJob>(`${this.baseURL}/api/ble/capture/jobs/${encodeURIComponent(id)}`)).data; }
  async cancelCapture(id: string) { return (await axios.post<BleCaptureJob>(`${this.baseURL}/api/ble/capture/jobs/${encodeURIComponent(id)}/cancel`)).data; }
  async captureLive(id: string) { return (await axios.get<BleCaptureLive>(`${this.baseURL}/api/ble/capture/jobs/${encodeURIComponent(id)}/live`)).data; }
  async captures() { return (await axios.get<{ captures: BleCaptureRecord[] }>(`${this.baseURL}/api/ble/capture/recordings`)).data.captures; }
  async verifyCapture(id: string) { return (await axios.get<{ data_valid: boolean; metadata_valid: boolean }>(`${this.baseURL}/api/ble/capture/recordings/${encodeURIComponent(id)}/verify`)).data; }
  async analyzeCapture(id: string) { return (await axios.post<BleGate2a2Job>(`${this.baseURL}/api/ble/capture/recordings/${encodeURIComponent(id)}/analyze`)).data; }
  captureMetaUrl(id: string) { return `${this.baseURL}/api/ble/capture/recordings/${encodeURIComponent(id)}/sigmf-meta`; }
  async nativeStatus() { return (await axios.get<BleNativeStatus>(`${this.baseURL}/api/ble/native/status`)).data; }
  async startNativeScan() { return (await axios.post(`${this.baseURL}/api/ble/native/scan/start`)).data; }
  async stopNativeScan() { return (await axios.post(`${this.baseURL}/api/ble/native/scan/stop`)).data; }
  async nativeDevices() { return (await axios.get<{devices:BleNativeDevice[]}>(`${this.baseURL}/api/ble/native/devices`)).data.devices; }
  async nativeDevice(id:string) { return (await axios.get<BleNativeDevice>(`${this.baseURL}/api/ble/native/devices/${encodeURIComponent(id)}`)).data; }
  async connectNative(id:string) { return (await axios.post<BleNativeDevice>(`${this.baseURL}/api/ble/native/devices/${encodeURIComponent(id)}/connect`)).data; }
  async disconnectNative(id:string) { return (await axios.post<BleNativeDevice>(`${this.baseURL}/api/ble/native/devices/${encodeURIComponent(id)}/disconnect`)).data; }
  async nativeServices(id:string) { return (await axios.get<{services:BleNativeService[]}>(`${this.baseURL}/api/ble/native/devices/${encodeURIComponent(id)}/services`)).data.services; }
  async nativeDiagnostics(id:string) { return (await axios.get<Record<string,unknown>>(`${this.baseURL}/api/ble/native/devices/${encodeURIComponent(id)}/gatt-diagnostics`)).data; }
  async readNative(id:string,uuid:string) { return (await axios.post(`${this.baseURL}/api/ble/native/devices/${encodeURIComponent(id)}/characteristics/${encodeURIComponent(uuid)}/read`)).data; }
  async subscribeNative(id:string,uuid:string) { return (await axios.post(`${this.baseURL}/api/ble/native/devices/${encodeURIComponent(id)}/characteristics/${encodeURIComponent(uuid)}/subscribe`)).data; }
  async unsubscribeNative(id:string,uuid:string) { return (await axios.post(`${this.baseURL}/api/ble/native/devices/${encodeURIComponent(id)}/characteristics/${encodeURIComponent(uuid)}/unsubscribe`)).data; }
  async startEnvironmental(id:string) { return (await axios.post<BleNativeDevice>(`${this.baseURL}/api/ble/native/devices/${encodeURIComponent(id)}/environmental/start`)).data; }
  async stopEnvironmental(id:string) { return (await axios.post<BleNativeDevice>(`${this.baseURL}/api/ble/native/devices/${encodeURIComponent(id)}/environmental/stop`)).data; }
  async startIrTemperature(id:string) { return (await axios.post<BleNativeDevice>(`${this.baseURL}/api/ble/native/devices/${encodeURIComponent(id)}/ir-temperature/start`)).data; }
  async stopIrTemperature(id:string) { return (await axios.post<BleNativeDevice>(`${this.baseURL}/api/ble/native/devices/${encodeURIComponent(id)}/ir-temperature/stop`)).data; }
}
