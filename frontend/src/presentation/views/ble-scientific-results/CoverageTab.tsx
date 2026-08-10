import { BleScientificResultsApiService } from '../../../app/services/bleScientificResultsApi';
import RiskCoverageChart, { RiskCoveragePoint } from './charts/RiskCoverageChart';
import RunScopedJsonReport from './RunScopedJsonReport';

const sciApi = new BleScientificResultsApiService();

function riskCoveragePoints(report: Record<string, unknown>): RiskCoveragePoint[] {
  const method = report.risk_coverage as { status?: string; value?: { coverage?: number; risk?: number }[] } | undefined;
  if (method?.status !== 'EXECUTED' || !Array.isArray(method.value)) return [];
  return method.value
    .filter((p) => typeof p.coverage === 'number' && typeof p.risk === 'number')
    .map((p) => ({ coverage: p.coverage as number, risk: p.risk as number }));
}

export default function CoverageTab() {
  return (
    <RunScopedJsonReport
      title="Coverage / Abstention"
      description="Ventanas elegibles, decididas, abstenidas y curva risk-coverage -- leido de confirmatory_future_analysis_report.json (coverage, risk_coverage). Obligatorio para el paper."
      noDataReason="confirmatory_future_analysis_report.json no existe todavia para este run."
      fetchReport={(paperRunId) => sciApi.confirmatoryFutureAnalysis(paperRunId)}
      renderCharts={(report) => (
        <div>
          <div className="mb-1 text-xs font-semibold text-slate-400">Curva risk-coverage</div>
          <RiskCoverageChart points={riskCoveragePoints(report)} noDataReason="risk_coverage no esta EXECUTED en el reporte para este run." />
        </div>
      )}
    />
  );
}
