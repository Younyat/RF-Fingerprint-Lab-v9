// Domain Types
export interface SpectrumData {
  timestamp: number;
  centerFrequency: number;
  span: number;
  frequencyArray: number[];
  powerLevels: number[];
}

export interface WaterfallData {
  timestamp: number;
  centerFrequency: number;
  span: number;
  data: number[][];
}

export interface Marker {
  id: string;
  label: string;
  frequency: number;
  level: number;
  type: 'normal' | 'delta' | 'noise' | 'peak';
  enabled: boolean;
}

export interface DeviceStatus {
  isConnected: boolean;
  driver: string;
  centerFrequency: number;
  sampleRate: number;
  gain: number;
  antenna?: string;
  lastError?: string | null;
}

export interface AnalyzerSettings {
  centerFrequency: number;
  span: number;
  rbw: number;
  vbw: number;
  referenceLevel: number;
  noiseFloorOffset: number;
  detectorMode: 'sample' | 'rms' | 'average' | 'peak' | 'min_hold' | 'max_hold' | 'video';
  traceMode: 'clear_write' | 'average' | 'max_hold' | 'min_hold' | 'video_average';
  dbPerDiv: number;
  colorScheme: 'blue' | 'green' | 'amber' | 'magenta';
  averaging: number;
  smoothing: number;
}

export interface Recording {
  id: string;
  sessionId: string;
  timestamp: number;
  duration: number;
  filePath: string;
  size: number;
  type: 'iq' | 'audio';
}

export interface DemodulationResult {
  id: string;
  status: string;
  mode: string;
  start_frequency_hz: number;
  stop_frequency_hz: number;
  center_frequency_hz: number;
  bandwidth_hz: number;
  duration_seconds: number;
  sample_rate_hz: number;
  audio_supported: boolean;
  audio_file?: string | null;
  audio_url?: string | null;
  iq_file?: string;
  metadata_file?: string;
  metadata_url?: string;
  notes?: string[];
}

export interface Session {
  id: string;
  name: string;
  createdAt: number;
  recordings: Recording[];
  notes?: string;
}

export interface Preset {
  id: string;
  name: string;
  settings: AnalyzerSettings;
  createdAt: number;
}

// API Response Types
export interface ApiResponse<T> {
  data: T;
  success: boolean;
  message?: string;
}

// Form Types
export interface FrequencyInput {
  value: number;
  unit: 'Hz' | 'kHz' | 'MHz' | 'GHz';
}

export interface GainInput {
  value: number;
  mode: 'auto' | 'manual';
}

// UI State Types
export interface UiState {
  theme: 'light' | 'dark';
  sidebarCollapsed: boolean;
  activeTab: 'spectrum' | 'waterfall' | 'recordings' | 'settings';
}

