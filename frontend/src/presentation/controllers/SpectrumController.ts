import { useCallback } from 'react';
import { useAppActions } from '../../app/store/AppStore';
import { ApiService } from '../../app/services/ApiService';
import type { AnalyzerSettings } from '../../shared/types';

const apiService = new ApiService();

export const useSpectrumController = () => {
  const actions = useAppActions();

  const startDeviceStream = useCallback(async () => {
    await apiService.startDeviceStream();
    const status = await apiService.getDeviceStatus();
    actions.setDeviceStatus(status);
  }, [actions]);

  const stopDeviceStream = useCallback(async () => {
    await apiService.stopDeviceStream();
    const status = await apiService.getDeviceStatus();
    actions.setDeviceStatus(status);
  }, [actions]);

  const connectDevice = useCallback(async () => {
    const status = await apiService.connectDevice();
    actions.setDeviceStatus(status);
  }, [actions]);

  const disconnectDevice = useCallback(async () => {
    const status = await apiService.disconnectDevice();
    actions.setDeviceStatus(status);
  }, [actions]);

  const openWfmReceiver = useCallback(async () => {
    const status = await apiService.openWfmReceiver();
    actions.setDeviceStatus(status);
  }, [actions]);

  const closeWfmReceiver = useCallback(async () => {
    const status = await apiService.closeWfmReceiver();
    actions.setDeviceStatus(status);
  }, [actions]);

  const setCenterFrequency = useCallback(async (frequency: number) => {
    await apiService.setSpectrumCenterFrequency(frequency);
    actions.setDeviceStatus({ centerFrequency: frequency });
    actions.updateAnalyzerSettings({ centerFrequency: frequency });
  }, [actions]);

  const setStartStop = useCallback(async (startFrequency: number, stopFrequency: number) => {
    const span = stopFrequency - startFrequency;
    const center = startFrequency + span / 2;
    await apiService.setSpectrumStartStop(startFrequency, stopFrequency);
    actions.setDeviceStatus({ centerFrequency: center, sampleRate: span });
    actions.updateAnalyzerSettings({ centerFrequency: center, span });
  }, [actions]);

  const setSpan = useCallback(async (span: number) => {
    await apiService.setSpectrumSpan(span);
    actions.setDeviceStatus({ sampleRate: span });
    actions.updateAnalyzerSettings({ span });
  }, [actions]);

  const setGain = useCallback(async (gain: number) => {
    await apiService.setDeviceGain(gain);
    actions.setDeviceStatus({ gain });
  }, [actions]);

  const setRbw = useCallback(async (rbw: number) => {
    await apiService.setSpectrumRbw(rbw);
    actions.updateAnalyzerSettings({ rbw });
  }, [actions]);

  const setReferenceLevel = useCallback(async (level: number) => {
    await apiService.setSpectrumReferenceLevel(level);
    actions.updateAnalyzerSettings({ referenceLevel: level });
  }, [actions]);

  const setVbw = useCallback(async (vbw: number) => {
    await apiService.setSpectrumVbw(vbw);
    actions.updateAnalyzerSettings({ vbw });
  }, [actions]);

  const setNoiseFloorOffset = useCallback(async (offset: number) => {
    await apiService.setSpectrumNoiseFloorOffset(offset);
    actions.updateAnalyzerSettings({ noiseFloorOffset: offset });
  }, [actions]);

  const setDetectorMode = useCallback(async (mode: AnalyzerSettings['detectorMode']) => {
    await apiService.setSpectrumDetectorMode(mode);
    actions.updateAnalyzerSettings({ detectorMode: mode });
  }, [actions]);

  const setAveraging = useCallback(async (count: number) => {
    await apiService.setSpectrumAveraging(count);
    actions.updateAnalyzerSettings({ averaging: count });
  }, [actions]);

  const refreshSpectrum = useCallback(async () => {
    const spectrumData = await apiService.getLiveSpectrum();
    actions.setSpectrumData(spectrumData);
  }, [actions]);

  const setTraceDisplay = useCallback((settings: Pick<AnalyzerSettings, 'traceMode' | 'dbPerDiv' | 'colorScheme'>) => {
    actions.updateAnalyzerSettings(settings);
  }, [actions]);

  return {
    startDeviceStream,
    stopDeviceStream,
    connectDevice,
    disconnectDevice,
    openWfmReceiver,
    closeWfmReceiver,
    setCenterFrequency,
    setStartStop,
    setSpan,
    setGain,
    setRbw,
    setVbw,
    setReferenceLevel,
    setNoiseFloorOffset,
    setDetectorMode,
    setAveraging,
    setTraceDisplay,
    refreshSpectrum,
  };
};
