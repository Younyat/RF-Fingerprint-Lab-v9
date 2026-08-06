import { useState } from 'react';
import AcquisitionQualityTab from './AcquisitionQualityTab';
import CampaignTab from './CampaignTab';
import GuidedValidationTab from './GuidedValidationTab';
import IntegrityLeakageTab from './IntegrityLeakageTab';
import ProtocolTab from './ProtocolTab';
import ReadinessTab from './ReadinessTab';

// The full specification calls for 14 tabs. Fase 1+2 implement the five
// this phase's backend supports (Protocol, Readiness, Campaign, Integrity
// and Leakage, Acquisition Quality); the remaining 9 (RQ1-4, S1-S2,
// forensics, reproducibility, export) are declared here so the navigation
// shape matches the final module from day one, but stay disabled rather
// than rendering UI for endpoints that do not exist yet -- see
// docs/ble/SCIENTIFIC_STATUS.md and the Fase 1/2 plan for what each one
// will cover.
const TABS: { id: string; label: string; enabled: boolean }[] = [
  { id: 'guided-validation', label: 'Guided Validation', enabled: true },
  { id: 'protocol', label: 'Protocol', enabled: true },
  { id: 'readiness', label: 'Readiness', enabled: true },
  { id: 'campaign', label: 'Campaign', enabled: true },
  { id: 'integrity', label: 'Integrity and Leakage', enabled: true },
  { id: 'quality', label: 'Acquisition Quality', enabled: true },
  { id: 'rq1', label: 'RQ1', enabled: false },
  { id: 'rq2', label: 'RQ2', enabled: false },
  { id: 'rq3', label: 'RQ3', enabled: false },
  { id: 'rq4', label: 'RQ4', enabled: false },
  { id: 's1', label: 'Channel Transport', enabled: false },
  { id: 's2', label: 'Online Equivalence', enabled: false },
  { id: 'forensics', label: 'Calibration and Forensics', enabled: false },
  { id: 'reproducibility', label: 'Reproducibility', enabled: false },
  { id: 'export', label: 'Paper Export', enabled: false },
];

export default function BleScientificResultsPage() {
  const [activeTab, setActiveTab] = useState('guided-validation');
  const [showFutureAnalysisInfo, setShowFutureAnalysisInfo] = useState(false);

  // Rutas y componentes de las 9 pestañas "Fase 3+" NO se eliminan -- solo
  // se agrupan visualmente detrás de una unica entrada mientras la
  // identificacion fisica no este disponible (ver GuidedValidationTab).
  const visibleTabs = TABS.filter((tab) => tab.enabled);
  const futureTabs = TABS.filter((tab) => !tab.enabled);

  return (
    <div>
      <div className="sticky top-0 z-10 border-b border-slate-800 bg-slate-950/95 px-4 py-2 backdrop-blur">
        <div className="mb-2">
          <div className="text-base font-bold text-slate-100">BLE Scientific Results Studio</div>
          <div className="text-xs text-slate-500">
            Capa autoritativa para los resultados empiricos del paper BLE -- contratos de analisis congelados,
            preflight cientifico, registros canonicos y contabilidad de campana. Fase 2 de 6. Nunca modifica los
            manifests o artefactos de BLE-RFFI Studio.
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1">
          {visibleTabs.map((tab) => (
            <button
              key={tab.id}
              className={`rounded px-2.5 py-1 text-xs transition-colors ${
                activeTab === tab.id ? 'bg-cyan-600/30 text-cyan-100' : 'text-slate-400 hover:bg-slate-800'
              }`}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
          <button
            className="rounded px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-800 hover:text-slate-400"
            onClick={() => setShowFutureAnalysisInfo((v) => !v)}
          >
            Análisis científicos posteriores
          </button>
        </div>
        {showFutureAnalysisInfo && (
          <div className="mt-2 rounded border border-slate-700 bg-slate-900/60 px-3 py-2 text-xs text-slate-400">
            Estas funciones ({futureTabs.map((tab) => tab.label).join(', ')}) se habilitarán cuando la asociación
            física haya sido comprobada.
          </div>
        )}
      </div>

      {activeTab === 'guided-validation' && <GuidedValidationTab />}
      {activeTab === 'protocol' && <ProtocolTab />}
      {activeTab === 'readiness' && <ReadinessTab />}
      {activeTab === 'campaign' && <CampaignTab />}
      {activeTab === 'integrity' && <IntegrityLeakageTab />}
      {activeTab === 'quality' && <AcquisitionQualityTab />}
    </div>
  );
}
