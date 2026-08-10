import NoDataNotice from './NoDataNotice';

export default function ChannelTransportTab() {
  return (
    <div className="space-y-4 p-4">
      <div>
        <div className="text-sm font-semibold text-slate-200">Engineering -- CH37 -&gt; CH38/39 transport</div>
        <div className="mt-1 text-xs text-slate-500">
          Mantenido explicitamente fuera de RQ1-RQ4. Nunca se etiqueta como "channel invariant" -- solo "bounded
          channel transport" si algun dia se ejecuta.
        </div>
      </div>
      <NoDataNotice reason="El analisis de transporte entre canales todavia no esta implementado (mecanismo no construido) -- ver docs/ble/PREPROCESSING.md y el plan de cierre." />
    </div>
  );
}
