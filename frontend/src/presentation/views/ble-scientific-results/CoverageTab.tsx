import { BleScientificResultsApiService } from '../../../app/services/bleScientificResultsApi';
import RunScopedJsonReport from './RunScopedJsonReport';

const sciApi = new BleScientificResultsApiService();

export default function CoverageTab() {
  return (
    <RunScopedJsonReport
      title="Coverage / Abstention"
      description="Ventanas elegibles, decididas, abstenidas y curva risk-coverage -- leido de confirmatory_future_analysis_report.json (coverage, risk_coverage). Obligatorio para el paper."
      noDataReason="confirmatory_future_analysis_report.json no existe todavia para este run."
      fetchReport={(paperRunId) => sciApi.confirmatoryFutureAnalysis(paperRunId)}
    />
  );
}
