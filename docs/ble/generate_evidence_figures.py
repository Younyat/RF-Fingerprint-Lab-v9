"""Generates real, static figures from the platform's own real, persisted
evidence -- the exact same aggregation the Evidence Dashboard tab reads live
(ScientificResultsRepository.get_evidence_dashboard_summary()), rendered to
PNG so they are visible directly on GitHub/README without running the
platform. Computes NO new science: every number plotted here is read
verbatim from the same real artifacts the dashboard already serves.

Run from the repo root:
    backend/.venv-validation/Scripts/python.exe docs/ble/generate_evidence_figures.py

Regenerate whenever the underlying real results change (new RQ1/RQ2 runs,
RQ3 campaign progress, RQ4 eligibility) -- this script is the single source
both readme_img/evidence_*.png and docs/ble/evidence_figures.ipynb are built
from, so the two never drift apart.

Paper-representation pass (2026-08-17): the campaign timeline, the closed-set
normalized confusion matrix, and the forensic lineage diagram are NOT
re-plotted here -- they are rendered once by the paper-export pipeline
(`ScientificResultsRepository.run_paper_export()` -> `paper_export.py` ->
`figures/paper_figures.py`, the same real renderer the manuscript's PDF/SVG
exports use) and this script only copies the PNG variant it already wrote
into `readme_img/`. Two renderers for these three figures would be exactly
the duplication this pass exists to remove; the other figures below predate
that pipeline and still compute their own matplotlib calls directly from
`get_evidence_dashboard_summary()` -- no independent computation either way,
only a difference in which renderer is called.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from app.config.settings import settings
from app.modules.ble_scientific_results.api.scientific_results_repository import ScientificResultsRepository

OUT_DIR = REPO_ROOT / "readme_img"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# (paper_exports/figures PNG name, readme_img PNG name) -- copied verbatim
# after run_paper_export(), never re-rendered.
CONSOLIDATED_FIGURES = [
    ("campaign_timeline.png", "evidence_campaign_timeline.png"),
    ("closed_set_confusion_matrix_normalized.png", "evidence_confusion_normalized.png"),
    ("forensic_lineage.png", "evidence_forensic_lineage.png"),
]

# Matches the platform's own dark research-console palette (BleScientific
# ResultsPage.tsx is Tailwind slate/cyan) -- kept legible against GitHub's
# light background instead of mimicking it verbatim.
COLORS = {
    "window": "#b9822c", "capture": "#2f6fb3", "test": "#2f8f89",
    "primary": "#b9822c", "unselected": "#8892a0",
    "reset": "#c1683b", "control": "#2f8f89",
}
plt.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "white", "axes.edgecolor": "#333333",
    "axes.grid": True, "grid.alpha": 0.25, "font.size": 10.5, "axes.titlesize": 11.5, "axes.titleweight": "bold",
})


def load_repository() -> ScientificResultsRepository:
    root = settings.storage.storage_root
    return ScientificResultsRepository(root / "scientific_reports" / "ble", ble_rffi_studio_root=root / "ble_rffi_studio")


def load_summary() -> dict:
    return load_repository().get_evidence_dashboard_summary()


def sync_consolidated_figures(repo: ScientificResultsRepository) -> list[Path]:
    """Runs the real paper-export pipeline and copies the PNG variant of the
    figures it already rendered into readme_img/ -- see module docstring."""
    repo.run_paper_export()
    figures_dir = repo.root / "paper_exports" / "figures"
    written: list[Path] = []
    for source_name, dest_name in CONSOLIDATED_FIGURES:
        source_path = figures_dir / source_name
        if not source_path.is_file():
            continue
        dest_path = OUT_DIR / dest_name
        shutil.copyfile(source_path, dest_path)
        print("wrote", dest_path, "(copied from paper_exports/figures, not re-rendered)")
        written.append(dest_path)
    return written


def _save(fig, name: str) -> Path:
    path = OUT_DIR / name
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print("wrote", path)
    return path


def fig_rq1_domains(summary: dict) -> Path | None:
    # Label correction (2026-08-18, DEVELOPMENT EVIDENCE closure pass): the
    # first bar was previously labeled "BA_window", which reads as if it were
    # the platform's separate 10-second decision-window unit (RQ3/RQ4/
    # coverage_analysis's group_examples_into_windows) -- it is not. This
    # report's own evaluation_unit is EXAMPLE_RECORD (burst-level) for every
    # bar here; the underlying JSON field name (rq1["ba_window"], a frozen
    # contract key elsewhere in the codebase) is unchanged, only this
    # figure's human-readable labels are. "Held-out TEST" is deliberately its
    # own bar, distinct from "protected FUTURE" (which only renders once
    # ba_future is a real, non-None number) -- TEST != FUTURE.
    rq1 = (summary.get("closed_set") or {}).get("rq1")
    primary_test = (summary.get("closed_set") or {}).get("primary_test")
    if not rq1:
        return None
    labels, values, colors, yerr_lower, yerr_upper = [], [], [], [], []
    if rq1.get("ba_window") is not None:
        labels.append("Capture-dependent\n(same capture)"); values.append(rq1["ba_window"]); colors.append(COLORS["window"])
        yerr_lower.append(0.0); yerr_upper.append(0.0)  # no CI on this diagnostic -- intentionally leakage-violating, not a valid estimator
    if rq1.get("ba_capture") is not None:
        labels.append("Capture-disjoint\n(VALIDATION)"); values.append(rq1["ba_capture"]); colors.append(COLORS["capture"])
        ci = (rq1.get("uncertainty_ci") or {}).get("ba_capture_ci") or {}
        ci_low, ci_high = ci.get("ci_low"), ci.get("ci_high")
        yerr_lower.append(max(0.0, rq1["ba_capture"] - ci_low) if ci_low is not None else 0.0)
        yerr_upper.append(max(0.0, ci_high - rq1["ba_capture"]) if ci_high is not None else 0.0)
    if primary_test and primary_test.get("balanced_accuracy") is not None:
        # Held-out TEST -- explicitly NOT "protected FUTURE": FUTURE has not
        # been executed for this study yet (see the separate bar below,
        # which only appears once ba_future is a real number).
        labels.append("Held-out TEST\n(not protected FUTURE)"); values.append(primary_test["balanced_accuracy"]); colors.append(COLORS["test"])
        yerr_lower.append(0.0); yerr_upper.append(0.0)
    if rq1.get("ba_future") is not None:
        labels.append(f"protected FUTURE\n({rq1.get('ba_future_status')})"); values.append(rq1["ba_future"]); colors.append("#5b3d8f")
        yerr_lower.append(0.0); yerr_upper.append(0.0)
    fig, ax = plt.subplots(figsize=(7, 4.3))
    bars = ax.bar(labels, values, color=colors)
    ax.errorbar(range(len(labels)), values, yerr=[yerr_lower, yerr_upper], fmt="none", ecolor="#222222", capsize=4)
    ax.bar_label(bars, fmt="%.3f", padding=3)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Balanced accuracy")
    ax.set_title("RQ1 -- closed-set acquisition dependence")
    delta = rq1.get("delta_dependence")
    caption_lines = []
    if delta is not None:
        ci = (rq1.get("uncertainty_ci") or {}).get("delta_dependence_ci") or {}
        ci_low, ci_high = ci.get("ci_low"), ci.get("ci_high")
        if ci_low is not None and ci_high is not None:
            caption_lines.append(f"delta_dependence = {delta:+.4f}  95% CI [{ci_low:.4f}, {ci_high:.4f}]")
        else:
            caption_lines.append(f"delta_dependence = {delta:+.4f}")
    n_parts = []
    if rq1.get("ba_window_n_comparable") is not None:
        n_parts.append(f"capture-dependent n={rq1['ba_window_n_comparable']}")
    if rq1.get("ba_capture_n_comparable") is not None:
        n_parts.append(f"capture-disjoint n={rq1['ba_capture_n_comparable']}")
    if n_parts:
        caption_lines.append("  ·  ".join(n_parts))
    caption_lines.append("EXAMPLE_RECORD (burst-level) != the platform's separate 10-s decision-window unit")
    if caption_lines:
        ax.text(0.5, -0.32, "\n".join(caption_lines), transform=ax.transAxes, ha="center", fontsize=8.5, color="#555555")
    return _save(fig, "evidence_rq1_domains.png")


def fig_rq2_branches(summary: dict) -> Path | None:
    branches = ((summary.get("closed_set") or {}).get("rq2") or {}).get("branches") or []
    if not branches:
        return None
    names = [b["branch"] for b in branches]
    ba = [b.get("balanced_accuracy") or 0 for b in branches]
    f1 = [b.get("macro_f1") or 0 for b in branches]
    colors = [COLORS["primary"] if b.get("analysis_role") == "PRIMARY" else COLORS["unselected"] for b in branches]
    x = np.arange(len(names))
    fig, ax = plt.subplots(figsize=(6.5, 4))
    ax.bar(x - 0.2, ba, width=0.4, label="Balanced accuracy", color=colors)
    ax.bar(x + 0.2, f1, width=0.4, label="Macro-F1", color=colors, alpha=0.55, hatch="//")
    ax.set_xticks(x); ax.set_xticklabels(names, rotation=15)
    ax.set_ylim(0, 1.05)
    ax.set_title("RQ2 -- closed-set representation comparison (VALIDATION)")
    ax.legend(frameon=False)
    return _save(fig, "evidence_rq2_branches.png")


def fig_confusion(matrix: dict | None, title: str, filename: str) -> Path | None:
    if not matrix:
        return None
    labels = list(matrix.keys())
    grid = np.array([[matrix[t].get(p, 0) for p in labels] for t in labels], dtype=float)
    fig, ax = plt.subplots(figsize=(5, 4.4))
    im = ax.imshow(grid, cmap="Blues")
    ax.set_xticks(range(len(labels))); ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.set_yticks(range(len(labels))); ax.set_yticklabels(labels)
    ax.set_xlabel("predicted"); ax.set_ylabel("true")
    ax.set_title(title)
    vmax = grid.max() or 1
    for i in range(len(labels)):
        for j in range(len(labels)):
            color = "white" if grid[i, j] > vmax * 0.5 else "#222222"
            ax.text(j, i, int(grid[i, j]), ha="center", va="center", color=color, fontsize=9)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    return _save(fig, filename)


def fig_per_unit_metrics(summary: dict) -> Path | None:
    primary_test = (summary.get("closed_set") or {}).get("primary_test") or {}
    recall = primary_test.get("recall_per_class") or {}
    precision = primary_test.get("precision_per_class") or {}
    f1 = primary_test.get("f1_per_class") or {}
    if not recall:
        return None
    units = list(recall.keys())
    x = np.arange(len(units))
    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.bar(x - 0.27, [recall.get(u, 0) for u in units], width=0.27, label="Recall", color="#2f6fb3")
    ax.bar(x, [precision.get(u, 0) for u in units], width=0.27, label="Precision", color="#b9822c")
    ax.bar(x + 0.27, [f1.get(u, 0) for u in units], width=0.27, label="F1", color="#2f8f89")
    ax.set_xticks(x); ax.set_xticklabels(units, rotation=15)
    ax.set_ylim(0, 1.05)
    ax.set_title("Per-unit precision / recall / F1 -- TEST, PRIMARY branch")
    ax.legend(frameon=False)
    return _save(fig, "evidence_per_unit_metrics.png")


def fig_risk_coverage(summary: dict) -> Path | None:
    points = ((summary.get("closed_set") or {}).get("primary_test") or {}).get("risk_coverage") or []
    if not points:
        return None
    pts = sorted(points, key=lambda p: p["coverage"])
    fig, ax = plt.subplots(figsize=(5.5, 4))
    ax.plot([p["coverage"] for p in pts], [p["risk"] for p in pts], color="#2f6fb3", marker="o", markersize=2.5, linewidth=1.4)
    ax.set_xlabel("coverage"); ax.set_ylabel("risk")
    ax.set_xlim(0, 1)
    ax.set_title("Risk-coverage (TEST, PRIMARY branch) -- DEVELOPMENT / EXPLORATORY\nEl-Yaniv & Wiener (2010)")
    return _save(fig, "evidence_risk_coverage.png")


def fig_seed_variability(summary: dict) -> Path | None:
    branches = ((summary.get("closed_set") or {}).get("rq2") or {}).get("branches") or []
    primary = next((b for b in branches if b.get("analysis_role") == "PRIMARY"), None)
    seeds = (primary or {}).get("seed_variability") or []
    if not seeds:
        return None
    labels = [f"seed {s['seed']}" for s in seeds]
    values = [s.get("validation_balanced_accuracy") or 0 for s in seeds]
    fig, ax = plt.subplots(figsize=(4.5, 4))
    bars = ax.bar(labels, values, color="#2f6fb3")
    ax.bar_label(bars, fmt="%.3f", padding=3)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Balanced accuracy (VALIDATION)")
    ax.set_title(f"Seed variability -- {primary['branch']} (PRIMARY) -- DEVELOPMENT / SENSITIVITY")
    return _save(fig, "evidence_seed_variability.png")


def fig_computational_cost(summary: dict) -> Path | None:
    branches = ((summary.get("closed_set") or {}).get("rq2") or {}).get("branches") or []
    branches = [b for b in branches if b.get("inference_latency_ms") is not None and b.get("serialized_model_size_bytes") is not None]
    if not branches:
        return None
    names = [b["branch"] for b in branches]
    latency = [b["inference_latency_ms"] for b in branches]
    size_kb = [b["serialized_model_size_bytes"] / 1024 for b in branches]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(8.5, 4))
    ax1.bar(names, latency, color="#2f6fb3"); ax1.set_ylabel("ms"); ax1.set_title("Inference latency"); ax1.tick_params(axis="x", rotation=20)
    ax2.bar(names, size_kb, color="#b9822c"); ax2.set_ylabel("KB"); ax2.set_title("Serialized model size"); ax2.tick_params(axis="x", rotation=20)
    fig.suptitle("Computational cost by RQ2 branch -- DEVELOPMENT")
    # Real methodology (training_service.py::_measure_latency_ms): wall-clock
    # time.perf_counter() around a single-sample predict_proba call, mean of
    # 10 repeats, measured on VALIDATION data for every branch of the SAME
    # training run -- so the 4 branches are comparable to each other, but the
    # specific host/machine identity was never captured at measurement time
    # (real gap, not fabricated here) and is not the same as any embedded
    # deployment target.
    fig.text(0.5, -0.03, "latency = mean of 10 repeats, single-sample predict_proba, wall-clock (host not captured at measurement time)",
              ha="center", va="top", fontsize=7.5, color="#4a5568")
    return _save(fig, "evidence_computational_cost.png")


def fig_per_unit_auxiliary_rq1(summary: dict) -> Path | None:
    runs = summary.get("per_unit_auxiliary") or []
    runs = [r for r in runs if r.get("rq1")]
    if not runs:
        return None
    names = [r["dataset_id"] for r in runs]
    window = [r["rq1"].get("ba_window") or 0 for r in runs]
    capture = [r["rq1"].get("ba_capture") or 0 for r in runs]
    x = np.arange(len(names))
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    ax.bar(x - 0.2, window, width=0.4, label="BA_window", color=COLORS["window"])
    ax.bar(x + 0.2, capture, width=0.4, label="BA_capture", color=COLORS["capture"])
    ax.set_xticks(x); ax.set_xticklabels(names, rotation=15, ha="right")
    ax.set_ylim(0, 1.05)
    ax.set_title("Per-unit auxiliary TARGET_VS_BACKGROUND -- RQ1 (4 real runs)")
    ax.legend(frameon=False)
    return _save(fig, "evidence_per_unit_auxiliary_rq1.png")


FIGURES = [
    ("RQ1 -- closed-set acquisition dependence", fig_rq1_domains),
    ("RQ2 -- closed-set branch comparison", fig_rq2_branches),
    ("Per-unit precision/recall/F1 (TEST)", fig_per_unit_metrics),
    ("Risk-coverage (TEST)", fig_risk_coverage),
    ("Seed variability (PRIMARY branch)", fig_seed_variability),
    ("Computational cost by branch", fig_computational_cost),
    ("Per-unit auxiliary RQ1 (4 real runs)", fig_per_unit_auxiliary_rq1),
]


def main() -> None:
    repo = load_repository()
    summary = repo.get_evidence_dashboard_summary()
    fig_confusion((summary.get("closed_set") or {}).get("rq1", {}).get("confusion_matrix_capture"),
                  "Confusion matrix -- VALIDATION (capture-disjoint)", "evidence_confusion_validation.png")
    fig_confusion((summary.get("closed_set") or {}).get("primary_test", {}).get("confusion_matrix"),
                  "Confusion matrix -- TEST (PRIMARY branch)", "evidence_confusion_test.png")
    for _title, fn in FIGURES:
        fn(summary)
    sync_consolidated_figures(repo)


if __name__ == "__main__":
    main()
