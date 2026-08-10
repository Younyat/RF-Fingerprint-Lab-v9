import NoDataNotice from './NoDataNotice';

export default function ProvenanceTab() {
  return (
    <div className="space-y-4 p-4">
      <div>
        <div className="text-sm font-semibold text-slate-200">Provenance</div>
        <div className="mt-1 text-xs text-slate-500">
          decision -&gt; window -&gt; bursts -&gt; examples -&gt; PDU recuperado -&gt; sample_start/end -&gt; capture_id -&gt; I/Q
          SHA-256, mas dataset/split manifest, perfil de preprocesamiento, bundle de modelo, protocol_version,
          contract_sha256 y git SHA.
        </div>
      </div>
      <NoDataNotice reason="No existe todavia un endpoint de reconstruccion de cadena de provenance ni una decision real que reconstruir -- los campos individuales (iq_sha256, capture_id, etc.) ya existen en los registros canonicos, pero la vista de reconstruccion visual esta pendiente hasta la auditoria de provenance real (roadmap #29)." />
    </div>
  );
}
