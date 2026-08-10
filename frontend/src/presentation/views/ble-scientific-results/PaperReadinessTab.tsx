import { useEffect, useState } from 'react';
import { BleScientificResultsApiService, PaperReadinessRow } from '../../../app/services/bleScientificResultsApi';
import { StatusBadge } from './NoDataNotice';

const sciApi = new BleScientificResultsApiService();

export default function PaperReadinessTab() {
  const [rows, setRows] = useState<PaperReadinessRow[] | null>(null);

  useEffect(() => {
    sciApi.paperReadiness().then(setRows).catch(() => setRows(null));
  }, []);

  return (
    <div className="space-y-4 p-4">
      <div>
        <div className="text-sm font-semibold text-slate-200">Paper readiness</div>
        <div className="mt-1 text-xs text-slate-500">
          Un elemento del manuscrito solo se marca disponible cuando su artefacto canonico real existe en disco; solo
          se marca confirmatorio cuando ademas hay un protocol freeze real (nunca a partir de un VALIDATION_DRY_RUN).
        </div>
      </div>

      {rows && (
        <table className="w-full text-left text-xs text-slate-300">
          <thead className="text-slate-500">
            <tr>
              <th className="py-1 pr-3">Paper element</th>
              <th className="py-1 pr-3">Status</th>
              <th className="py-1 pr-3">Required artifact</th>
              <th className="py-1 pr-3">Available</th>
              <th className="py-1 pr-3">Confirmatory</th>
              <th className="py-1 pr-3">Table</th>
              <th className="py-1 pr-3">Figure</th>
              <th className="py-1">Text</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.paper_element} className="border-t border-slate-800">
                <td className="py-1.5 pr-3 font-medium text-slate-200">{row.paper_element}</td>
                <td className="py-1.5 pr-3"><StatusBadge status={row.status} /></td>
                <td className="py-1.5 pr-3 font-mono text-[11px] text-slate-500">{row.required_artifact}</td>
                <td className="py-1.5 pr-3">{row.available ? 'YES' : 'NO'}</td>
                <td className="py-1.5 pr-3">{row.confirmatory ? 'YES' : 'NO'}</td>
                <td className="py-1.5 pr-3">{row.table_ready ? 'YES' : 'NO'}</td>
                <td className="py-1.5 pr-3">{row.figure_ready ? 'YES' : 'NO'}</td>
                <td className="py-1.5">{row.text_ready ? 'YES' : 'NO'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
