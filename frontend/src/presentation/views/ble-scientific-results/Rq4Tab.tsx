import { BleScientificResultsApiService, NoDataResponse } from '../../../app/services/bleScientificResultsApi';
import HistogramChart from './charts/HistogramChart';
import NonInferiorityChart, { NonInferiorityDatum } from './charts/NonInferiorityChart';
import EvidenceMaturityBadge, { EvidenceMaturity } from './EvidenceMaturityBadge';
import RunScopedJsonReport from './RunScopedJsonReport';
import StatisticalInspectionPanel, { holmSummary, nonInferiorityRow, rq4PairedComparisonRow } from './StatisticalInspectionPanel';

const sciApi = new BleScientificResultsApiService();

function isNoData(report: Record<string, unknown> | NoDataResponse): report is NoDataResponse {
  return (report as NoDataResponse).status === 'NO_DATA';
}

/** Same VALIDATION-fallback pattern as RQ3: prefer the real CONFIRMATORY
 * (FUTURE-gated) report when it exists, otherwise the non-FUTURE
 * VALIDATION dry-run -- same statistical engine either way, badge shows
 * which one actually backs the currently-displayed figures. */
async function fetchRq4Report(paperRunId: string): Promise<Record<string, unknown> | NoDataResponse> {
  const confirmatory = await sciApi.confirmatoryFutureAnalysis(paperRunId).catch(() => ({ status: 'NO_DATA' as const }));
  if (!isNoData(confirmatory)) return { ...confirmatory, _evidence_source: 'CONFIRMATORY' };
  const validation = await sciApi.confirmatoryStatisticalPlan(paperRunId).catch(() => ({ status: 'NO_DATA' as const }));
  if (!isNoData(validation)) return { ...validation, _evidence_source: 'VALIDATION' };
  return { status: 'NO_DATA' };
}

function pairedDifferences(report: Record<string, unknown>): number[] {
  const method = report.rq4_paired_comparison as { value?: { contrast?: { differences?: number[] } } } | undefined;
  const differences = method?.value?.contrast?.differences;
  return Array.isArray(differences) ? differences.filter((v) => typeof v === 'number') : [];
}

function observedStatistic(report: Record<string, unknown>): number | null {
  const method = report.rq4_paired_comparison as { value?: { randomization_test?: { observed_statistic?: number } } } | undefined;
  return typeof method?.value?.randomization_test?.observed_statistic === 'number' ? method.value.randomization_test.observed_statistic : null;
}

function nonInferiorityChartData(report: Record<string, unknown>): NonInferiorityDatum[] {
  const method = report.non_inferiority as { value?: { mean_difference?: number; ci_low?: number; margin?: number; non_inferior?: boolean } } | undefined;
  const value = method?.value;
  if (!value || typeof value.mean_difference !== 'number' || typeof value.ci_low !== 'number' || typeof value.margin !== 'number') return [];
  return [{ label: 'RQ4 (agregado)', meanDifference: value.mean_difference, ciLow: value.ci_low, margin: value.margin, nonInferior: value.non_inferior === true }];
}

export default function Rq4Tab() {
  return (
    <RunScopedJsonReport
      title="RQ4 -- Packet-content dependence"
      description="FULL_BURST / ADVA_EXCLUDED / PRE_PDU (analytical_region) vs ORIGINAL / CONTROLLED_VARIANT (packet_condition), comparacion pareada y non-inferiority -- leido de confirmatory_future_analysis_report.json (rq4_paired_comparison, non_inferiority)."
      noDataReason="Ni confirmatory_future_analysis_report.json ni confirmatory_statistical_plan_report.json existen todavia para este run."
      fetchReport={fetchRq4Report}
      renderCharts={(report) => (
        <>
          <div className="flex items-center gap-2 text-[11px] text-slate-500">
            <span>fuente de evidencia:</span><EvidenceMaturityBadge maturity={(report._evidence_source as EvidenceMaturity) ?? 'VALIDATION'} />
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">Inspeccion estadistica</div>
            <StatisticalInspectionPanel
              rows={[rq4PairedComparisonRow(report), nonInferiorityRow(report)]}
              holm={holmSummary(report)}
              noDataReason="rq4_paired_comparison/non_inferiority.status != EXECUTED todavia."
            />
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">Diferencias pareadas (nuevo - referencia)</div>
            <HistogramChart
              values={pairedDifferences(report)}
              observedValue={observedStatistic(report)}
              xLabel="diferencia pareada"
              noDataReason="rq4_paired_comparison.value.contrast.differences no esta presente en el reporte."
            />
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">Non-inferiority -- estimacion, CI unilateral y frontera de decision (-margin)</div>
            <NonInferiorityChart data={nonInferiorityChartData(report)} noDataReason="non_inferiority.value no esta presente en el reporte." />
          </div>
          <div className="rounded border border-dashed border-slate-700 bg-slate-900/30 px-3 py-2 text-[11px] text-amber-400/80">
            MISSING_CANONICAL_METRIC -- el desglose por region analitica (FULL_BURST / ADVA_EXCLUDED / PRE_PDU) y por
            condicion de paquete todavia no esta expuesto como serie independiente en
            confirmatory_future_analysis_report.json, solo el contraste agregado. No se fabrica en el frontend.
          </div>
        </>
      )}
    />
  );
}
