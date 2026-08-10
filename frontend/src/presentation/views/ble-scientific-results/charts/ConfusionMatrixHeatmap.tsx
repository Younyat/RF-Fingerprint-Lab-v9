import NoDataNotice from '../NoDataNotice';

/** RQ1 capture-disjoint/FUTURE confusion matrices -- `matrix[trueLabel][predictedLabel]`
 * exactly SplitEvaluationReport.confusion_matrix's own dict-of-dicts shape.
 * No heatmap primitive exists anywhere in this codebase or in recharts, so
 * this is a small CSS-grid pattern: each cell's background intensity is a
 * simple linear interpolation of its own count against the matrix max --
 * a display-only computation, never a statistic. */
export default function ConfusionMatrixHeatmap({
  matrix,
  noDataReason,
}: {
  matrix: Record<string, Record<string, number>> | null | undefined;
  noDataReason: string;
}) {
  const labels = matrix ? Object.keys(matrix) : [];
  if (!matrix || labels.length === 0) {
    return <NoDataNotice reason={noDataReason} />;
  }
  const maxCount = Math.max(1, ...labels.flatMap((t) => labels.map((p) => matrix[t]?.[p] ?? 0)));

  return (
    <div className="overflow-x-auto">
      <div
        role="table"
        aria-label="Confusion matrix"
        className="inline-grid gap-px bg-slate-800"
        style={{ gridTemplateColumns: `auto repeat(${labels.length}, minmax(48px, 1fr))` }}
      >
        <div />
        {labels.map((p) => (
          <div key={`col-${p}`} className="bg-slate-950 px-2 py-1 text-center text-[10px] text-slate-400">{p}</div>
        ))}
        {labels.map((t) => (
          <div key={`row-${t}`} className="contents">
            <div className="bg-slate-950 px-2 py-1 text-right text-[10px] text-slate-400">{t}</div>
            {labels.map((p) => {
              const count = matrix[t]?.[p] ?? 0;
              const intensity = count / maxCount;
              return (
                <div
                  key={`${t}-${p}`}
                  data-testid="confusion-cell"
                  className="flex items-center justify-center py-2 text-xs font-mono text-slate-100"
                  style={{ backgroundColor: `rgba(43, 108, 176, ${0.12 + 0.68 * intensity})` }}
                >
                  {count}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
