import NoDataNotice from './NoDataNotice';

export default function OnlineEquivalenceTab() {
  return (
    <div className="space-y-4 p-4">
      <div>
        <div className="text-sm font-semibold text-slate-200">Engineering -- Offline vs near-live</div>
        <div className="mt-1 text-xs text-slate-500">
          Dos clases separadas cuando existan datos reales: discriminacion cientifica (acuerdo de prediccion) y
          rendimiento computacional (latencia, throughput, drops). Nunca 0 cuando no este medido.
        </div>
      </div>
      <NoDataNotice reason="NOT_MEASURED_YET -- ningun path de inferencia near-live esta instrumentado con latencia/throughput/drop-rate todavia." />
    </div>
  );
}
