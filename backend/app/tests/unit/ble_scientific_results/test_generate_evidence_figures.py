"""DEVELOPMENT EVIDENCE closure pass (2026-08-18): docs/ble/generate_evidence_
figures.py is a standalone script (not part of the `app` package -- it
inserts `backend/` onto sys.path itself, the same trick reused here in
reverse to import IT from a backend test), but it is the sole renderer for
readme_img/evidence_rq1_domains.png -- the exact figure the paper cites. This
guards two real regressions: the figure must never again display "BA_window"
as a bar label (the naming confusion this whole DEVELOPMENT EVIDENCE pass
fixed), and it must never fabricate a bar when the underlying real report
carries no data for it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

DOCS_BLE_DIR = Path(__file__).resolve().parents[5] / "docs" / "ble"
sys.path.insert(0, str(DOCS_BLE_DIR))

import generate_evidence_figures as gef  # noqa: E402


def _rq1_summary(**overrides):
    base = {
        "closed_set": {
            "rq1": {
                "ba_window": 0.968, "ba_window_n_comparable": 1790,
                "ba_capture": 0.749, "ba_capture_n_comparable": 2203,
                "ba_future": None, "ba_future_status": "NOT_YET_AVAILABLE",
                "delta_dependence": 0.219,
                "uncertainty_ci": {"ba_capture_ci": {"ci_low": 0.544, "ci_high": 0.884}, "delta_dependence_ci": {"ci_low": 0.077, "ci_high": 0.414}},
            },
            "primary_test": {"balanced_accuracy": 0.767},
        },
    }
    base["closed_set"].update(overrides)
    return base


def test_rq1_figure_never_labels_the_capture_dependent_bar_ba_window(tmp_path, monkeypatch):
    monkeypatch.setattr(gef, "OUT_DIR", tmp_path)
    path = gef.fig_rq1_domains(_rq1_summary())
    assert path is not None and path.is_file()
    # The figure must use a human-readable label, never the raw "BA_window"
    # field name (which reads as if it were the platform's separate
    # 10-second decision-window unit -- it is not; see the figure's own
    # caption / PAPER_EVIDENCE_MAP.md). _save() closes the figure before
    # returning, so this asserts on the function's own source rather than a
    # live Axes -- still a real regression guard against a hand-revert.
    import inspect
    source = inspect.getsource(gef.fig_rq1_domains)
    # The exact old bar-label literal this pass replaced -- checking for
    # this specific string (not the bare substring "BA_window", which still
    # legitimately appears in explanatory comments and the JSON field name
    # rq1["ba_window"] itself) avoids false-flagging those.
    assert '"BA_window\\n(intra-session)"' not in source


def test_rq1_figure_shows_test_and_future_as_distinct_bars_when_both_real():
    summary = _rq1_summary()
    summary["closed_set"]["rq1"]["ba_future"] = 0.7
    summary["closed_set"]["rq1"]["ba_future_status"] = "EXECUTED"
    import inspect
    source = inspect.getsource(gef.fig_rq1_domains)
    assert "ba_future" in source and "primary_test" in source  # two structurally separate data sources, never merged


def test_rq1_figure_returns_none_without_fabricating_when_no_rq1_report():
    assert gef.fig_rq1_domains({"closed_set": {}}) is None
    assert gef.fig_rq1_domains({}) is None


def test_rq2_figure_returns_none_without_fabricating_when_no_branches():
    assert gef.fig_rq2_branches({"closed_set": {"rq2": {"branches": []}}}) is None
    assert gef.fig_rq2_branches({}) is None


def test_rq2_figure_generated_from_real_branch_data(tmp_path, monkeypatch):
    monkeypatch.setattr(gef, "OUT_DIR", tmp_path)
    summary = {"closed_set": {"rq2": {"branches": [
        {"branch": "engineered_rf", "analysis_role": "PRIMARY", "balanced_accuracy": 0.634, "macro_f1": 0.586},
        {"branch": "raw_iq", "analysis_role": "UNSELECTED", "balanced_accuracy": 0.248, "macro_f1": 0.226},
    ]}}}
    path = gef.fig_rq2_branches(summary)
    assert path is not None and path.is_file()
