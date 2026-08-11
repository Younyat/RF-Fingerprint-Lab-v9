import { BleScientificResultsApiService } from '../../../app/services/bleScientificResultsApi';
import BarWithCiChart, { BarWithCiDatum } from './charts/BarWithCiChart';
import EvidenceMaturityBadge from './EvidenceMaturityBadge';
import RunScopedJsonReport from './RunScopedJsonReport';

const sciApi = new BleScientificResultsApiService();

function lodoBars(report: Record<string, unknown>): BarWithCiDatum[] {
  const method = report.leave_one_device_out as { status?: string; value?: { excluded_device_id?: string; balanced_accuracy_value?: number | null }[] } | undefined;
  if (method?.status !== 'EXECUTED' || !Array.isArray(method.value)) return [];
  return method.value
    .filter((r) => typeof r.balanced_accuracy_value === 'number')
    .map((r) => ({ category: `sin ${r.excluded_device_id}`, value: r.balanced_accuracy_value as number }));
}

function seedVariabilityBars(report: Record<string, unknown>): BarWithCiDatum[] {
  const method = report.fixed_seed_variability as { status?: string; value?: { seed?: number; balanced_accuracy?: number }[] } | undefined;
  if (method?.status !== 'EXECUTED' || !Array.isArray(method.value)) return [];
  return method.value
    .filter((r) => typeof r.balanced_accuracy === 'number')
    .map((r) => ({ category: `seed=${r.seed}`, value: r.balanced_accuracy as number }));
}

export default function SensitivityTab() {
  return (
    <RunScopedJsonReport
      title="Sensitivity analyses"
      description="Leave-one-device-out, offset-retaining preprocessing, variabilidad por semilla fija -- leido de confirmatory_statistical_plan_report.json (VALIDATION_DRY_RUN). Nunca mezclado con resultados confirmatorios primarios (ver RQ1-4)."
      noDataReason="confirmatory_statistical_plan_report.json no existe todavia para este run."
      fetchReport={(paperRunId) => sciApi.confirmatoryStatisticalPlan(paperRunId)}
      renderCharts={(report) => (
        <>
          <div className="flex items-center gap-2 text-[11px] text-slate-500">
            <span>evidence maturity:</span><EvidenceMaturityBadge maturity="VALIDATION" />
            <span className="ml-2">-- nunca CONFIRMATORY, nunca mezclado con el resultado principal de RQ1-4.</span>
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">Leave-one-device-out</div>
            <BarWithCiChart data={lodoBars(report)} yLabel="Balanced accuracy" noDataReason="leave_one_device_out no esta EXECUTED en el reporte para este run." />
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">Variabilidad por semilla fija</div>
            <BarWithCiChart data={seedVariabilityBars(report)} yLabel="Balanced accuracy" noDataReason="fixed_seed_variability no esta EXECUTED en el reporte para este run." />
          </div>
          <div className="rounded border border-dashed border-slate-700 bg-slate-900/30 px-3 py-2 text-[11px] text-amber-400/80">
            MISSING_CANONICAL_METRIC -- el perfil offset-retaining-v1 (base_preprocessing_registry.py) existe como
            perfil de preprocesamiento real, pero ConfirmatoryStatisticalPlanReport no tiene todavia un MethodResult
            dedicado para una comparacion evaluada con ese perfil (solo leave_one_device_out y
            fixed_seed_variability existen hoy). No se fabrica aqui.
          </div>
        </>
      )}
    />
  );
}
