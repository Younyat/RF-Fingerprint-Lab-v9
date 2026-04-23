import { createBrowserRouter, RouterProvider } from 'react-router-dom';
import { SpectrumView } from '../../presentation/views/SpectrumView';
import { WaterfallView } from '../../presentation/views/WaterfallView';
import { RecordingsView } from '../../presentation/views/RecordingsView';
import { SettingsView } from '../../presentation/views/SettingsView';
import { AppLayout } from '../../presentation/views/AppLayout';
import { DemodulationView } from '../../presentation/views/DemodulationView';
import { ModulatedSignalAnalysisView } from '../../presentation/views/ModulatedSignalAnalysisView';
import { ReceiversMapView } from '../../presentation/views/kiwisdr/ReceiversMapView';

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
    children: [
      {
        index: true,
        element: <SpectrumView />,
      },
      {
        path: 'spectrum',
        element: <SpectrumView />,
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
