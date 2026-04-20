// UI Constants
export const THEME = {
  COLORS: {
    primary: '#3b82f6',
    secondary: '#64748b',
    success: '#10b981',
    warning: '#f59e0b',
    error: '#ef4444',
    background: '#ffffff',
    surface: '#f8fafc',
    text: '#1e293b',
    textSecondary: '#64748b',
  },
  SPACING: {
    xs: '0.25rem',
    sm: '0.5rem',
    md: '1rem',
    lg: '1.5rem',
    xl: '2rem',
    xxl: '3rem',
  },
  BORDER_RADIUS: {
    sm: '0.25rem',
    md: '0.375rem',
    lg: '0.5rem',
    xl: '0.75rem',
  },
} as const;

// Frequency Units
export const FREQUENCY_UNITS = {
  Hz: 1,
  kHz: 1000,
  MHz: 1000000,
  GHz: 1000000000,
} as const;

// Detector Modes
export const DETECTOR_MODES = [
  { value: 'sample', label: 'Sample' },
  { value: 'rms', label: 'RMS' },
  { value: 'average', label: 'Average' },
  { value: 'peak', label: 'Peak' },
  { value: 'max_hold', label: 'Max Hold' },
  { value: 'min_hold', label: 'Min Hold' },
  { value: 'video', label: 'Video' },
] as const;

export const TRACE_MODES = [
  { value: 'clear_write', label: 'Clear/Write' },
  { value: 'average', label: 'Average' },
  { value: 'max_hold', label: 'Max Hold' },
  { value: 'min_hold', label: 'Min Hold' },
  { value: 'video_average', label: 'Video Avg' },
] as const;

export const SPECTRUM_COLOR_SCHEMES = [
  { value: 'blue', label: 'Blue' },
  { value: 'green', label: 'Green' },
  { value: 'amber', label: 'Amber' },
  { value: 'magenta', label: 'Magenta' },
] as const;

// Window Functions
export const WINDOW_FUNCTIONS = [
  { value: 'hann', label: 'Hann' },
  { value: 'hamming', label: 'Hamming' },
  { value: 'blackman', label: 'Blackman' },
  { value: 'bartlett', label: 'Bartlett' },
  { value: 'rectangular', label: 'Rectangular' },
] as const;

// Demodulation Modes
export const DEMODULATION_MODES = [
  { value: 'am', label: 'AM' },
  { value: 'fm', label: 'FM' },
  { value: 'wfm', label: 'WFM' },
  { value: 'ask', label: 'ASK' },
  { value: 'fsk', label: 'FSK' },
  { value: 'psk', label: 'PSK' },
  { value: 'ook', label: 'OOK' },
] as const;

// Recording Formats
export const RECORDING_FORMATS = [
  { value: 'iq', label: 'IQ Data' },
  { value: 'audio', label: 'Audio WAV' },
] as const;

// Colormaps
export const COLORMAPS = [
  { value: 'turbo', label: 'Turbo' },
  { value: 'viridis', label: 'Viridis' },
  { value: 'plasma', label: 'Plasma' },
  { value: 'inferno', label: 'Inferno' },
  { value: 'magma', label: 'Magma' },
] as const;

// Default Settings
export const DEFAULT_SETTINGS = {
  centerFrequency: 89400000, // 89.4 MHz
  span: 2000000, // 2 MHz
  rbw: 10000, // 10 kHz
  vbw: 10000, // 10 kHz
  referenceLevel: 0, // 0 dBm
  noiseFloorOffset: 0,
  detectorMode: 'sample' as const,
  traceMode: 'clear_write' as const,
  dbPerDiv: 10,
  colorScheme: 'blue' as const,
  averaging: 1,
  smoothing: 0,
} as const;

// API Endpoints
export const API_ENDPOINTS = {
  // Device
  DEVICE_STATUS: '/api/device/status',
  DEVICE_CONNECT: '/api/device/connect',
  DEVICE_DISCONNECT: '/api/device/disconnect',
  DEVICE_OPEN_RECEIVER: '/api/device/receiver/open',
  DEVICE_CLOSE_RECEIVER: '/api/device/receiver/close',
  DEVICE_START_STREAM: '/api/device/stream/start',
  DEVICE_STOP_STREAM: '/api/device/stream/stop',
  DEVICE_SET_FREQUENCY: '/api/device/frequency',
  DEVICE_SET_GAIN: '/api/device/gain',
  DEVICE_SET_SAMPLE_RATE: '/api/device/sample-rate',

  // Spectrum
  SPECTRUM_LIVE: '/api/spectrum/live',
  SPECTRUM_SET_CENTER: '/api/spectrum/center-frequency',
  SPECTRUM_SET_SPAN: '/api/spectrum/span',
  SPECTRUM_SET_START_STOP: '/api/spectrum/start-stop',
  SPECTRUM_SET_RBW: '/api/spectrum/rbw',
  SPECTRUM_SET_VBW: '/api/spectrum/vbw',
  SPECTRUM_SET_REFERENCE_LEVEL: '/api/spectrum/reference-level',
  SPECTRUM_SET_NOISE_FLOOR: '/api/spectrum/noise-floor-offset',
  SPECTRUM_SET_DETECTOR: '/api/spectrum/detector-mode',
  SPECTRUM_SET_AVERAGING: '/api/spectrum/averaging',

  // Waterfall
  WATERFALL_LIVE: '/api/waterfall/live',

  // Markers
  MARKERS_LIST: '/api/markers/',
  MARKERS_CREATE: '/api/markers/',
  MARKERS_DELETE: (id: string) => `/api/markers/${id}`,

  // Recording
  RECORDINGS_LIST: '/api/recordings/',
  RECORDINGS_START: '/api/recordings/start',
  RECORDINGS_STOP: '/api/recordings/stop',

  // Demodulation
  DEMODULATION_START: '/api/demodulation/start',
  DEMODULATION_STOP: '/api/demodulation/stop',
  DEMODULATION_AUDIO_STATUS: '/api/demodulation/audio/status',
  DEMODULATION_MARKER_BAND: '/api/demodulation/marker-band',
  DEMODULATION_RESULTS: '/api/demodulation/results',
  DEMODULATION_AUDIO: (id: string) => `/api/demodulation/audio/${id}`,

  // Presets
  PRESETS_LIST: '/api/presets/',
  PRESETS_CREATE: '/api/presets/',
  PRESETS_LOAD: (id: string) => `/api/presets/${id}`,
  PRESETS_DELETE: (id: string) => `/api/presets/${id}`,

  // Sessions
  SESSIONS_LIST: '/api/sessions/',
  SESSIONS_CREATE: '/api/sessions/',
} as const;

