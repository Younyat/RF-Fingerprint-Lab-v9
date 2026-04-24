import { create } from 'zustand';
import { subscribeWithSelector } from 'zustand/middleware';
import {
  SpectrumData,
  WaterfallData,
  Marker,
  DeviceStatus,
  AnalyzerSettings,
  Recording,
  Session,
  Preset,
  UiState
} from '../../shared/types';
import { DEFAULT_SETTINGS } from '../../shared/constants';

interface AppState {
  // UI State
  ui: UiState;

  // Domain State
  spectrumData: SpectrumData | null;
  waterfallData: WaterfallData[];
  markers: Marker[];
  deviceStatus: DeviceStatus;
  analyzerSettings: AnalyzerSettings;
  recordings: Recording[];
  sessions: Session[];
  presets: Preset[];
  currentSession: Session | null;
  currentRecording: Recording | null;

  // Actions
  setUiState: (updates: Partial<UiState>) => void;

  setSpectrumData: (data: SpectrumData) => void;
  setWaterfallData: (data: WaterfallData) => void;
  addWaterfallData: (data: WaterfallData) => void;
  clearWaterfallData: () => void;

  addMarker: (marker: Marker) => void;
  updateMarker: (id: string, updates: Partial<Marker>) => void;
  removeMarker: (id: string) => void;
  clearMarkers: () => void;

  setDeviceStatus: (status: Partial<DeviceStatus>) => void;
  updateAnalyzerSettings: (settings: Partial<AnalyzerSettings>) => void;

  addRecording: (recording: Recording) => void;
  setRecordings: (recordings: Recording[]) => void;
  setCurrentRecording: (recording: Recording | null) => void;

  addSession: (session: Session) => void;
  setSessions: (sessions: Session[]) => void;
  setCurrentSession: (session: Session | null) => void;

  addPreset: (preset: Preset) => void;
  setPresets: (presets: Preset[]) => void;
  removePreset: (id: string) => void;

  // Reset
  reset: () => void;
}

const initialState = {
  ui: {
    theme: 'light' as const,
    sidebarCollapsed: false,
    activeTab: 'spectrum' as const,
  },

  spectrumData: null,
  waterfallData: [],
  markers: [],
  deviceStatus: {
    isConnected: false,
    driver: 'uhd_gnuradio',
    centerFrequency: 89400000,
    sampleRate: 2000000,
    gain: 0,
  },
  analyzerSettings: DEFAULT_SETTINGS,
  recordings: [],
  sessions: [],
  presets: [],
  currentSession: null,
  currentRecording: null,
};

export const useAppStore = create<AppState>()(
  subscribeWithSelector((set) => ({
    ...initialState,

    setUiState: (updates) =>
      set((state) => ({
        ui: { ...state.ui, ...updates },
      })),

    setSpectrumData: (data) =>
      set({ spectrumData: data }),

    setWaterfallData: (data) =>
      set({ waterfallData: [data] }),

    addWaterfallData: (data) =>
      set((state) => ({
        waterfallData: [...state.waterfallData.slice(-99), data], // Keep last 100 entries
      })),

    clearWaterfallData: () =>
      set({ waterfallData: [] }),

    addMarker: (marker) =>
      set((state) => ({
        markers: [...state.markers, marker],
      })),

    updateMarker: (id, updates) =>
      set((state) => ({
        markers: state.markers.map((marker) =>
          marker.id === id ? { ...marker, ...updates } : marker
        ),
      })),

    removeMarker: (id) =>
      set((state) => ({
        markers: state.markers.filter((marker) => marker.id !== id),
      })),

    clearMarkers: () =>
      set({ markers: [] }),

    setDeviceStatus: (status) =>
      set((state) => ({
        deviceStatus: { ...state.deviceStatus, ...status },
      })),

    updateAnalyzerSettings: (settings) =>
      set((state) => ({
        analyzerSettings: { ...state.analyzerSettings, ...settings },
      })),

    addRecording: (recording) =>
      set((state) => ({
        recordings: [...state.recordings, recording],
      })),

    setRecordings: (recordings) =>
      set({ recordings }),

    setCurrentRecording: (recording) =>
      set({ currentRecording: recording }),

    addSession: (session) =>
      set((state) => ({
        sessions: [...state.sessions, session],
      })),

    setSessions: (sessions) =>
      set({ sessions }),

    setCurrentSession: (session) =>
      set({ currentSession: session }),

    addPreset: (preset) =>
      set((state) => ({
        presets: [...state.presets, preset],
      })),

    setPresets: (presets) =>
      set({ presets }),

    removePreset: (id) =>
      set((state) => ({
        presets: state.presets.filter((preset) => preset.id !== id),
      })),

    reset: () =>
      set(initialState),
  }))
);

// Selectors
export const useSpectrumData = () => useAppStore((state) => state.spectrumData);
export const useWaterfallData = () => useAppStore((state) => state.waterfallData);
export const useMarkers = () => useAppStore((state) => state.markers);
export const useDeviceStatus = () => useAppStore((state) => state.deviceStatus);
export const useAnalyzerSettings = () => useAppStore((state) => state.analyzerSettings);
export const useRecordings = () => useAppStore((state) => state.recordings);
export const useSessions = () => useAppStore((state) => state.sessions);
export const usePresets = () => useAppStore((state) => state.presets);
export const useCurrentSession = () => useAppStore((state) => state.currentSession);
export const useCurrentRecording = () => useAppStore((state) => state.currentRecording);
export const useUiState = () => useAppStore((state) => state.ui);

// Actions
export const useAppActions = () => useAppStore((state) => ({
  setUiState: state.setUiState,
  setSpectrumData: state.setSpectrumData,
  setWaterfallData: state.setWaterfallData,
  addWaterfallData: state.addWaterfallData,
  clearWaterfallData: state.clearWaterfallData,
  addMarker: state.addMarker,
  updateMarker: state.updateMarker,
  removeMarker: state.removeMarker,
  clearMarkers: state.clearMarkers,
  setDeviceStatus: state.setDeviceStatus,
  updateAnalyzerSettings: state.updateAnalyzerSettings,
  addRecording: state.addRecording,
  setRecordings: state.setRecordings,
  setCurrentRecording: state.setCurrentRecording,
  addSession: state.addSession,
  setSessions: state.setSessions,
  setCurrentSession: state.setCurrentSession,
  addPreset: state.addPreset,
  setPresets: state.setPresets,
  removePreset: state.removePreset,
  reset: state.reset,
}));
