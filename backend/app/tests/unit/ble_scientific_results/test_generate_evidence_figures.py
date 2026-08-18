"""Figure/artifact sync closure (2026-08-18): docs/ble/generate_evidence_
figures.py is a standalone script (not part of the `app` package -- it
inserts `backend/` onto sys.path itself, the same trick reused here in
reverse to import IT from a backend test). RQ1/RQ2 are no longer rendered
by a second, independently-coded function here (fig_rq1_domains/
fig_rq2_branches were deleted) -- readme_img/'s copies are now always the
exact same PDF/PNG paper_export.py already rendered (see
figures/paper_figures.py::bar_with_ci_figure, multi-format). What remains
real to test in this module is `verify_figures()` -- the read-only
cross-check against `paper_exports/figure_manifest.json` -- since it is
this script's own logic, not a re-test of paper_export.py (tested
separately in test_paper_export_generation.py).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

DOCS_BLE_DIR = Path(__file__).resolve().parents[5] / "docs" / "ble"
sys.path.insert(0, str(DOCS_BLE_DIR))

import generate_evidence_figures as gef  # noqa: E402


def _repo(tmp_path):
    root = tmp_path / "sci_results"
    root.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(root=root)


def _write_rq1_artifact(repo, *, paper_run_id="RUN-1", evaluation_unit="EXAMPLE_RECORD", evidence_status="DEVELOPMENT", with_ci=True, ba_future=None) -> Path:
    path = repo.root / paper_run_id / "06_statistics" / "rq1_acquisition_dependence_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "evaluation_unit": evaluation_unit, "evidence_status": evidence_status,
        "ba_window": 0.968, "ba_capture": 0.749, "ba_future": ba_future, "ba_future_status": "NOT_YET_AVAILABLE" if ba_future is None else "EXECUTED",
        "delta_dependence": 0.219,
        "uncertainty_ci": {"ba_capture_ci": {"ci_low": 0.544, "ci_high": 0.884}} if with_ci else {},
    }
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def _write_manifest(repo, entries: list[dict]) -> None:
    exports_dir = repo.root / "paper_exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    (exports_dir / "figure_manifest.json").write_text(json.dumps({"figures": entries}), encoding="utf-8")


def _manifest_entry_for(source_path: Path, *, paper_run_id="RUN-1", evaluation_unit="EXAMPLE_RECORD", evidence_status="DEVELOPMENT", figure_path="figures/rq1_acquisition_dependence.png", source_artifact_relpath=None) -> dict:
    return {
        "figure_path": figure_path,
        "source_artifact": source_artifact_relpath or f"{paper_run_id}/06_statistics/rq1_acquisition_dependence_report.json",
        "source_artifact_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "paper_run_id": paper_run_id, "evaluation_unit": evaluation_unit, "evidence_status": evidence_status,
        "generator_commit": "deadbeef", "generated_at": "2026-08-18T00:00:00Z",
    }


def test_verify_fails_when_manifest_missing(tmp_path):
    repo = _repo(tmp_path)
    failures = gef.verify_figures(repo, None)
    assert len(failures) == 1
    assert "figure_manifest.json does not exist" in failures[0]


def test_verify_fails_when_a_required_figure_has_no_entry(tmp_path):
    repo = _repo(tmp_path)
    _write_manifest(repo, [])
    failures = gef.verify_figures(repo, None)
    assert any("MISSING_REQUIRED_SOURCE" in f and "rq1_acquisition_dependence" in f for f in failures)
    assert any("MISSING_REQUIRED_SOURCE" in f and "rq2_representation_comparison" in f for f in failures)


def test_verify_passes_when_manifest_matches_real_artifact(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(gef, "OUT_DIR", tmp_path / "readme_img")
    rq1_path = _write_rq1_artifact(repo)
    rq2_path = repo.root / "RUN-1" / "06_statistics" / "rq2_representation_comparison_report.json"
    rq2_path.write_text(json.dumps({"evaluation_unit": "EXAMPLE_RECORD", "evidence_status": "DEVELOPMENT"}), encoding="utf-8")
    entries = [
        _manifest_entry_for(rq1_path, figure_path="figures/rq1_acquisition_dependence.png"),
        _manifest_entry_for(rq2_path, figure_path="figures/rq2_representation_comparison.png", source_artifact_relpath="RUN-1/06_statistics/rq2_representation_comparison_report.json"),
    ]
    _write_manifest(repo, entries)
    assert gef.verify_figures(repo, None) == []
    assert gef.verify_figures(repo, "RUN-1") == []


def test_verify_fails_on_stale_artifact_hash(tmp_path, monkeypatch):
    # The classic desync this whole mechanism exists to catch: the artifact
    # changed on disk (regenerated) but the figure/manifest were not.
    repo = _repo(tmp_path)
    monkeypatch.setattr(gef, "OUT_DIR", tmp_path / "readme_img")
    rq1_path = _write_rq1_artifact(repo)
    rq2_path = repo.root / "RUN-1" / "06_statistics" / "rq2_representation_comparison_report.json"
    rq2_path.write_text(json.dumps({"evaluation_unit": "EXAMPLE_RECORD", "evidence_status": "DEVELOPMENT"}), encoding="utf-8")
    entries = [
        _manifest_entry_for(rq1_path),
        _manifest_entry_for(rq2_path, figure_path="figures/rq2_representation_comparison.png", source_artifact_relpath="RUN-1/06_statistics/rq2_representation_comparison_report.json"),
    ]
    _write_manifest(repo, entries)
    # Real artifact changes (e.g. re-run of RQ1) -- manifest's recorded
    # sha256 is now stale.
    rq1_path.write_text(json.dumps({"evaluation_unit": "EXAMPLE_RECORD", "evidence_status": "DEVELOPMENT", "ba_window": 0.5, "ba_capture": 0.4, "uncertainty_ci": {"ba_capture_ci": {"ci_low": 0.3, "ci_high": 0.5}}}), encoding="utf-8")
    failures = gef.verify_figures(repo, None)
    assert any("STALE_ARTIFACT" in f and "rq1_acquisition_dependence" in f for f in failures)


def test_verify_fails_when_evaluation_unit_mismatches(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(gef, "OUT_DIR", tmp_path / "readme_img")
    rq1_path = _write_rq1_artifact(repo, evaluation_unit="EXAMPLE_RECORD")
    entry = _manifest_entry_for(rq1_path, evaluation_unit="DECISION_WINDOW")  # manifest disagrees with the real artifact
    _write_manifest(repo, [entry])
    failures = gef.verify_figures(repo, None)
    assert any("EVALUATION_UNIT_MISMATCH" in f for f in failures)


def test_verify_fails_when_paper_run_id_does_not_match(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(gef, "OUT_DIR", tmp_path / "readme_img")
    rq1_path = _write_rq1_artifact(repo, paper_run_id="RUN-1")
    entry = _manifest_entry_for(rq1_path, paper_run_id="RUN-1")
    _write_manifest(repo, [entry])
    failures = gef.verify_figures(repo, "RUN-DIFFERENT")
    assert any("PAPER_RUN_ID_MISMATCH" in f for f in failures)


def test_verify_fails_when_required_ci_missing(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(gef, "OUT_DIR", tmp_path / "readme_img")
    rq1_path = _write_rq1_artifact(repo, with_ci=False)
    entry = _manifest_entry_for(rq1_path)
    _write_manifest(repo, [entry])
    failures = gef.verify_figures(repo, None)
    assert any("MISSING_REQUIRED_CI" in f for f in failures)


def test_verify_fails_when_test_labeled_as_future(tmp_path, monkeypatch):
    # ba_future is still None (protected FUTURE not executed) but the
    # manifest claims evidence_status=PROTECTED_FUTURE -- exactly the
    # TEST != FUTURE conflation this whole pass exists to prevent.
    repo = _repo(tmp_path)
    monkeypatch.setattr(gef, "OUT_DIR", tmp_path / "readme_img")
    rq1_path = _write_rq1_artifact(repo, ba_future=None)
    entry = _manifest_entry_for(rq1_path, evidence_status="PROTECTED_FUTURE")
    _write_manifest(repo, [entry])
    failures = gef.verify_figures(repo, None)
    assert any("TEST_LABELED_AS_FUTURE" in f for f in failures)


def test_verify_fails_when_readme_copy_diverges_from_paper_export(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    out_dir = tmp_path / "readme_img"
    out_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(gef, "OUT_DIR", out_dir)
    rq1_path = _write_rq1_artifact(repo)
    rq2_path = repo.root / "RUN-1" / "06_statistics" / "rq2_representation_comparison_report.json"
    rq2_path.write_text(json.dumps({"evaluation_unit": "EXAMPLE_RECORD", "evidence_status": "DEVELOPMENT"}), encoding="utf-8")
    entries = [
        _manifest_entry_for(rq1_path),
        _manifest_entry_for(rq2_path, figure_path="figures/rq2_representation_comparison.png", source_artifact_relpath="RUN-1/06_statistics/rq2_representation_comparison_report.json"),
    ]
    _write_manifest(repo, entries)
    figures_dir = repo.root / "paper_exports" / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    (figures_dir / "rq1_acquisition_dependence.png").write_bytes(b"real-png-bytes")
    (out_dir / "evidence_rq1_domains.png").write_bytes(b"DIFFERENT-bytes-someone-hand-edited-this")
    failures = gef.verify_figures(repo, None)
    assert any("DIVERGED_FROM_PAPER_EXPORT" in f for f in failures)
