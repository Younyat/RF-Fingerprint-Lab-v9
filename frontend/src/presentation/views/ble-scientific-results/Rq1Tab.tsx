import { BleScientificResultsApiService } from '../../../app/services/bleScientificResultsApi';
import BarWithCiChart, { BarWithCiDatum } from './charts/BarWithCiChart';
import ConfusionMatrixHeatmap from './charts/ConfusionMatrixHeatmap';
import RunScopedJsonReport from './RunScopedJsonReport';

const sciApi = new BleScientificResultsApiService();

function domainBars(report: Record<string, unknown>): BarWithCiDatum[] {
  const bars: BarWithCiDatum[] = [];
  if (typeof report.ba_window === 'number') bars.push({ category: 'capture-dependent (BA_window)', value: report.ba_window });
  if (typeof report.ba_capture === 'number') bars.push({ category: 'capture-disjoint (BA_capture)', value: report.ba_capture });
  if (typeof report.ba_future === 'number') bars.push({ category: `future (${String(report.ba_future_status ?? '')})`, value: report.ba_future });
  return bars;
}

function perUnitRecallBars(report: Record<string, unknown>): BarWithCiDatum[] {
  const perUnit = report.per_unit_recall as Record<string, { recall?: number | null }> | null | undefined;
  if (!perUnit) return [];
  return Object.entries(perUnit)
    .filter(([, v]) => typeof v?.recall === 'number')
    .map(([unitId, v]) => ({ category: unitId, value: v.recall as number }));
}

export default function Rq1Tab() {
  return (
    <RunScopedJsonReport
      title="RQ1 -- Acquisition dependence"
      description="BA_window / BA_capture / BA_future, deltas, cobertura -- leidos directamente de rq1_acquisition_dependence_report.json (persist_rq1_acquisition_dependence_report). No se recalcula nada aqui."
      noDataReason="rq1_acquisition_dependence_report.json no existe todavia para este run -- pendiente de CONFIRMATORY_FUTURE."
      fetchReport={(paperRunId) => sciApi.rq1AcquisitionDependence(paperRunId)}
      renderCharts={(report) => (
        <>
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">BA por dominio de evaluacion</div>
            <BarWithCiChart data={domainBars(report)} yLabel="Balanced accuracy" noDataReason="ba_window/ba_capture no estan presentes en el reporte." />
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">Recall por unidad fisica</div>
            <BarWithCiChart data={perUnitRecallBars(report)} yLabel="Recall" noDataReason="per_unit_recall no esta presente en el reporte." />
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-400">Matriz de confusion -- capture-disjoint</div>
              <ConfusionMatrixHeatmap matrix={report.confusion_matrix_capture as Record<string, Record<string, number>> | null} noDataReason="confusion_matrix_capture no esta presente en el reporte." />
            </div>
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-400">Matriz de confusion -- future</div>
              <ConfusionMatrixHeatmap matrix={report.confusion_matrix_future as Record<string, Record<string, number>> | null} noDataReason="confusion_matrix_future no esta presente en el reporte." />
            </div>
          </div>
        </>
      )}
    />
  );
}
