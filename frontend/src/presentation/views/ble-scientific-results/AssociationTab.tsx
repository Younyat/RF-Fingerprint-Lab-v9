import { useEffect, useState } from 'react';
import { AssociationPolicyStatusResponse, BleScientificResultsApiService } from '../../../app/services/bleScientificResultsApi';
import NoDataNotice, { StatusBadge } from './NoDataNotice';

const sciApi = new BleScientificResultsApiService();

export default function AssociationTab() {
  const [status, setStatus] = useState<AssociationPolicyStatusResponse | null>(null);

  useEffect(() => {
    sciApi.associationPolicyStatus().then(setStatus).catch(() => setStatus(null));
  }, []);

  return (
    <div className="space-y-4 p-4">
      <div>
        <div className="text-sm font-semibold text-slate-200">Association calibration</div>
        <div className="mt-1 text-xs text-slate-500">
          Estado real de find_frozen_association_policy() -- fail-closed. Nunca se recalibra desde aqui.
        </div>
      </div>

      {status && (
        <div className="flex items-center gap-2 text-sm">
          <span className="text-slate-400">Policy state:</span>
          <StatusBadge status={status.status} />
        </div>
      )}

      {status?.status === 'NONE' && (
        <NoDataNotice reason="Ningun intento de calibracion ha producido todavia una policy FROZEN -- estado real, honesto (0 STRONG), no un error." />
      )}

      {status?.status === 'FROZEN' && status.policy && (
        <pre className="max-h-[60vh] overflow-auto rounded border border-slate-800 bg-slate-950 p-3 text-[11px] text-slate-300">
          {JSON.stringify(status.policy, null, 2)}
        </pre>
      )}
    </div>
  );
}
