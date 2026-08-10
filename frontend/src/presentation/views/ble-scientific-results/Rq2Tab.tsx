import { BleScientificResultsApiService } from '../../../app/services/bleScientificResultsApi';
import BarWithCiChart, { BarWithCiDatum } from './charts/BarWithCiChart';
import RunScopedJsonReport from './RunScopedJsonReport';

const sciApi = new BleScientificResultsApiService();

function branches(report: Record<string, unknown>): { branch: string; analysis_role: string; balanced_accuracy?: number | null; coverage?: number | null }[] {
  const value = report.branches;
  return Array.isArray(value) ? (value as { branch: string; analysis_role: string; balanced_accuracy?: number | null; coverage?: number | null }[]) : [];
}

function balancedAccuracyBars(report: Record<string, unknown>): BarWithCiDatum[] {
  return branches(report)
    .filter((b) => typeof b.balanced_accuracy === 'number')
    .map((b) => ({ category: `${b.branch} (${b.analysis_role})`, value: b.balanced_accuracy as number }));
}

function coverageBars(report: Record<string, unknown>): BarWithCiDatum[] {
  return branches(report)
    .filter((b) => typeof b.coverage === 'number')
    .map((b) => ({ category: `${b.branch} (${b.analysis_role})`, value: b.coverage as number }));
}

export default function Rq2Tab() {
  return (
    <RunScopedJsonReport
      title="RQ2 -- Representation comparison"
      description="Engineered RF / raw I/Q CNN1D / STFT CNN2D / coarse morphology -- leido de rq2_representation_comparison_report.json (persist_rq2_representation_comparison_report). Cada rama declara su propio analysis_role (PRIMARY/SENSITIVITY/UNSELECTED); nada se recalcula aqui."
      noDataReason="rq2_representation_comparison_report.json no existe todavia para este run."
      fetchReport={(paperRunId) => sciApi.rq2RepresentationComparison(paperRunId)}
      renderCharts={(report) => (
        <>
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">Balanced accuracy por rama</div>
            <BarWithCiChart data={balancedAccuracyBars(report)} yLabel="Balanced accuracy" noDataReason="Ninguna rama tiene balanced_accuracy real en el reporte." />
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">Coverage por rama</div>
            <BarWithCiChart data={coverageBars(report)} yLabel="Coverage" noDataReason="Ninguna rama tiene coverage real en el reporte." />
          </div>
        </>
      )}
    />
  );
}
