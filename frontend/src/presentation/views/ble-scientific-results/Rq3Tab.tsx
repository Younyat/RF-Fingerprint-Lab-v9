import { BleScientificResultsApiService } from '../../../app/services/bleScientificResultsApi';
import HistogramChart from './charts/HistogramChart';
import RunScopedJsonReport from './RunScopedJsonReport';
import StatisticalInspectionPanel, { rq3PermutationRow } from './StatisticalInspectionPanel';

const sciApi = new BleScientificResultsApiService();

function permutationDraws(report: Record<string, unknown>): number[] {
  const method = report.rq3_within_device_permutation_test as { value?: { null_distribution?: number[] } } | undefined;
  const draws = method?.value?.null_distribution;
  return Array.isArray(draws) ? draws.filter((v) => typeof v === 'number') : [];
}

function observedStatistic(report: Record<string, unknown>): number | null {
  const method = report.rq3_within_device_permutation_test as { value?: { observed_statistic?: number } } | undefined;
  return typeof method?.value?.observed_statistic === 'number' ? method.value.observed_statistic : null;
}

export default function Rq3Tab() {
  return (
    <RunScopedJsonReport
      title="RQ3 -- Reset-associated displacement"
      description="delta_cycle, permutation test, pares RESET/CONTROL PRE/POST -- leido de confirmatory_future_analysis_report.json (rq3_within_device_permutation_test)."
      noDataReason="confirmatory_future_analysis_report.json no existe todavia para este run -- 0 pares reales RQ3 hasta la campana definitiva."
      fetchReport={(paperRunId) => sciApi.confirmatoryFutureAnalysis(paperRunId)}
      renderCharts={(report) => (
        <>
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">Inspeccion estadistica</div>
            <StatisticalInspectionPanel rows={[rq3PermutationRow(report)]} noDataReason="rq3_within_device_permutation_test.status != EXECUTED todavia." />
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">Distribucion nula de la prueba de permutacion (dentro de dispositivo)</div>
            <HistogramChart
              values={permutationDraws(report)}
              observedValue={observedStatistic(report)}
              xLabel="estadistico de permutacion"
              noDataReason="rq3_within_device_permutation_test.value.null_distribution no esta presente en el reporte."
            />
          </div>
          <div className="rounded border border-dashed border-slate-700 bg-slate-900/30 px-3 py-2 text-[11px] text-amber-400/80">
            MISSING_CANONICAL_METRIC -- el par PRE/POST por unidad, el efecto por unidad y el efecto agregado con CI
            no estan expuestos como series independientes en confirmatory_future_analysis_report.json todavia
            (StratifiedCrossoverTestResult solo persiste observed_statistic/p_value/n_permutations/exact). El
            componente PairedPrePostChart ya existe y se conectara aqui en cuanto el backend exponga esa serie real
            -- nunca se fabrica en el frontend.
          </div>
          <div className="text-[11px] text-slate-500">
            Tabla de pares invalidados: pendiente del mismo motivo -- ningun pair PRE/POST real existe todavia
            (0 pares como de esta version de la campana).
          </div>
        </>
      )}
    />
  );
}
