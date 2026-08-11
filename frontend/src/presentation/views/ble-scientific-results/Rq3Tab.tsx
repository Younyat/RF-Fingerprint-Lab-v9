import { BleScientificResultsApiService, NoDataResponse, Rq3Pair } from '../../../app/services/bleScientificResultsApi';
import EvidenceMaturityBadge, { EvidenceMaturity } from './EvidenceMaturityBadge';
import HistogramChart from './charts/HistogramChart';
import RunScopedJsonReport from './RunScopedJsonReport';
import StatisticalInspectionPanel, { rq3PermutationRow } from './StatisticalInspectionPanel';

const sciApi = new BleScientificResultsApiService();

function isNoData(report: Record<string, unknown> | NoDataResponse): report is NoDataResponse {
  return (report as NoDataResponse).status === 'NO_DATA';
}

function permutationDraws(report: Record<string, unknown>): number[] {
  const method = report.rq3_within_device_permutation_test as { value?: { null_distribution?: number[] } } | undefined;
  const draws = method?.value?.null_distribution;
  return Array.isArray(draws) ? draws.filter((v) => typeof v === 'number') : [];
}

function observedStatistic(report: Record<string, unknown>): number | null {
  const method = report.rq3_within_device_permutation_test as { value?: { observed_statistic?: number } } | undefined;
  return typeof method?.value?.observed_statistic === 'number' ? method.value.observed_statistic : null;
}

function pairs(report: Record<string, unknown>): Rq3Pair[] {
  const value = report.rq3_pairs;
  return Array.isArray(value) ? (value as Rq3Pair[]) : [];
}

/** RQ3 reads whichever real confirmatory statistical report exists,
 * preferring the FUTURE-gated CONFIRMATORY one (confirmatory_future_
 * analysis_report.json) only when it has actually been produced (requires
 * a real protocol freeze + opened FUTURE holdout -- never triggered by
 * this dashboard), and otherwise falling back to the non-FUTURE VALIDATION
 * dry-run (confirmatory_statistical_plan_report.json) -- the SAME
 * statistical engine, just never touching FUTURE_TEST. Every field is
 * tagged with which source backed it so a VALIDATION figure can never be
 * mistaken for a CONFIRMATORY one. */
async function fetchRq3Report(paperRunId: string): Promise<Record<string, unknown> | NoDataResponse> {
  const confirmatory = await sciApi.confirmatoryFutureAnalysis(paperRunId).catch(() => ({ status: 'NO_DATA' as const }));
  if (!isNoData(confirmatory)) return { ...confirmatory, _evidence_source: 'CONFIRMATORY' };
  const validation = await sciApi.confirmatoryStatisticalPlan(paperRunId).catch(() => ({ status: 'NO_DATA' as const }));
  if (!isNoData(validation)) return { ...validation, _evidence_source: 'VALIDATION' };
  return { status: 'NO_DATA' };
}

export default function Rq3Tab() {
  return (
    <RunScopedJsonReport
      title="RQ3 -- Reset-associated displacement"
      description="delta_cycle, permutation test, pares RESET/CONTROL PRE/POST -- lee confirmatory_future_analysis_report.json (CONFIRMATORY) cuando existe, o confirmatory_statistical_plan_report.json (VALIDATION, no toca FUTURE) en caso contrario -- el mismo motor estadistico, badge de madurez segun la fuente real."
      noDataReason="Ni confirmatory_future_analysis_report.json ni confirmatory_statistical_plan_report.json existen todavia para este run."
      fetchReport={fetchRq3Report}
      renderCharts={(report) => {
        const source = (report._evidence_source as EvidenceMaturity) ?? 'VALIDATION';
        const realPairs = pairs(report);
        const invalidPairs = realPairs.filter((p) => !p.valid);
        return (
          <>
            <div className="flex items-center gap-2 text-[11px] text-slate-500">
              <span>fuente de evidencia:</span><EvidenceMaturityBadge maturity={source} />
            </div>
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
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-400">Registro real de pares PRE/POST (identidad -- build_pre_post_pairs, nunca un valor inventado)</div>
              {realPairs.length === 0 ? (
                <div className="rounded border border-dashed border-slate-700 bg-slate-900/40 px-4 py-6 text-center text-xs text-slate-500">
                  0 pares reales todavia (0/0 capturas declaran day_id/intervention_arm/pre_or_post a la vez -- esperado hasta la campana definitiva).
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[760px] border-collapse text-[11px]">
                    <thead>
                      <tr className="border-b border-slate-800 text-left text-slate-500">
                        <th className="py-1 pr-2">unidad</th><th className="py-1 pr-2">dia</th><th className="py-1 pr-2">arm</th>
                        <th className="py-1 pr-2">pre_capture_id</th><th className="py-1 pr-2">post_capture_id</th>
                        <th className="py-1 pr-2">valido</th><th className="py-1 pr-2">razon de invalidacion</th>
                      </tr>
                    </thead>
                    <tbody>
                      {realPairs.map((p, i) => (
                        <tr key={i} className={`border-b border-slate-900 ${p.valid ? 'text-slate-300' : 'text-red-400/80'}`}>
                          <td className="py-1.5 pr-2">{p.physical_unit_id}</td><td className="py-1.5 pr-2">{p.day_id}</td><td className="py-1.5 pr-2">{p.intervention_arm}</td>
                          <td className="py-1.5 pr-2 font-mono">{p.pre_capture_id}</td><td className="py-1.5 pr-2 font-mono">{p.post_capture_id}</td>
                          <td className="py-1.5 pr-2">{p.valid ? 'yes' : 'no'}</td><td className="py-1.5 pr-2">{p.invalidation_reason ?? '-'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {invalidPairs.length > 0 && (
                    <div className="mt-1 text-[11px] text-slate-500">{invalidPairs.length} de {realPairs.length} pares invalidos (ver razon en la tabla).</div>
                  )}
                </div>
              )}
            </div>
            <div className="rounded border border-dashed border-slate-700 bg-slate-900/30 px-3 py-2 text-[11px] text-amber-400/80">
              MISSING_CANONICAL_METRIC -- el par PRE/POST por unidad SOLO tiene identidad real arriba (unidad/dia/arm/
              capture_ids/validez), nunca un valor numerico PRE/POST ni D: ninguna funcion en el codebase calcula
              todavia una puntuacion por captura para alimentar ese valor (confirmado por revision directa de
              PrePostPair y de confirmatory_analysis_runner.py). Inventar ese numero aqui seria exactamente la
              "nueva metrica para completar una grafica" que esta prohibida -- PairedPrePostChart se conectara en
              cuanto exista un producer real.
            </div>
          </>
        );
      }}
    />
  );
}
