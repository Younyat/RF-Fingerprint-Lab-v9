import { BleScientificResultsApiService } from '../../../app/services/bleScientificResultsApi';
import RunScopedJsonReport from './RunScopedJsonReport';

const sciApi = new BleScientificResultsApiService();

export default function Rq2Tab() {
  return (
    <RunScopedJsonReport
      title="RQ2 -- Representation comparison"
      description="Engineered RF / raw I/Q CNN1D / STFT CNN2D / coarse morphology -- leido de confirmatory_future_analysis_report.json. Solo confirmatorio tras un protocol freeze real (ver Study Overview)."
      noDataReason="confirmatory_future_analysis_report.json no existe todavia para este run -- pendiente de CONFIRMATORY_FUTURE."
      fetchReport={(paperRunId) => sciApi.confirmatoryFutureAnalysis(paperRunId)}
    />
  );
}
