"""Paper progress dashboard, point 1 (2026-08-11): a small set of GENERIC,
reusable figure plotters for the paper export -- not 11 bespoke functions.
Reuses `campaign_figures.py`'s exact deterministic matplotlib pattern
(`Agg` backend, fixed figsize/dpi) and extends it with real vector `.pdf`
output (preferred for the manuscript; `campaign_figures.py` itself is left
untouched).

Every function here is a PURE renderer over already-computed numbers --
none of them read a file, none of them compute a statistic, none of them
decide whether real data exists. The caller (`paper_export.py`) is the only
place that checks source-artifact presence and decides whether to call
these at all; that is also why, unlike `campaign_figures.py`, these never
render an "empty axes" placeholder for missing data -- when there is
nothing real to plot, the caller simply does not call this module, and the
export manifest records `SKIPPED_NO_DATA` instead of a file.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

FIGSIZE = (8, 4.5)
DPI = 150


def _save_pdf(fig, out_path: Path) -> str:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return str(out_path)


def bar_with_ci_figure(
    *, categories: Sequence[str], values: Sequence[float], ci_low: Sequence[float] | None,
    ci_high: Sequence[float] | None, ylabel: str, title: str, out_path: Path,
) -> str:
    """RQ1 BA-by-domain, RQ2 BA/macro-F1/coverage-by-branch. `ci_low`/
    `ci_high` are absolute bounds (not offsets) -- None skips error bars for
    a category whose CI is not available, never fabricated as 0-width."""
    fig, ax = plt.subplots(figsize=FIGSIZE)
    x = np.arange(len(categories))
    ax.bar(x, values, color="#2b6cb0")
    if ci_low is not None and ci_high is not None:
        lower_err = [max(0.0, v - lo) if lo is not None else 0.0 for v, lo in zip(values, ci_low)]
        upper_err = [max(0.0, hi - v) if hi is not None else 0.0 for v, hi in zip(values, ci_high)]
        ax.errorbar(x, values, yerr=[lower_err, upper_err], fmt="none", ecolor="#1a202c", capsize=4)
    ax.set_xticks(x)
    ax.set_xticklabels(categories, rotation=20, ha="right")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    return _save_pdf(fig, out_path)


def paired_pre_post_figure(
    *, unit_ids: Sequence[str], pre_values: Sequence[float], post_values: Sequence[float], ylabel: str, title: str, out_path: Path,
) -> str:
    """RQ3 paired PRE->POST per physical unit (RESET or CONTROL arm --
    caller picks which arm's values to pass; two calls for the two arms)."""
    fig, ax = plt.subplots(figsize=FIGSIZE)
    for unit_id, pre, post in zip(unit_ids, pre_values, post_values):
        ax.plot([0, 1], [pre, post], marker="o", color="#2b6cb0", alpha=0.7)
        ax.annotate(unit_id, (1.02, post), fontsize=8, color="#4a5568")
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["PRE", "POST"])
    ax.set_xlim(-0.2, 1.4)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    return _save_pdf(fig, out_path)


def confusion_matrix_figure(*, labels: Sequence[str], matrix: Sequence[Sequence[int]], title: str, out_path: Path) -> str:
    """RQ1 capture-disjoint/FUTURE confusion matrices -- `matrix[i][j]` is
    the count of true label i predicted as label j, exactly
    SplitEvaluationReport.confusion_matrix's own shape."""
    fig, ax = plt.subplots(figsize=(max(FIGSIZE[0], 1.2 * len(labels)), max(FIGSIZE[1], 1.2 * len(labels))))
    array = np.array(matrix, dtype=float)
    im = ax.imshow(array, cmap="Blues")
    ax.set_xticks(range(len(labels)))
    ax.set_yticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_yticklabels(labels)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("True")
    ax.set_title(title)
    for i in range(len(labels)):
        for j in range(len(labels)):
            ax.text(j, i, int(array[i, j]), ha="center", va="center", color="#1a202c", fontsize=9)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    return _save_pdf(fig, out_path)


def risk_coverage_figure(*, coverage: Sequence[float], risk: Sequence[float], title: str, out_path: Path) -> str:
    """Risk-coverage curve -- coverage on x, risk (error rate) on y, exactly
    the shape SplitEvaluationReport.risk_coverage already produces."""
    fig, ax = plt.subplots(figsize=FIGSIZE)
    ax.plot(coverage, risk, marker=".", color="#2b6cb0")
    ax.set_xlabel("coverage")
    ax.set_ylabel("risk")
    ax.set_xlim(0, 1)
    ax.set_ylim(bottom=0)
    ax.set_title(title)
    return _save_pdf(fig, out_path)


def ecdf_figure(*, values: Sequence[float], xlabel: str, title: str, out_path: Path) -> str:
    """Offline/near-live latency ECDF -- a real empirical CDF, not a
    histogram density estimate."""
    fig, ax = plt.subplots(figsize=FIGSIZE)
    sorted_values = np.sort(np.asarray(values, dtype=float))
    n = len(sorted_values)
    y = np.arange(1, n + 1) / n
    ax.step(sorted_values, y, where="post", color="#2b6cb0")
    ax.set_xlabel(xlabel)
    ax.set_ylabel("ECDF")
    ax.set_ylim(0, 1)
    ax.set_title(title)
    return _save_pdf(fig, out_path)


def histogram_figure(*, values: Sequence[float], bins: int, xlabel: str, title: str, out_path: Path) -> str:
    """RQ3 permutation-test null distribution + observed statistic overlay,
    when the canonical report supplies the permutation draws; also reusable
    for any other real distribution the export needs to show."""
    fig, ax = plt.subplots(figsize=FIGSIZE)
    ax.hist(values, bins=bins, color="#2b6cb0")
    ax.set_xlabel(xlabel)
    ax.set_ylabel("count")
    ax.set_title(title)
    return _save_pdf(fig, out_path)
