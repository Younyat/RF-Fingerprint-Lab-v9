import { BleScientificResultsApiService } from '../../../app/services/bleScientificResultsApi';
import BarWithCiChart, { BarWithCiDatum } from './charts/BarWithCiChart';
import HistogramChart from './charts/HistogramChart';
import RunScopedJsonReport from './RunScopedJsonReport';

const sciApi = new BleScientificResultsApiService();

function pairedDifferences(report: Record<string, unknown>): number[] {
  const method = report.rq4_paired_comparison as { value?: { contrast?: { differences?: number[] } } } | undefined;
  const differences = method?.value?.contrast?.differences;
  return Array.isArray(differences) ? differences.filter((v) => typeof v === 'number') : [];
}

function observedStatistic(report: Record<string, unknown>): number | null {
  const method = report.rq4_paired_comparison as { value?: { randomization_test?: { observed_statistic?: number } } } | undefined;
  return typeof method?.value?.randomization_test?.observed_statistic === 'number' ? method.value.randomization_test.observed_statistic : null;
}

function nonInferiorityBar(report: Record<string, unknown>): BarWithCiDatum[] {
  const method = report.non_inferiority as { value?: { mean_difference?: number; ci_low?: number; margin?: number } } | undefined;
  const value = method?.value;
  if (!value || typeof value.mean_difference !== 'number') return [];
  return [{ category: 'diferencia (nuevo - referencia)', value: value.mean_difference, ciLow: value.ci_low ?? null, ciHigh: null }];
}

export default function Rq4Tab() {
  return (
    <RunScopedJsonReport
      title="RQ4 -- Packet-content dependence"
      description="FULL_BURST / ADVA_EXCLUDED / PRE_PDU (analytical_region) vs ORIGINAL / CONTROLLED_VARIANT (packet_condition), comparacion pareada y non-inferiority -- leido de confirmatory_future_analysis_report.json (rq4_paired_comparison, non_inferiority)."
      noDataReason="confirmatory_future_analysis_report.json no existe todavia para este run -- pendiente de CONFIRMATORY_FUTURE."
      fetchReport={(paperRunId) => sciApi.confirmatoryFutureAnalysis(paperRunId)}
      renderCharts={(report) => (
        <>
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
            <div className="mb-1 text-xs font-semibold text-slate-400">Estimacion de non-inferiority (margen unilateral)</div>
            <BarWithCiChart data={nonInferiorityBar(report)} yLabel="diferencia media" noDataReason="non_inferiority.value no esta presente en el reporte." />
          </div>
          <div className="text-[11px] text-slate-500">
            La comparacion por region (FULL_BURST / ADVA_EXCLUDED / PRE_PDU) todavia no esta expuesta como serie independiente en confirmatory_future_analysis_report.json -- solo el contraste agregado.
          </div>
        </>
      )}
    />
  );
}
