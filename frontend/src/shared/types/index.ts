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

export interface ModulatedSignalCapture {
  id: string;
  generated_at_utc: string;
  capture_type: string;
  file_format?: 'cfile' | 'iq';
  source_device: string;
  driver: string;
  label?: string;
  modulation_hint?: string;
  notes?: string;
  dataset_split?: 'train' | 'val' | 'predict';
  session_id?: string;
  transmitter_id?: string;
  transmitter_class?: string;
  operator?: string;
  environment?: string;
  start_frequency_hz: number;
  stop_frequency_hz: number;
  center_frequency_hz: number;
  bandwidth_hz: number;
  duration_seconds: number;
  sample_rate_hz: number;
  sample_count: number;
  gain_db: number;
  antenna: string;
  device_addr: string;
  channel_index: number;
  iq_file: string;
  metadata_file: string;
  iq_format: string;
  file_extension?: string;
  iq_dtype: string;
  byte_order: string;
  file_size_bytes: number;
  sha256: string;
  iq_url?: string;
  metadata_url?: string;
  replay_parameters?: {
    center_frequency_hz: number;
    sample_rate_hz: number;
    gain_db: number;
    antenna: string;
    iq_format: string;
  };
  ai_dataset_fields?: string[];
  preview_metrics?: {
    live_preview_snr_db?: number;
    live_preview_noise_floor_db?: number;
    live_preview_peak_level_db?: number;
    live_preview_peak_frequency_hz?: number;
  };
  trigger_capture?: {
    mode?: 'immediate' | 'triggered_burst';
    threshold_db?: number;
    pre_trigger_ms?: number;
    post_trigger_ms?: number;
    trigger_max_wait_s?: number;
    trigger_detected?: boolean;
    burst_start_sample?: number;
    burst_end_sample?: number;
    captured_duration_s?: number;
  };
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

export interface FingerprintingDashboardSummary {
  modes: Array<{
    id: string;
    title: string;
    goal: string;
  }>;
  thresholds: Record<string, number>;
  summary: {
    total_captures: number;
    valid_captures: number;
    doubtful_captures: number;
    rejected_captures: number;
  };
  required_metadata: string[];
}

export interface FingerprintingCaptureRecord {
  capture_id: string;
  capture_mode: string;
  session_id: string;
  dataset_split: string;
  created_at_utc: string;
  updated_at_utc?: string;
  capture_config: {
    device_source: string;
    sdr_model: string;
    sdr_serial: string;
    gain_stage?: string;
    antenna_port: string;
    capture_type: string;
    center_frequency_hz: number;
    sample_rate_hz: number;
    effective_bandwidth_hz: number;
    frontend_bandwidth_hz?: number | null;
    gain_mode: string;
    gain_settings: Record<string, unknown>;
    ppm_correction: number;
    lo_offset_hz: number;
    capture_duration_s: number;
    sample_count: number;
    file_format: string;
    sample_dtype: string;
    byte_order: string;
    channel_count: number;
    output_path: string;
    dataset_destination?: string;
  };
  transmitter: {
    transmitter_label: string;
    transmitter_class: string;
    transmitter_id: string;
    family: string;
    ground_truth_confidence: string;
  };
  scenario: {
    operator: string;
    environment: string;
    distance_m?: number | null;
    line_of_sight?: boolean | null;
    indoor?: boolean | null;
    notes: string;
    session_number: number;
    timestamp_utc: string;
  };
  quality_metrics: {
    estimated_snr_db?: number;
    spectral_snr_db?: number | null;
    noise_floor_db?: number | null;
    peak_power_db?: number | null;
    average_power_db?: number | null;
    occupied_bandwidth_hz?: number | null;
    peak_frequency_hz?: number | null;
    frequency_offset_hz?: number;
    clipping_pct?: number;
    sample_drop_count?: number;
    buffer_overflow_count?: number;
    silence_pct?: number;
    peak_to_average_ratio_db?: number | null;
    kurtosis?: number | null;
    burst_duration_ms?: number;
  };
  burst_detection: {
    method: string;
    energy_threshold_db?: number | null;
    pre_trigger_samples: number;
    post_trigger_samples: number;
    min_burst_duration_ms: number;
    max_burst_duration_ms?: number | null;
    burst_count: number;
    regions_of_interest: string[];
    burst_start_sample?: number | null;
    burst_end_sample?: number | null;
  };
  quality_review: {
    status: 'valid' | 'doubtful' | 'rejected';
    reasons: string[];
    quality_flags: string[];
    operator_decision?: 'valid' | 'doubtful' | 'rejected' | null;
    review_notes?: string;
    export_windows?: string[];
    updated_at_utc?: string;
  };
  artifacts: {
    iq_file?: string | null;
    metadata_file?: string | null;
    sha256?: string | null;
    source_capture_id?: string | null;
  };
  preview_metrics?: {
    live_preview_snr_db?: number | null;
    live_preview_noise_floor_db?: number | null;
    live_preview_peak_level_db?: number | null;
    live_preview_peak_frequency_hz?: number | null;
  };
}

export interface TrainingDashboard {
  model_dir: string;
  current_model: {
    path: string;
    exists: boolean;
    size_bytes: number;
    modified_at_utc?: string | null;
    train_config?: Record<string, unknown>;
    dataset_manifest?: Record<string, unknown>;
    label_map?: Record<string, unknown>;
    file_inventory?: Array<{
      name: string;
      path: string;
      size_bytes: number;
      modified_at_utc?: string | null;
    }>;
  };
  dataset: {
    records: number;
    devices: number;
    sessions: number;
    device_ids: string[];
  };
  training: {
    epochs: number;
    best_test_acc: number;
    last_test_acc: number;
    last_train_acc: number;
    best_epoch: number | null;
    config: Record<string, unknown>;
    profiles_count: number;
    labeled_devices: number;
    latest_history: Array<Record<string, unknown>>;
  };
  retraining: {
    snapshot_count: number;
    snapshots: Array<Record<string, unknown>>;
  };
  prediction_readiness: {
    has_model_file: boolean;
    has_profiles: boolean;
    has_manifest: boolean;
    has_history: boolean;
    has_validation: boolean;
    latest_validation?: Record<string, unknown> | null;
  };
  validation_reports: Array<Record<string, unknown>>;
  filesystem: {
    model_dir_exists: boolean;
    model_dir_size_bytes: number;
    train_dataset_dir: string;
    train_dataset_size_bytes: number;
    val_dataset_dir: string;
    val_dataset_size_bytes: number;
    predict_dataset_dir: string;
    predict_dataset_size_bytes: number;
  };
}

export interface AsyncJobStatus {
  status: string;
  job_id?: string;
  started_at_utc?: string;
  ended_at_utc?: string | null;
  returncode?: number | null;
  command?: string[];
  cwd?: string | null;
  metadata?: Record<string, unknown>;
  stdout?: string;
  stderr?: string;
  report?: Record<string, unknown>;
}

export interface ModelArtifactSummary {
  version?: string;
  created_at_utc?: string;
  metrics?: Record<string, unknown>;
  [key: string]: unknown;
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
  theme: 'light' | 'dark' | 'laboratory';
  sidebarCollapsed: boolean;
  activeTab: 'spectrum' | 'waterfall' | 'recordings' | 'settings';
}

