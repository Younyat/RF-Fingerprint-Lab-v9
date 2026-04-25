import { createBrowserRouter, RouterProvider } from 'react-router-dom';
import { SpectrumView } from '../../presentation/views/SpectrumView';
import { WaterfallView } from '../../presentation/views/WaterfallView';
import { RecordingsView } from '../../presentation/views/RecordingsView';
import { SettingsView } from '../../presentation/views/SettingsView';
import { AppLayout } from '../../presentation/views/AppLayout';
import { DemodulationView } from '../../presentation/views/DemodulationView';
import { ModulatedSignalAnalysisView } from '../../presentation/views/ModulatedSignalAnalysisView';
import { ReceiversMapView } from '../../presentation/views/kiwisdr/ReceiversMapView';
import { FingerprintingOverviewView } from '../../presentation/views/FingerprintingOverviewView';
import { DatasetBuilderView } from '../../presentation/views/DatasetBuilderView';
import { TrainingLabView } from '../../presentation/views/TrainingLabView';
import { ValidationLabView } from '../../presentation/views/ValidationLabView';
import { InferenceLabView } from '../../presentation/views/InferenceLabView';
import { ModelRegistryView } from '../../presentation/views/ModelRegistryView';
import { RetrainingLabView } from '../../presentation/views/RetrainingLabView';

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
    children: [
      {
        index: true,
        element: <FingerprintingOverviewView />,
      },
      {
        path: 'spectrum',
        element: <SpectrumView />,
      },
      {
        path: 'capture',
        element: <ModulatedSignalAnalysisView />,
      },
      {
        path: 'guided-capture',
        element: <ModulatedSignalAnalysisView />,
      },
      {
        path: 'dataset-builder',
        element: <DatasetBuilderView />,
      },
      {
        path: 'training',
        element: <TrainingLabView />,
      },
      {
        path: 'retraining',
        element: <RetrainingLabView />,
      },
      {
        path: 'validation',
        element: <ValidationLabView />,
      },
      {
        path: 'inference',
        element: <InferenceLabView />,
      },
      {
        path: 'models',
        element: <ModelRegistryView />,
      },
      {
        path: 'waterfall',
        element: <WaterfallView />,
      },
      {
        path: 'recordings',
        element: <RecordingsView />,
      },
      {
        path: 'demodulation',
        element: <DemodulationView />,
      },
      {
        path: 'modulated-analysis',
        element: <ModulatedSignalAnalysisView />,
      },
      {
        path: 'kiwisdr',
        element: <ReceiversMapView />,
      },
      {
        path: 'settings',
        element: <SettingsView />,
      },
    ],
  },
]);

export const AppRouter = () => {
  return <RouterProvider router={router} />;
};
