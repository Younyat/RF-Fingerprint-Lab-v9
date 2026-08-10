import { useEffect, useState } from 'react';
import { BleScientificResultsApiService, NoDataResponse, OfflineNearliveReport } from '../../../app/services/bleScientificResultsApi';
import MechanismDataNotice from './MechanismDataNotice';
import NoDataNotice from './NoDataNotice';
import { READ_ONLY_PICKER_CLASS, useReadOnlyRuns } from './useReadOnlyRuns';

const sciApi = new BleScientificResultsApiService();

function isNoData(report: OfflineNearliveReport | NoDataResponse | null): report is NoDataResponse {
  return !!report && (report as NoDataResponse).status === 'NO_DATA';
}

/** S2 (2026-08-11): offline vs near-live. The join key that would match a
 * near-live decision to "the same retained sample interval" as an offline
 * one does not exist yet (near-live inference does not go through the
 * dataset/example pipeline) -- this is a real, disclosed methodological
 * gap, not something this pass invents. Renderer + backend
 * (compute_offline_nearlive_report / get_offline_nearlive_report) are
 * real and tested (MECHANISM=READY); computational fields default to
 * NOT_MEASURED, never 0. */
export default function OnlineEquivalenceTab() {
  const { runs, paperRunId, setPaperRunId } = useReadOnlyRuns();
  const [report, setReport] = useState<OfflineNearliveReport | NoDataResponse | null>(null);

  useEffect(() => {
    if (!paperRunId) { setReport(null); return; }
    sciApi.getOfflineNearlive(paperRunId).then(setReport).catch(() => setReport({ status: 'NO_DATA' }));
  }, [paperRunId]);

  const analytical = report && !isNoData(report) ? report.analytical_agreement : null;
  const computational = report && !isNoData(report) ? report.computational_behavior : null;

  return (
    <div className="space-y-4 p-4">
      <div>
        <div className="text-sm font-semibold text-slate-200">Engineering -- Offline vs near-live</div>
        <div className="mt-1 text-xs text-slate-500">
          Dos clases separadas: (A) acuerdo analitico (conteo de decisiones, acuerdo de clase, acuerdo de score,
          acuerdo de abstencion) y (B) comportamiento computacional (latencia, throughput, drops). Nunca 0 cuando no
          este medido -- NOT_MEASURED explicito.
        </div>
      </div>
      <MechanismDataNotice
        data={analytical ? 'AVAILABLE' : 'NO_DATA'}
        dataReason="No existe mecanismo establecido para emparejar una decision near-live con el mismo intervalo de muestras que una decision offline -- ver pairing_note del reporte. El agregador solo calcula sobre pares ya emparejados por el llamador; ninguno existe todavia."
      />
      <div>
        <label className="mb-1 block text-xs text-slate-500">paper_run_id</label>
        <select className={READ_ONLY_PICKER_CLASS} value={paperRunId} onChange={(e) => setPaperRunId(e.target.value)}>
          <option value="">(seleccionar run)</option>
          {runs.map((run) => (<option key={run.paper_run_id} value={run.paper_run_id}>{run.paper_run_id}</option>))}
        </select>
      </div>
      {!paperRunId && <NoDataNotice reason="Ningun paper run seleccionado." />}
      {paperRunId && isNoData(report) && <NoDataNotice reason="offline_nearlive_report.json no existe todavia para este run." />}
      {paperRunId && report && !isNoData(report) && (
        <>
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">Acuerdo analitico</div>
            {analytical ? (
              <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
                {Object.entries(analytical).map(([key, value]) => (
                  <div key={key} className="rounded border border-slate-800 bg-slate-950 p-2">
                    <div className="text-slate-500">{key}</div>
                    <div className="font-mono text-slate-200">{value ?? 'NOT_MEASURED'}</div>
                  </div>
                ))}
              </div>
            ) : (
              <NoDataNotice reason={report.pairing_note} />
            )}
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">Comportamiento computacional</div>
            <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
              {Object.entries(computational ?? {}).map(([key, value]) => (
                <div key={key} className="rounded border border-slate-800 bg-slate-950 p-2">
                  <div className="text-slate-500">{key}</div>
                  <div className="font-mono text-slate-200">{String(value)}</div>
                </div>
              ))}
            </div>
          </div>
          <details className="rounded border border-slate-800 bg-slate-950">
            <summary className="cursor-pointer px-3 py-2 text-xs font-semibold text-slate-400">JSON crudo (fuente exacta persistida)</summary>
            <pre className="max-h-[70vh] overflow-auto p-3 text-[11px] text-slate-300">{JSON.stringify(report, null, 2)}</pre>
          </details>
        </>
      )}
    </div>
  );
}
