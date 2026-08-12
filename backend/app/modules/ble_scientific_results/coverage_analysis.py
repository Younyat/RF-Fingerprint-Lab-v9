"""Coverage / abstention canonical producer (2026-08-12, Scientific
Closure pass) -- Coverage audit finding: the real decision records
(OfflineInferenceService.run_decision_windows(), the SAME frozen primary-
branch/preprocessing/decision-window-rule/calibrated-threshold pipeline
RQ3 already drives) already carry everything needed to compute coverage
overall and by evaluation_domain/branch/physical_unit, but nothing
aggregated them -- this module is exactly that aggregation, real reporting,
no new methodology:

- "decided" reuses the EXACT SAME abstention definition
  `scientific_results_repository.run_confirmatory_statistical_plan`'s own
  `coverage()` call already uses: abstained iff
  `final_decision == "INSUFFICIENT_EVIDENCE"` (UNKNOWN counts as decided --
  a real classification decision, just not the target class).
- `coverage()` itself is `statistics/metrics.py`'s existing, already-tested
  function -- never a second definition, never a different threshold
  family "to make a prettier curve".
- `abstention_reason` is read verbatim from `run_decision_windows()`'s own
  output (real, machine-readable, e.g.
  "BELOW_MINIMUM_ELIGIBLE_BURSTS:1<2") -- reported as `NOT_AVAILABLE` only
  when the source genuinely never populated one, never inferred
  retrospectively.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .statistics.metrics import coverage as _coverage


@dataclass(frozen=True)
class CoverageRow:
    decided: bool
    correct: bool | None = None
    evaluation_domain: str | None = None
    branch: str | None = None
    physical_unit_id: str | None = None
    abstention_reason: str | None = None


def coverage_row_from_decision_window(
    window: dict[str, Any], *, evaluation_domain: str | None = None, branch: str | None = None,
) -> CoverageRow:
    """Real, single-source-of-truth mapping from a real
    run_decision_windows() output row to a CoverageRow. `correct` is set
    only when the window carries BOTH a real predicted_class and a real
    physical_unit_id ground truth -- never inferred when either is
    missing."""
    decided = window.get("final_decision") != "INSUFFICIENT_EVIDENCE"
    physical_unit_id = window.get("physical_unit_id")
    correct = None
    if decided and physical_unit_id is not None:
        correct = window.get("final_decision") == "IDENTIFIED" and window.get("predicted_class") == physical_unit_id
    return CoverageRow(
        decided=decided, correct=correct, evaluation_domain=evaluation_domain, branch=branch,
        physical_unit_id=physical_unit_id, abstention_reason=window.get("abstention_reason"),
    )


def _bucket(rows: list[CoverageRow]) -> dict[str, Any] | None:
    total = len(rows)
    if total == 0:
        return None
    abstained = sum(1 for r in rows if not r.decided)
    decided_rows = [r for r in rows if r.decided]
    comparable = [r for r in decided_rows if r.correct is not None]
    errors_among_decided = sum(1 for r in comparable if not r.correct) if comparable else None
    risk_among_decided = (errors_among_decided / len(comparable)) if comparable else None
    return {
        "eligible_windows": total, "decided_windows": len(decided_rows), "abstained_windows": abstained,
        "coverage": _coverage(total, abstained), "errors_among_decided": errors_among_decided,
        "risk_among_decided": risk_among_decided,
    }


def compute_coverage_summary(rows: list[CoverageRow]) -> dict[str, Any]:
    """Real, general aggregation over already-real CoverageRows -- groups
    by whichever dimensions (evaluation_domain/branch/physical_unit) are
    actually present on the rows, never fabricates a bucket for a
    dimension nothing supplied."""
    overall = _bucket(rows)
    domains = sorted({r.evaluation_domain for r in rows if r.evaluation_domain is not None})
    branches = sorted({r.branch for r in rows if r.branch is not None})
    units = sorted({r.physical_unit_id for r in rows if r.physical_unit_id is not None})
    by_domain = {domain: _bucket([r for r in rows if r.evaluation_domain == domain]) for domain in domains}
    by_branch = {branch: _bucket([r for r in rows if r.branch == branch]) for branch in branches}
    by_unit = {unit: _bucket([r for r in rows if r.physical_unit_id == unit]) for unit in units}

    abstained_rows = [r for r in rows if not r.decided]
    abstention_reason_counts: Any
    if abstained_rows and any(r.abstention_reason is not None for r in abstained_rows):
        counts: dict[str, int] = {}
        for row in abstained_rows:
            key = row.abstention_reason or "NOT_AVAILABLE"
            counts[key] = counts.get(key, 0) + 1
        abstention_reason_counts = counts
    else:
        abstention_reason_counts = "NOT_AVAILABLE"

    return {
        "overall": overall, "by_evaluation_domain": by_domain, "by_branch": by_branch,
        "by_physical_unit": by_unit, "abstention_reason_counts": abstention_reason_counts,
    }
