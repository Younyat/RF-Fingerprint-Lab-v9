import { BleScientificResultsApiService } from '../../../app/services/bleScientificResultsApi';
import RunScopedJsonReport from './RunScopedJsonReport';

const sciApi = new BleScientificResultsApiService();

export default function SensitivityTab() {
  return (
    <RunScopedJsonReport
      title="Sensitivity analyses"
      description="Leave-one-device-out, offset-retaining preprocessing, variabilidad por semilla fija -- leido de confirmatory_statistical_plan_report.json (VALIDATION_DRY_RUN). Nunca mezclado con resultados confirmatorios primarios (ver RQ1-4)."
      noDataReason="confirmatory_statistical_plan_report.json no existe todavia para este run."
      fetchReport={(paperRunId) => sciApi.confirmatoryStatisticalPlan(paperRunId)}
    />
  );
}
