import { BleScientificResultsApiService } from '../../../app/services/bleScientificResultsApi';
import RunScopedJsonReport from './RunScopedJsonReport';

const sciApi = new BleScientificResultsApiService();

export default function Rq1Tab() {
  return (
    <RunScopedJsonReport
      title="RQ1 -- Acquisition dependence"
      description="BA_window / BA_capture / BA_future, deltas, cobertura -- leidos directamente de rq1_acquisition_dependence_report.json (persist_rq1_acquisition_dependence_report). No se recalcula nada aqui."
      noDataReason="rq1_acquisition_dependence_report.json no existe todavia para este run -- pendiente de CONFIRMATORY_FUTURE."
      fetchReport={(paperRunId) => sciApi.rq1AcquisitionDependence(paperRunId)}
    />
  );
}
