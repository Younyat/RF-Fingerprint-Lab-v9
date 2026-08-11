import { useEffect, useState } from 'react';
import { BleScientificResultsApiService, NoDataResponse, Rq2RepresentationComparisonReport } from '../../../app/services/bleScientificResultsApi';
import BarWithCiChart, { BarWithCiDatum } from './charts/BarWithCiChart';
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

function coverageMethodValue(report: Record<string, unknown>): number | null {
  const method = report.coverage as { status?: string; value?: number } | undefined;
  return method?.status === 'EXECUTED' && typeof method.value === 'number' ? method.value : null;
}

/** Coverage-by-branch reuses RQ2's own real per-branch `coverage` field
 * (rq2_representation_comparison_report.json) -- a real, already-persisted
 * artifact, never a new computation. Coverage-by-domain/by-unit and an
 * abstention-reason distribution are NOT wired: no canonical report tags
 * a risk-coverage curve with a domain, and no per-unit coverage or
 * abstention-reason taxonomy is computed anywhere (campaign_deviations'
 * real deviation_type values carry no "abstention" category) -- shown
 * honestly as MISSING_CANONICAL_METRIC below rather than guessed. */
function CoverageByBranch({ paperRunId }: { paperRunId: string }) {
  const [report, setReport] = useState<Rq2RepresentationComparisonReport | NoDataResponse | null>(null);
  useEffect(() => {
    sciApi.rq2RepresentationComparison(paperRunId).then(setReport).catch(() => setReport({ status: 'NO_DATA' }));
  }, [paperRunId]);

  const bars: BarWithCiDatum[] = report && (report as Rq2RepresentationComparisonReport).branches
    ? (report as Rq2RepresentationComparisonReport).branches
        .filter((b) => typeof b.coverage === 'number')
        .map((b) => ({ category: `${b.branch} (${b.analysis_role})`, value: b.coverage as number }))
    : [];

  return <BarWithCiChart data={bars} yLabel="Coverage" noDataReason="rq2_representation_comparison_report.json no tiene coverage real por rama todavia." />;
}

export default function CoverageTab() {
  return (
    <RunScopedJsonReport
      title="Coverage / Abstention"
      description="Ventanas elegibles, decididas, abstenidas y curva risk-coverage -- leido de confirmatory_future_analysis_report.json (coverage, risk_coverage). Obligatorio para el paper: ningun BA/F1 que use una regla con abstencion deberia mostrarse sin su coverage."
      noDataReason="confirmatory_future_analysis_report.json no existe todavia para este run."
      fetchReport={(paperRunId) => sciApi.confirmatoryFutureAnalysis(paperRunId)}
      renderCharts={(report, paperRunId) => (
        <>
          <div className="rounded border border-slate-800 bg-slate-950 px-3 py-2 text-xs">
            <span className="text-slate-500">coverage (real, EXECUTED):</span>{' '}
            <span className="font-mono text-slate-200">{coverageMethodValue(report) ?? 'N/A'}</span>
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">Curva risk-coverage</div>
            <RiskCoverageChart points={riskCoveragePoints(report)} noDataReason="risk_coverage no esta EXECUTED en el reporte para este run." />
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">Coverage por rama (RQ2, real, reutilizado)</div>
            <CoverageByBranch paperRunId={paperRunId} />
          </div>
          <div className="rounded border border-dashed border-slate-700 bg-slate-900/30 px-3 py-2 text-[11px] text-amber-400/80">
            MISSING_CANONICAL_METRIC -- coverage por dominio de evaluacion, coverage por unidad fisica y una
            distribucion de razones de abstencion no estan expuestos como series independientes en ningun reporte
            canonico todavia: risk_coverage no lleva una etiqueta de dominio, no existe coverage per-unit en ningun
            producer, y campaign_deviations no tiene una categoria "abstention" real. No se fabrican aqui.
          </div>
        </>
      )}
    />
  );
}
