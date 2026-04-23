import axios from 'axios';
import {
  SpectrumData,
  WaterfallData,
  Marker,
  DeviceStatus,
  AnalyzerSettings,
  Recording,
  Session,
  Preset,
  DemodulationResult,
  ModulatedSignalCapture,
} from '../../shared/types';
import { API_ENDPOINTS } from '../../shared/constants';

const toDeviceStatus = (data: any): DeviceStatus => ({
  isConnected: Boolean(data.isConnected ?? data.is_connected ?? data.is_streaming ?? data.status === 'streaming'),
  driver: data.driver ?? 'uhd_gnuradio',
  centerFrequency: data.centerFrequency ?? data.center_frequency_hz ?? data.frequency_hz ?? 0,
  sampleRate: data.sampleRate ?? data.sample_rate_hz ?? 0,
  gain: data.gain ?? data.gain_db ?? 0,
  antenna: data.antenna,
  lastError: data.lastError ?? data.last_error ?? null,
});

const toSpectrumData = (data: any): SpectrumData => ({
  timestamp: data.timestamp ?? (data.timestamp_utc ? Date.parse(data.timestamp_utc) : Date.now()),
  centerFrequency: data.centerFrequency ?? data.center_frequency_hz ?? 0,
  span: data.span ?? data.span_hz ?? 0,
  frequencyArray: data.source === 'real_sdr_error' ? [] : (data.frequencyArray ?? data.frequencies_hz ?? []),
  powerLevels: data.source === 'real_sdr_error' ? [] : (data.powerLevels ?? data.levels_db ?? []),
});

const toWaterfallData = (data: any): WaterfallData => {
  const levels = data.source === 'real_sdr_error' ? [] : (data.levels_db ?? data.powerLevels ?? []);
  const rows = data.data && data.data.length > 0 ? data.data : (levels.length > 0 ? [levels] : []);

  return {
    timestamp: data.timestamp ?? (data.timestamp_utc ? Date.parse(data.timestamp_utc) : Date.now()),
    centerFrequency: data.centerFrequency ?? data.center_frequency_hz ?? 0,
    span: data.span ?? data.span_hz ?? 0,
    data: rows,
  };
};

const toMarker = (data: any): Marker => ({
  id: data.id ?? data.marker_id ?? '',
  label: data.label ?? 'Marker',
  frequency: data.frequency ?? data.frequency_hz ?? 0,
  level: data.level ?? data.level_db ?? 0,
  type: data.type ?? data.marker_type ?? 'normal',
  enabled: data.enabled ?? true,
});

const toRecording = (data: any): Recording => ({
  id: data.id ?? data.recording_id ?? data.capture_id ?? '',
  sessionId: data.sessionId ?? data.session_id ?? '',
  timestamp: data.timestamp ?? (data.timestamp_utc ? Date.parse(data.timestamp_utc) : Date.now()),
  duration: data.duration ?? data.duration_seconds ?? 0,
  filePath: data.filePath ?? data.file_path ?? data.filename ?? '',
  size: data.size ?? data.file_size_bytes ?? 0,
  type: data.type ?? data.format ?? 'iq',
});

const toSession = (data: any): Session => ({
  id: data.id ?? data.session_id ?? '',
  name: data.name ?? 'Session',
  createdAt: data.createdAt ?? (data.created_utc ? Date.parse(data.created_utc) : Date.now()),
  recordings: data.recordings ?? [],
  notes: data.notes ?? data.description,
});

const toPreset = (data: any): Preset => ({
  id: data.id ?? data.preset_id ?? '',
  name: data.name ?? 'Preset',
  settings: data.settings ?? data.config ?? {
    centerFrequency: 100000000,
    span: 2000000,
    rbw: 10000,
    vbw: 3000,
    referenceLevel: 10,
    noiseFloorOffset: 0,
    detectorMode: 'sample',
    traceMode: 'clear_write',
    dbPerDiv: 10,
    colorScheme: 'blue',
    averaging: 1,
    smoothing: 0,
  },
  createdAt: data.createdAt ?? Date.now(),
});

export class ApiService {
  private baseURL = 'http://localhost:8000';

