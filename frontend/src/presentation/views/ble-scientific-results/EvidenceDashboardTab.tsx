import { useCallback, useEffect, useState } from 'react';
import {
  BleScientificResultsApiService,
  EvidenceDashboardClosedSet,
  EvidenceDashboardPerUnitRun,
  EvidenceDashboardSummary,
  Rq2BranchResult,
} from '../../../app/services/bleScientificResultsApi';
import BarWithCiChart, { BarWithCiDatum } from './charts/BarWithCiChart';
import ConfusionMatrixHeatmap from './charts/ConfusionMatrixHeatmap';
import NoDataNotice, { StatusBadge } from './NoDataNotice';

const sciApi = new BleScientificResultsApiService();

function domainBars(rq1: EvidenceDashboardClosedSet['rq1']): BarWithCiDatum[] {
  if (!rq1) return [];
  const bars: BarWithCiDatum[] = [];
  if (typeof rq1.ba_window === 'number') bars.push({ category: 'BA_window (intra-session)', value: rq1.ba_window });
  if (typeof rq1.ba_capture === 'number') bars.push({ category: 'BA_capture (capture-disjoint)', value: rq1.ba_capture });
  if (typeof rq1.ba_future === 'number') bars.push({ category: 'BA_future', value: rq1.ba_future });
  return bars;
}

function branchBars(rq2: EvidenceDashboardClosedSet['rq2'], field: 'balanced_accuracy' | 'macro_f1'): BarWithCiDatum[] {
  const branches = (rq2?.branches as Rq2BranchResult[] | undefined) ?? [];
  return branches
    .filter((b) => typeof b[field] === 'number')
    .map((b) => ({ category: `${b.branch} (${b.analysis_role})`, value: b[field] as number }));
}

function Provenance({ items }: { items: (string | null | undefined)[] }) {
  const parts = items.filter((v): v is string => !!v);
  if (parts.length === 0) return null;
  return <div className="mt-1 font-mono text-[10.5px] text-slate-500">{parts.join(' · ')}</div>;
}

