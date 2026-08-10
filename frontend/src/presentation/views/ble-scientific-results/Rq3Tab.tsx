import { BleScientificResultsApiService } from '../../../app/services/bleScientificResultsApi';
import RunScopedJsonReport from './RunScopedJsonReport';

const sciApi = new BleScientificResultsApiService();

export default function Rq3Tab() {
  return (
    <RunScopedJsonReport
      title="RQ3 -- Reset-associated displacement"
      description="delta_cycle, permutation test, pares RESET/CONTROL PRE/POST -- leido de confirmatory_future_analysis_report.json (rq3_within_device_permutation_test)."
      noDataReason="confirmatory_future_analysis_report.json no existe todavia para este run -- 0 pares reales RQ3 hasta la campana definitiva."
      fetchReport={(paperRunId) => sciApi.confirmatoryFutureAnalysis(paperRunId)}
    />
  );
}
