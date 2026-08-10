import { BleScientificResultsApiService } from '../../../app/services/bleScientificResultsApi';
import RunScopedJsonReport from './RunScopedJsonReport';

const sciApi = new BleScientificResultsApiService();

export default function Rq4Tab() {
  return (
    <RunScopedJsonReport
      title="RQ4 -- Packet-content dependence"
      description="FULL_BURST / ADVA_EXCLUDED / PRE_PDU (analytical_region) vs ORIGINAL / CONTROLLED_VARIANT (packet_condition), comparacion pareada y non-inferiority -- leido de confirmatory_future_analysis_report.json (rq4_paired_comparison, non_inferiority)."
      noDataReason="confirmatory_future_analysis_report.json no existe todavia para este run -- pendiente de CONFIRMATORY_FUTURE."
      fetchReport={(paperRunId) => sciApi.confirmatoryFutureAnalysis(paperRunId)}
    />
  );
}
