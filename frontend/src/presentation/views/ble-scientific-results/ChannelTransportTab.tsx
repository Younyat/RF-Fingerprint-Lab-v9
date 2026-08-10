import { useEffect, useState } from 'react';
import { BleScientificResultsApiService, ChannelTransportReport, NoDataResponse } from '../../../app/services/bleScientificResultsApi';
import BarWithCiChart, { BarWithCiDatum } from './charts/BarWithCiChart';
import ConfusionMatrixHeatmap from './charts/ConfusionMatrixHeatmap';
import MechanismDataNotice from './MechanismDataNotice';
import NoDataNotice from './NoDataNotice';
import { READ_ONLY_PICKER_CLASS, useReadOnlyRuns } from './useReadOnlyRuns';

const sciApi = new BleScientificResultsApiService();

function isNoData(report: ChannelTransportReport | NoDataResponse | null): report is NoDataResponse {
  return !!report && (report as NoDataResponse).status === 'NO_DATA';
}

function balancedAccuracyBars(report: ChannelTransportReport): BarWithCiDatum[] {
  return report.per_channel
    .filter((c) => typeof c.balanced_accuracy === 'number')
    .map((c) => ({ category: `CH${c.channel}`, value: c.balanced_accuracy as number }));
}

/** S1 (2026-08-11): CH37->CH38/39 bounded channel transport. Real renderer
 * + real backend (compute_channel_transport_report / get_channel_transport_report)
 * now exist -- MECHANISM=READY regardless of whether a real frozen bundle
 * has been scored per-channel yet (DATA stays NO_DATA until it has). Never
 * labeled "channel invariance". */
export default function ChannelTransportTab() {
  const { runs, paperRunId, setPaperRunId } = useReadOnlyRuns();
  const [report, setReport] = useState<ChannelTransportReport | NoDataResponse | null>(null);

  useEffect(() => {
    if (!paperRunId) { setReport(null); return; }
    sciApi.getChannelTransport(paperRunId).then(setReport).catch(() => setReport({ status: 'NO_DATA' }));
  }, [paperRunId]);

  return (
    <div className="space-y-4 p-4">
      <div>
        <div className="text-sm font-semibold text-slate-200">Engineering -- CH37 -&gt; CH38/39 transport</div>
        <div className="mt-1 text-xs text-slate-500">
          Mantenido explicitamente fuera de RQ1-RQ4. Modelo congelado (entrenado en CH37, sin reentrenar), misma regla
          de decision aplicada a CH38/39. Interpretacion permitida: "bounded channel transport" -- nunca "channel
          invariance".
        </div>
      </div>
      <MechanismDataNotice
        data={report && !isNoData(report) ? 'AVAILABLE' : 'NO_DATA'}
        dataReason="No existe todavia un bundle congelado real evaluado por canal (compute_channel_transport_report requiere predicciones ya puntuadas de UN solo modelo congelado)."
      />
      <div>
        <label className="mb-1 block text-xs text-slate-500">paper_run_id</label>
        <select className={READ_ONLY_PICKER_CLASS} value={paperRunId} onChange={(e) => setPaperRunId(e.target.value)}>
          <option value="">(seleccionar run)</option>
          {runs.map((run) => (<option key={run.paper_run_id} value={run.paper_run_id}>{run.paper_run_id}</option>))}
        </select>
      </div>
      {!paperRunId && <NoDataNotice reason="Ningun paper run seleccionado." />}
      {paperRunId && isNoData(report) && <NoDataNotice reason="channel_transport_report.json no existe todavia para este run." />}
      {paperRunId && report && !isNoData(report) && (
        <>
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">Balanced accuracy por canal</div>
            <BarWithCiChart data={balancedAccuracyBars(report)} yLabel="Balanced accuracy" noDataReason="Ningun canal tiene balanced_accuracy real en el reporte." />
          </div>
          {report.per_channel.map((c) => (
            <div key={c.channel}>
              <div className="mb-1 text-xs font-semibold text-slate-400">Matriz de confusion -- CH{c.channel}</div>
              <ConfusionMatrixHeatmap matrix={c.confusion_matrix} noDataReason={`Sin confusion_matrix real para CH${c.channel}.`} />
            </div>
          ))}
          <details className="rounded border border-slate-800 bg-slate-950">
            <summary className="cursor-pointer px-3 py-2 text-xs font-semibold text-slate-400">JSON crudo (fuente exacta persistida)</summary>
            <pre className="max-h-[70vh] overflow-auto p-3 text-[11px] text-slate-300">{JSON.stringify(report, null, 2)}</pre>
          </details>
        </>
      )}
    </div>
  );
}