function ClosedSetSection({ closedSet }: { closedSet: EvidenceDashboardClosedSet | null }) {
  if (!closedSet) {
    return <NoDataNotice reason="Ningun paper_run con scientific_task=MULTI_DEVICE_CLASSIFICATION existe todavia." />;
  }
  const primaryTest = closedSet.primary_test;
  return (
    <div className="space-y-4">
      <Provenance items={[`paper_run_id=${closedSet.paper_run_id}`, `dataset_id=${closedSet.dataset_id}`, `dataset_version=${closedSet.dataset_version}`]} />

      <div>
        <div className="mb-1 text-xs font-semibold text-slate-400">RQ1 -- BA por dominio de evaluacion</div>
        <BarWithCiChart data={domainBars(closedSet.rq1)} yLabel="Balanced accuracy" noDataReason="rq1_acquisition_dependence_report.json no existe todavia para este run." />
        {closedSet.rq1 && typeof closedSet.rq1.delta_dependence === 'number' && (
          <div className="mt-1 text-[11px] text-slate-500">
            delta_dependence = <span className="font-mono text-slate-300">{closedSet.rq1.delta_dependence.toFixed(4)}</span>
            {' · '}ba_future_status = <span className="font-mono text-slate-300">{closedSet.rq1.ba_future_status}</span>
          </div>
        )}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <div className="mb-1 text-xs font-semibold text-slate-400">RQ2 -- balanced accuracy por rama (VALIDATION)</div>
          <BarWithCiChart data={branchBars(closedSet.rq2, 'balanced_accuracy')} yLabel="Balanced accuracy" noDataReason="rq2_representation_comparison_report.json no existe todavia para este run." />
        </div>
        <div>
          <div className="mb-1 text-xs font-semibold text-slate-400">RQ2 -- macro-F1 por rama (VALIDATION)</div>
          <BarWithCiChart data={branchBars(closedSet.rq2, 'macro_f1')} yLabel="Macro-F1" noDataReason="rq2_representation_comparison_report.json no existe todavia para este run." />
        </div>
      </div>

      {closedSet.primary_branch && (
        <div className="text-[11px] text-slate-500">
          STUDY PRIMARY BRANCH = <span className="font-mono text-slate-300">{closedSet.primary_branch}</span>
          {' · '}training_run_id = <span className="font-mono text-slate-300">{closedSet.primary_training_run_id}</span>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <div className="mb-1 text-xs font-semibold text-slate-400">Matriz de confusion -- VALIDATION (capture-disjoint)</div>
          <ConfusionMatrixHeatmap matrix={closedSet.rq1?.confusion_matrix_capture ?? null} noDataReason="confusion_matrix_capture no esta presente en el reporte." />
        </div>
        <div>
          <div className="mb-1 text-xs font-semibold text-slate-400">Matriz de confusion -- TEST (branch primaria, held-out)</div>
          <ConfusionMatrixHeatmap matrix={primaryTest?.confusion_matrix ?? null} noDataReason="El training run de la branch primaria todavia no tiene TEST evaluado." />
        </div>
      </div>

      {primaryTest && (
        <div className="text-[11px] text-slate-500">
          PRIMARY TEST: BA = <span className="font-mono text-slate-300">{primaryTest.balanced_accuracy?.toFixed(4) ?? '—'}</span>
          {' · '}macro-F1 = <span className="font-mono text-slate-300">{primaryTest.macro_f1?.toFixed(4) ?? '—'}</span>
          {' · '}accuracy = <span className="font-mono text-slate-300">{primaryTest.accuracy?.toFixed(4) ?? '—'}</span>
        </div>
      )}
      {primaryTest?.recall_per_class && (
        <div>
          <div className="mb-1 text-xs font-semibold text-slate-400">Recall por unidad (TEST, branch primaria)</div>
          <BarWithCiChart
            data={Object.entries(primaryTest.recall_per_class).map(([unit, recall]) => ({ category: unit, value: recall }))}
            yLabel="Recall" noDataReason="recall_per_class no esta presente en la evaluacion TEST."
          />
        </div>
      )}
    </div>
  );
}

function PerUnitAuxiliarySection({ runs }: { runs: EvidenceDashboardPerUnitRun[] }) {
  if (runs.length === 0) {
    return <NoDataNotice reason="Ningun paper_run con scientific_task=TARGET_VS_BACKGROUND existe todavia." />;
  }
  return (
    <div className="overflow-x-auto rounded border border-slate-800">
      <table className="min-w-full text-xs">
        <thead className="bg-slate-950 text-[10.5px] uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-3 py-2 text-left">dataset_id</th>
            <th className="px-3 py-2 text-right">BA_window</th>
            <th className="px-3 py-2 text-right">BA_capture</th>
            <th className="px-3 py-2 text-right">delta_dependence</th>
            <th className="px-3 py-2 text-left">primary branch</th>
            <th className="px-3 py-2 text-right">primary BA (VALIDATION)</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800">
          {runs.map((run) => {
            const branches = (run.rq2?.branches as Rq2BranchResult[] | undefined) ?? [];
            const primary = branches.find((b) => b.analysis_role === 'PRIMARY');
            return (
              <tr key={run.paper_run_id}>
                <td className="px-3 py-2 font-mono text-slate-300">{run.dataset_id}</td>
                <td className="px-3 py-2 text-right font-mono text-slate-300">{run.rq1?.ba_window?.toFixed(4) ?? '—'}</td>
                <td className="px-3 py-2 text-right font-mono text-slate-300">{run.rq1?.ba_capture?.toFixed(4) ?? '—'}</td>
                <td className="px-3 py-2 text-right font-mono text-slate-300">{run.rq1?.delta_dependence?.toFixed(4) ?? '—'}</td>
                <td className="px-3 py-2 font-mono text-slate-300">{primary?.branch ?? '—'}</td>
                <td className="px-3 py-2 text-right font-mono text-slate-300">{primary?.balanced_accuracy?.toFixed(4) ?? '—'}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Rq3Section({ rq3 }: { rq3: EvidenceDashboardSummary['rq3'] }) {
  const decision = rq3.sample_size_decision;
  const progress = rq3.campaign_progress;
  return (
    <div className="space-y-3">
      {decision ? (
        <div className="text-[11px] text-slate-500">
          rationale = <span className="font-mono text-slate-300">{decision.rationale}</span>
          {' · '}decided_by = <span className="font-mono text-slate-300">{decision.decided_by ?? '—'}</span>
          {' · '}decided_at = <span className="font-mono text-slate-300">{decision.decided_at}</span>
          <pre className="mt-1 overflow-auto rounded border border-slate-800 bg-slate-950 p-2 text-[11px] text-slate-300">
            {JSON.stringify(decision.selected_value, null, 2)}
          </pre>
        </div>
      ) : (
        <NoDataNotice reason="rq3_sample_size no ha sido registrado todavia via record_scientist_decision()." />
      )}
      <div className="text-[11px] text-slate-500">
        Progreso real de campana: <span className="font-mono text-slate-300">{progress.captures_with_rq3_metadata}</span> de{' '}
        <span className="font-mono text-slate-300">{progress.total_captures}</span> capturas totales tienen day_id/pre_or_post/intervention_arm declarados.
      </div>
      {Object.keys(progress.declared_by_unit).length > 0 && (
        <div className="overflow-x-auto rounded border border-slate-800">
          <table className="min-w-full text-xs">
            <thead className="bg-slate-950 text-[10.5px] uppercase tracking-wide text-slate-500">
              <tr><th className="px-3 py-2 text-left">unit</th><th className="px-3 py-2 text-right">RESET declarados</th><th className="px-3 py-2 text-right">CONTROL declarados</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {Object.entries(progress.declared_by_unit).map(([unit, counts]) => (
                <tr key={unit}>
                  <td className="px-3 py-2 font-mono text-slate-300">{unit}</td>
                  <td className="px-3 py-2 text-right font-mono text-slate-300">{counts.RESET}</td>
                  <td className="px-3 py-2 text-right font-mono text-slate-300">{counts.CONTROL}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Rq4Section({ rq4 }: { rq4: EvidenceDashboardSummary['rq4'] }) {
  return (
    <div className="space-y-3">
      <div className="text-[11px] text-slate-500">status = <StatusBadge status={rq4.status} /></div>
      {rq4.physical_units.length === 0 ? (
        <NoDataNotice reason="Ningun physical_unit registrado todavia." />
      ) : (
        <div className="overflow-x-auto rounded border border-slate-800">
          <table className="min-w-full text-xs">
            <thead className="bg-slate-950 text-[10.5px] uppercase tracking-wide text-slate-500">
              <tr><th className="px-3 py-2 text-left">physical_unit_id</th><th className="px-3 py-2 text-left">eligibility</th><th className="px-3 py-2 text-left">reason</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {rq4.physical_units.map((unit) => (
                <tr key={unit.physical_unit_id}>
                  <td className="px-3 py-2 font-mono text-slate-300">{unit.physical_unit_id}</td>
                  <td className="px-3 py-2"><StatusBadge status={unit.rq4_eligibility} /></td>
                  <td className="px-3 py-2 text-slate-400">{unit.rq4_eligibility_reason ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** Real, in-platform paper-support dashboard: aggregates already-persisted
 * RQ1/RQ2 reports (closed-set + per-unit auxiliary runs), the frozen
 * rq3_sample_size decision + live RQ3 campaign progress, and RQ4 per-unit
 * eligibility. Computes nothing -- reads GET /evidence-dashboard, a plain
 * synchronous cross-reference of already-real getters (see
 * ScientificResultsRepository.get_evidence_dashboard_summary). Not
 * run-scoped (unlike RunScopedJsonReport) since it spans every run at
 * once; "Refrescar" simply re-fetches. */
export default function EvidenceDashboardTab() {
  const [data, setData] = useState<EvidenceDashboardSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    sciApi.evidenceDashboardSummary()
      .then(setData)
      .catch(() => setError('No se pudo cargar el dashboard de evidencia.'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-6 p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-sm font-semibold text-slate-200">Evidence Dashboard -- soporte real para el paper</div>
          <div className="mt-1 text-xs text-slate-500">
            RQ1/RQ2 closed-set + 4 runs auxiliares por unidad, RQ3 (tamano muestral congelado + progreso real de campana), RQ4 (elegibilidad por unidad).
            Cada seccion lee directamente su artefacto persistido -- nada se recalcula aqui.
          </div>
        </div>
        <button
          type="button" onClick={load} disabled={loading}
          className="shrink-0 rounded border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs font-semibold text-slate-300 hover:bg-slate-800 disabled:opacity-50"
        >
          {loading ? 'Actualizando…' : 'Refrescar'}
        </button>
      </div>

      {error && <NoDataNotice reason={error} />}

      {data && (
        <>
          <Provenance items={[`generated_at=${data.generated_at}`, `git_sha=${data.git_sha}`, `protocol_id=${data.protocol_id}`, `contract_sha256=${data.contract_sha256}`]} />

          <section>
            <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-400">RQ1 / RQ2 -- Closed-set (4-unit, MULTI_DEVICE_CLASSIFICATION)</h3>
            <ClosedSetSection closedSet={data.closed_set} />
          </section>

          <section>
            <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-400">Per-unit auxiliary analysis (TARGET_VS_BACKGROUND)</h3>
            <PerUnitAuxiliarySection runs={data.per_unit_auxiliary} />
          </section>

          <section>
            <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-400">RQ3 -- Reset-associated displacement</h3>
            <Rq3Section rq3={data.rq3} />
          </section>

          <section>
            <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-400">RQ4 -- Packet-content dependence</h3>
            <Rq4Section rq4={data.rq4} />
          </section>
        </>
      )}
    </div>
  );
}
