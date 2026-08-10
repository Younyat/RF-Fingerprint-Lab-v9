import { BleScientificResultsApiService } from '../../../app/services/bleScientificResultsApi';
import MechanismDataNotice from './MechanismDataNotice';
import RunScopedJsonReport from './RunScopedJsonReport';

const sciApi = new BleScientificResultsApiService();

export default function Rq2Tab() {
  return (
    <div className="space-y-4">
      <div className="px-4 pt-4">
        <MechanismDataNotice dataReason="No existe todavia un producer canonico de comparacion por rama (engineered_rf / raw_iq / stft / coarse_morphology) -- confirmatory_future_analysis_report.json guarda los 11 metodos estadisticos generales, no una tabla per-rama. La brecha esta documentada honestamente en paper_export.py, no inventada aqui." />
      </div>
      <RunScopedJsonReport
        title="RQ2 -- Representation comparison"
        description="Engineered RF / raw I/Q CNN1D / STFT CNN2D / coarse morphology -- leido de confirmatory_future_analysis_report.json. Solo confirmatorio tras un protocol freeze real (ver Study Overview)."
        noDataReason="confirmatory_future_analysis_report.json no existe todavia para este run -- pendiente de CONFIRMATORY_FUTURE."
        fetchReport={(paperRunId) => sciApi.confirmatoryFutureAnalysis(paperRunId)}
      />
    </div>
  );
}