  constructor(baseURL?: string) {
    if (baseURL) {
      this.baseURL = baseURL;
    }
  }

  // Device endpoints
  async getDeviceStatus(): Promise<DeviceStatus> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.DEVICE_STATUS}`);
    return toDeviceStatus(response.data);
  }

  async connectDevice(): Promise<DeviceStatus> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.DEVICE_CONNECT}`);
    return toDeviceStatus(response.data);
  }

  async disconnectDevice(): Promise<DeviceStatus> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.DEVICE_DISCONNECT}`);
    return toDeviceStatus(response.data);
  }

  async openWfmReceiver(): Promise<DeviceStatus> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.DEVICE_OPEN_RECEIVER}`);
    return toDeviceStatus(response.data);
  }

  async closeWfmReceiver(): Promise<DeviceStatus> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.DEVICE_CLOSE_RECEIVER}`);
    return toDeviceStatus(response.data);
  }

  async startDeviceStream(): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.DEVICE_START_STREAM}`);
  }

  async stopDeviceStream(): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.DEVICE_STOP_STREAM}`);
  }

  async setDeviceFrequency(frequency: number): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.DEVICE_SET_FREQUENCY}`, { frequency_hz: frequency });
  }

  async setDeviceGain(gain: number): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.DEVICE_SET_GAIN}`, { gain_db: gain });
  }

  async setDeviceSampleRate(sampleRate: number): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.DEVICE_SET_SAMPLE_RATE}`, { sample_rate_hz: sampleRate });
  }

  // Spectrum endpoints
  async getLiveSpectrum(): Promise<SpectrumData> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.SPECTRUM_LIVE}`);
    return toSpectrumData(response.data);
  }

  async setSpectrumCenterFrequency(frequency: number): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.SPECTRUM_SET_CENTER}`, { center_frequency_hz: frequency });
  }

  async setSpectrumSpan(span: number): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.SPECTRUM_SET_SPAN}`, { span_hz: span });
  }

  async setSpectrumStartStop(startFrequency: number, stopFrequency: number): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.SPECTRUM_SET_START_STOP}`, {
      start_frequency_hz: startFrequency,
      stop_frequency_hz: stopFrequency,
    });
  }

  async setSpectrumRbw(rbw: number): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.SPECTRUM_SET_RBW}`, { rbw_hz: rbw });
  }

  async setSpectrumVbw(vbw: number): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.SPECTRUM_SET_VBW}`, { vbw_hz: vbw });
  }

  async setSpectrumReferenceLevel(level: number): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.SPECTRUM_SET_REFERENCE_LEVEL}`, { reference_level_db: level });
  }

  async setSpectrumNoiseFloorOffset(offset: number): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.SPECTRUM_SET_NOISE_FLOOR}`, { offset_db: offset });
  }

  async setSpectrumDetectorMode(mode: string): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.SPECTRUM_SET_DETECTOR}`, { mode });
  }

  async setSpectrumAveraging(count: number): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.SPECTRUM_SET_AVERAGING}`, { count });
  }

  // Waterfall endpoints
  async getLiveWaterfall(): Promise<WaterfallData> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.WATERFALL_LIVE}`);
    return toWaterfallData(response.data);
  }

  // Marker endpoints
  async getMarkers(): Promise<Marker[]> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.MARKERS_LIST}`);
    const markers = Array.isArray(response.data) ? response.data : response.data.markers ?? [];
    return markers.map(toMarker);
  }

  async createMarker(marker: Omit<Marker, 'id'>): Promise<Marker> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.MARKERS_CREATE}`, marker);
    return toMarker(response.data);
  }

  async deleteMarker(id: string): Promise<void> {
    await axios.delete(`${this.baseURL}${API_ENDPOINTS.MARKERS_DELETE(id)}`);
  }

  // Recording endpoints
  async getRecordings(): Promise<Recording[]> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.RECORDINGS_LIST}`);
    return (Array.isArray(response.data) ? response.data : response.data.recordings ?? []).map(toRecording);
  }

  async startRecording(type: 'iq' | 'audio', duration?: number): Promise<Recording> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.RECORDINGS_START}`, {
      type,
      duration_seconds: duration,
    });
    return toRecording(response.data);
  }

  async stopRecording(): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.RECORDINGS_STOP}`);
  }

  // Demodulation endpoints
  async startDemodulation(mode: string, frequency: number): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.DEMODULATION_START}`, {
      mode,
      frequency_hz: frequency,
    });
  }

  async stopDemodulation(): Promise<void> {
    await axios.post(`${this.baseURL}${API_ENDPOINTS.DEMODULATION_STOP}`);
  }

  async getDemodulationAudioStatus(): Promise<{ is_active: boolean; mode: string }> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.DEMODULATION_AUDIO_STATUS}`);
    return response.data;
  }

  async demodulateMarkerBand(request: {
    startFrequencyHz: number;
    stopFrequencyHz: number;
    mode: string;
    durationSeconds: number;
  }): Promise<DemodulationResult> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.DEMODULATION_MARKER_BAND}`, {
      start_frequency_hz: request.startFrequencyHz,
      stop_frequency_hz: request.stopFrequencyHz,
      mode: request.mode,
      duration_seconds: request.durationSeconds,
    });
    return response.data;
  }

  async getDemodulationResults(): Promise<DemodulationResult[]> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.DEMODULATION_RESULTS}`);
    return Array.isArray(response.data) ? response.data : response.data.results ?? [];
  }

  getDemodulationAudioUrl(id: string): string {
    return `${this.baseURL}${API_ENDPOINTS.DEMODULATION_AUDIO(id)}`;
  }

  // Modulated signal analysis capture endpoints
  async captureModulatedSignal(request: {
    startFrequencyHz: number;
    stopFrequencyHz: number;
    durationSeconds: number;
    label: string;
    modulationHint: string;
    notes: string;
    fileFormat: 'cfile' | 'iq';
  }): Promise<ModulatedSignalCapture> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.MODULATED_SIGNAL_CAPTURES}`, {
      start_frequency_hz: request.startFrequencyHz,
      stop_frequency_hz: request.stopFrequencyHz,
      duration_seconds: request.durationSeconds,
      label: request.label,
      modulation_hint: request.modulationHint,
      notes: request.notes,
      file_format: request.fileFormat,
    });
    return response.data;
  }

  async getModulatedSignalCaptures(): Promise<ModulatedSignalCapture[]> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.MODULATED_SIGNAL_CAPTURES}`);
    return Array.isArray(response.data) ? response.data : response.data.captures ?? [];
  }

  getModulatedSignalIqUrl(id: string): string {
    return `${this.baseURL}${API_ENDPOINTS.MODULATED_SIGNAL_IQ(id)}`;
  }

  getModulatedSignalMetadataUrl(id: string): string {
    return `${this.baseURL}${API_ENDPOINTS.MODULATED_SIGNAL_METADATA(id)}`;
  }

  // Preset endpoints
  async getPresets(): Promise<Preset[]> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.PRESETS_LIST}`);
    return (Array.isArray(response.data) ? response.data : response.data.presets ?? []).map(toPreset);
  }

  async createPreset(name: string, settings: AnalyzerSettings): Promise<Preset> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.PRESETS_CREATE}`, {
      name,
      settings,
    });
    return toPreset(response.data);
  }

  async loadPreset(id: string): Promise<Preset> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.PRESETS_LOAD(id)}`);
    return toPreset(response.data);
  }

  async deletePreset(id: string): Promise<void> {
    await axios.delete(`${this.baseURL}${API_ENDPOINTS.PRESETS_DELETE(id)}`);
  }

  // Session endpoints
  async getSessions(): Promise<Session[]> {
    const response = await axios.get(`${this.baseURL}${API_ENDPOINTS.SESSIONS_LIST}`);
    return (Array.isArray(response.data) ? response.data : response.data.sessions ?? []).map(toSession);
  }

  async createSession(name: string): Promise<Session> {
    const response = await axios.post(`${this.baseURL}${API_ENDPOINTS.SESSIONS_CREATE}`, { name });
    return toSession(response.data);
  }
}
