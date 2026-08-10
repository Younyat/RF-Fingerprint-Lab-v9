"""Paper export structure (2026-08-10, real generation added 2026-08-11) --
writes `paper_exports/` under the repository root. Pure reporting: never
computes a scientific value itself, only reads what
`ScientificResultsRepository` (or the ble_rffi_studio storage it reads)
already computed/persisted for real, and turns it into a CSV/LaTeX
table/figure.

Every planned export whose real source artifact does not exist yet is
recorded as SKIPPED_NO_DATA in `export_manifest.json` -- never a fabricated
CSV row, an empty placeholder PDF, or a zero-filled table. Each export
function below is a pure transform over an already-parsed dict (unit-
tested directly against synthetic fixtures in
test_paper_export_generation.py); only `generate_paper_exports` touches the
filesystem to decide whether real source data exists.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.infrastructure.ble.capture.ble_capture_metadata import atomic_json

from .figures import paper_figures

EXPORT_MANIFEST_SCHEMA_VERSION = "ble-scientific-results-paper-export-manifest-v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ExportOutcome:
    status: str  # "GENERATED" | "SKIPPED_NO_DATA"
    detail: str
    would_be_derived_from: str | None = None


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ----------------------------------------------------------------------
# Per-export pure transforms: (parsed source dict) -> (csv rows, figure
# calls). Each is independently unit-testable with a synthetic fixture.
# ----------------------------------------------------------------------

def qualification_summary_rows(preflight_report: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"gate": name, "status": item.get("status"), "detail": item.get("detail")} for name, item in preflight_report.get("items", {}).items()]


def association_summary_rows(calibration_attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for attempt in calibration_attempts:
        rows.append({
            "status": attempt.get("status"), "threshold_ms": (attempt.get("policy") or {}).get("threshold_ms"),
            "calibration_campaign_id": (attempt.get("policy") or {}).get("calibration_campaign_id"),
            "detail": attempt.get("detail"),
        })
    return rows


def rq1_result_rows(rq1_report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"domain": "capture-dependent (BA_window)", "ba": rq1_report.get("ba_window"), "n_comparable": rq1_report.get("ba_window_n_comparable")},
        {"domain": "capture-disjoint (BA_capture)", "ba": rq1_report.get("ba_capture"), "n_comparable": rq1_report.get("ba_capture_n_comparable")},
        {"domain": f"protected future ({rq1_report.get('ba_future_status')})", "ba": rq1_report.get("ba_future"), "n_comparable": rq1_report.get("ba_future_n_comparable")},
        {"domain": "delta_dependence", "ba": rq1_report.get("delta_dependence"), "n_comparable": None},
        {"domain": "delta_future", "ba": rq1_report.get("delta_future"), "n_comparable": None},
    ]


def confusion_matrix_rows(confusion_matrix: dict[str, dict[str, int]]) -> list[dict[str, Any]]:
    labels = list(confusion_matrix.keys())
    rows = []
    for true_label in labels:
        row = {"true_label": true_label}
        row.update({f"predicted_{predicted_label}": confusion_matrix[true_label].get(predicted_label, 0) for predicted_label in labels})
        rows.append(row)
    return rows


def statistical_method_rows(confirmatory_report: dict[str, Any], method_names: list[str]) -> list[dict[str, Any]]:
    rows = []
    for name in method_names:
        entry = confirmatory_report.get(name) or {}
        rows.append({"method": name, "status": entry.get("status"), "detail": entry.get("detail"), "value": json.dumps(entry.get("value")) if entry.get("value") is not None else None})
    return rows


def channel_transport_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"channel": row.get("channel"), "center_frequency_hz": row.get("center_frequency_hz"), "bundle_id": row.get("frozen_bundle_id"),
         "windows": row.get("windows"), "balanced_accuracy": row.get("balanced_accuracy"), "macro_f1": row.get("macro_f1"), "coverage": row.get("coverage")}
        for row in report.get("per_channel", [])
    ]


def offline_nearlive_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    agreement = report.get("analytical_agreement") or {}
    for key, value in agreement.items():
        rows.append({"category": "analytical_agreement", "metric": key, "value": value})
    for key, value in (report.get("computational_behavior") or {}).items():
        rows.append({"category": "computational_behavior", "metric": key, "value": value})
    return rows


def render_latex_tables(sections: dict[str, list[dict[str, Any]]]) -> str:
    """Minimal, dependency-free LaTeX table templating -- one `table`
    environment per non-empty section. Never called with a section whose
    rows the caller didn't already confirm are real."""
    lines = ["% Auto-generated by paper_export.py -- real data only, regenerate via the paper export tab.", ""]
    for label, rows in sections.items():
        if not rows:
            continue
        columns = list(rows[0].keys())
        lines.append(f"\\begin{{table}}[htbp]\\centering\\caption{{{label}}}\\label{{tab:{label}}}")
        lines.append("\\begin{tabular}{" + "l" * len(columns) + "}\\toprule")
        lines.append(" & ".join(columns) + " \\\\\\midrule")
        for row in rows:
            lines.append(" & ".join(str(row.get(c, "")).replace("_", "\\_") for c in columns) + " \\\\")
        lines.append("\\bottomrule\\end{tabular}\\end{table}")
        lines.append("")
    return "\n".join(lines)


# ----------------------------------------------------------------------
# Orchestration: real filesystem reads, decides GENERATED vs SKIPPED_NO_DATA.
# ----------------------------------------------------------------------

def _read_json(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _most_recent_run_dir(repository: Any) -> Path | None:
    """Only a directory with a real `run.json` (the same marker
    `ScientificResultsRepository.list_runs()` uses) counts as a paper run --
    NOT any other subdirectory of the repository root (e.g. `logs/`, whose
    mtime can outrace a real run directory's and previously caused this
    function to silently pick the wrong -- non-run -- directory). Ranked by
    the run's own declared `created_at`, never filesystem mtime."""
    run_json_paths = sorted(repository.root.glob("*/run.json"))
    if not run_json_paths:
        return None
    best_path, best_created_at = None, ""
    for path in run_json_paths:
        created_at = json.loads(path.read_text(encoding="utf-8")).get("created_at", "")
        if created_at >= best_created_at:
            best_path, best_created_at = path, created_at
    return best_path.parent


def generate_paper_exports(repository: Any) -> dict[str, Any]:
    exports_dir = repository.root / "paper_exports"
    figures_dir = exports_dir / "figures"
    exports_dir.mkdir(parents=True, exist_ok=True)

    study_status = repository.get_study_status()
    atomic_json(exports_dir / "study_status.json", study_status)
    readiness = repository.get_paper_readiness()
    atomic_json(exports_dir / "paper_readiness.json", {"generated_at": _utc_now(), "elements": readiness})

    entries: list[dict[str, Any]] = [
        {"file": "study_status.json", "status": "GENERATED", "detail": "real, from get_study_status()"},
        {"file": "paper_readiness.json", "status": "GENERATED", "detail": "real, from get_paper_readiness()"},
    ]

    def emit(filename: str, outcome: ExportOutcome) -> None:
        entry = {"file": filename, "status": outcome.status, "detail": outcome.detail}
        if outcome.would_be_derived_from:
            entry["would_be_derived_from"] = outcome.would_be_derived_from
        entries.append(entry)

    # --- Repo-root-scoped exports (no paper_run_id needed) ---
    preflight = _read_json(repository.root / "campaign_qualification_preflight_report.json")
    if preflight is not None:
        _write_csv(exports_dir / "qualification_summary.csv", qualification_summary_rows(preflight))
        emit("qualification_summary.csv", ExportOutcome("GENERATED", "real, from campaign_qualification_preflight_report.json"))
    else:
        emit("qualification_summary.csv", ExportOutcome("SKIPPED_NO_DATA", "no campaign_qualification_preflight_report.json on disk", "campaign_qualification_preflight_report.json"))

    guided_validation_dir = repository.root / "guided_validation"
    calibration_attempts = []
    if guided_validation_dir.is_dir():
        for path in sorted(guided_validation_dir.glob("*/association_policy.json")):
            data = _read_json(path)
            if data is not None:
                calibration_attempts.append(data)
    if calibration_attempts:
        _write_csv(exports_dir / "association_summary.csv", association_summary_rows(calibration_attempts))
        emit("association_summary.csv", ExportOutcome("GENERATED", f"real, from {len(calibration_attempts)} calibration attempt(s)"))
    else:
        emit("association_summary.csv", ExportOutcome("SKIPPED_NO_DATA", "no guided_validation/*/association_policy.json on disk", "guided_validation/*/association_policy.json"))

    # dataset/exclusions summaries need a real paper run's canonical records.
    run_dir = _most_recent_run_dir(repository)
    canonical_dir = (run_dir / "01_inputs" / "canonical_records") if run_dir else None
    captures_payload = _read_json(canonical_dir / "capture_records.json") if canonical_dir else None
    if captures_payload:
        rows = [{"capture_id": c.get("capture_id"), "physical_unit_id": c.get("physical_unit_id"), "day_id": c.get("day_id"), "channel": c.get("channel")} for c in captures_payload]
        _write_csv(exports_dir / "dataset_summary.csv", rows)
        emit("dataset_summary.csv", ExportOutcome("GENERATED", f"real, from {run_dir.name}/01_inputs/canonical_records/capture_records.json"))
    else:
        emit("dataset_summary.csv", ExportOutcome("SKIPPED_NO_DATA", "no canonical capture_records.json for any real paper run", "01_inputs/canonical_records/capture_records.json"))

    deviations_payload = _read_json(canonical_dir / "campaign_deviations.json") if canonical_dir else None
    if deviations_payload:
        rows = [{"deviation_type": d.get("deviation_type"), "classification": d.get("classification"), "severity": d.get("severity")} for d in deviations_payload]
        _write_csv(exports_dir / "exclusions_summary.csv", rows)
        emit("exclusions_summary.csv", ExportOutcome("GENERATED", f"real, from {run_dir.name}/01_inputs/canonical_records/campaign_deviations.json"))
    else:
        emit("exclusions_summary.csv", ExportOutcome("SKIPPED_NO_DATA", "no canonical campaign_deviations.json for any real paper run", "01_inputs/canonical_records/campaign_deviations.json"))

    # --- Run-scoped statistics/RQ exports ---
    rq1_report = repository.get_rq1_acquisition_dependence_report(run_dir.name) if run_dir else None
    if rq1_report:
        _write_csv(exports_dir / "rq1_results.csv", rq1_result_rows(rq1_report))
        emit("rq1_results.csv", ExportOutcome("GENERATED", f"real, from {run_dir.name}/06_statistics/rq1_acquisition_dependence_report.json"))
        if rq1_report.get("ba_window") is not None and rq1_report.get("ba_capture") is not None:
            domains = ["capture-dependent", "capture-disjoint"]
            values = [rq1_report["ba_window"], rq1_report["ba_capture"]]
            if rq1_report.get("ba_future") is not None:
                domains.append("future")
                values.append(rq1_report["ba_future"])
            paper_figures.bar_with_ci_figure(
                categories=domains, values=values, ci_low=None, ci_high=None, ylabel="Balanced accuracy",
                title="RQ1 -- BA by evaluation domain", out_path=figures_dir / "rq1_acquisition_dependence.pdf",
            )
            emit("figures/rq1_acquisition_dependence.pdf", ExportOutcome("GENERATED", "real"))
        else:
            emit("figures/rq1_acquisition_dependence.pdf", ExportOutcome("SKIPPED_NO_DATA", "rq1_acquisition_dependence_report.json is missing ba_window/ba_capture", "06_statistics/rq1_acquisition_dependence_report.json"))
        if rq1_report.get("confusion_matrix_capture"):
            _write_csv(exports_dir / "confusion_matrix_capture.csv", confusion_matrix_rows(rq1_report["confusion_matrix_capture"]))
            emit("confusion_matrix_capture.csv", ExportOutcome("GENERATED", "real, from rq1_acquisition_dependence_report.json"))
        else:
            emit("confusion_matrix_capture.csv", ExportOutcome("SKIPPED_NO_DATA", "rq1_acquisition_dependence_report.json has no confusion_matrix_capture", "06_statistics/rq1_acquisition_dependence_report.json"))
        if rq1_report.get("confusion_matrix_future"):
            _write_csv(exports_dir / "confusion_matrix_future.csv", confusion_matrix_rows(rq1_report["confusion_matrix_future"]))
            emit("confusion_matrix_future.csv", ExportOutcome("GENERATED", "real, from rq1_acquisition_dependence_report.json"))
        else:
            emit("confusion_matrix_future.csv", ExportOutcome("SKIPPED_NO_DATA", "rq1_acquisition_dependence_report.json has no confusion_matrix_future", "06_statistics/rq1_acquisition_dependence_report.json"))
        scored_units = {unit: v.get("recall") for unit, v in (rq1_report.get("per_unit_recall") or {}).items() if v.get("recall") is not None}
        if scored_units:
            paper_figures.bar_with_ci_figure(
                categories=list(scored_units.keys()), values=list(scored_units.values()),
                ci_low=None, ci_high=None, ylabel="Recall", title="RQ1 -- per-unit recall", out_path=figures_dir / "rq1_per_unit_recall.pdf",
            )
            emit("figures/rq1_per_unit_recall.pdf", ExportOutcome("GENERATED", "real"))
        else:
            emit("figures/rq1_per_unit_recall.pdf", ExportOutcome("SKIPPED_NO_DATA", "rq1_acquisition_dependence_report.json has no per-unit recall values", "06_statistics/rq1_acquisition_dependence_report.json"))
    else:
        for name in ("rq1_results.csv", "figures/rq1_acquisition_dependence.pdf", "confusion_matrix_capture.csv", "confusion_matrix_future.csv", "figures/rq1_per_unit_recall.pdf"):
            emit(name, ExportOutcome("SKIPPED_NO_DATA", "no rq1_acquisition_dependence_report.json for any real paper run", "06_statistics/rq1_acquisition_dependence_report.json"))

    confirmatory_future = repository.get_confirmatory_future_analysis_report(run_dir.name) if run_dir else None
    _emit_confirmatory_derived_exports(emit, confirmatory_future, run_dir, exports_dir, figures_dir)

    sensitivity_source = repository.get_confirmatory_statistical_plan_report(run_dir.name) if run_dir else None
    if sensitivity_source and sensitivity_source.get("leave_one_device_out", {}).get("status") == "EXECUTED":
        _write_csv(exports_dir / "sensitivity_results.csv", statistical_method_rows(sensitivity_source, ["leave_one_device_out", "fixed_seed_variability"]))
        emit("sensitivity_results.csv", ExportOutcome("GENERATED", f"real, from {run_dir.name}/06_statistics/confirmatory_statistical_plan_report.json"))
    else:
        emit("sensitivity_results.csv", ExportOutcome("SKIPPED_NO_DATA", "no EXECUTED leave_one_device_out in confirmatory_statistical_plan_report.json", "06_statistics/confirmatory_statistical_plan_report.json"))

    # --- S1/S2 engineering ---
    channel_transport = repository.get_channel_transport_report(run_dir.name) if run_dir else None
    if channel_transport:
        _write_csv(exports_dir / "channel_transport_results.csv", channel_transport_rows(channel_transport))
        emit("channel_transport_results.csv", ExportOutcome("GENERATED", f"real, from {run_dir.name}/06_statistics/channel_transport_report.json"))
        scored_channels = [row for row in channel_transport.get("per_channel", []) if row.get("balanced_accuracy") is not None]
        if scored_channels:
            paper_figures.bar_with_ci_figure(
                categories=[str(row["channel"]) for row in scored_channels], values=[row["balanced_accuracy"] for row in scored_channels],
                ci_low=None, ci_high=None, ylabel="Balanced accuracy", title="S1 -- bounded channel transport",
                out_path=figures_dir / "channel_transport.pdf",
            )
            emit("figures/channel_transport.pdf", ExportOutcome("GENERATED", "real"))
        else:
            emit("figures/channel_transport.pdf", ExportOutcome("SKIPPED_NO_DATA", "no channel in channel_transport_report.json has a real (non-None) balanced_accuracy", "06_statistics/channel_transport_report.json"))
    else:
        emit("channel_transport_results.csv", ExportOutcome("SKIPPED_NO_DATA", "no channel_transport_report.json for any real paper run", "06_statistics/channel_transport_report.json"))
        emit("figures/channel_transport.pdf", ExportOutcome("SKIPPED_NO_DATA", "no channel_transport_report.json for any real paper run", "06_statistics/channel_transport_report.json"))

    offline_nearlive = repository.get_offline_nearlive_report(run_dir.name) if run_dir else None
    if offline_nearlive and offline_nearlive.get("analytical_agreement"):
        _write_csv(exports_dir / "offline_nearlive_results.csv", offline_nearlive_rows(offline_nearlive))
        emit("offline_nearlive_results.csv", ExportOutcome("GENERATED", f"real, from {run_dir.name}/06_statistics/offline_nearlive_report.json"))
        latency = (offline_nearlive.get("computational_behavior") or {}).get("median_latency_ms")
        if isinstance(latency, (int, float)):
            emit("figures/offline_nearlive_latency.pdf", ExportOutcome("SKIPPED_NO_DATA", "latency ECDF needs a real distribution of samples, not just a median -- not yet supplied", "06_statistics/offline_nearlive_report.json"))
        else:
            emit("figures/offline_nearlive_latency.pdf", ExportOutcome("SKIPPED_NO_DATA", "no real latency distribution in offline_nearlive_report.json", "06_statistics/offline_nearlive_report.json"))
    else:
        emit("offline_nearlive_results.csv", ExportOutcome("SKIPPED_NO_DATA", "no offline_nearlive_report.json with real analytical_agreement for any real paper run", "06_statistics/offline_nearlive_report.json"))
        emit("figures/offline_nearlive_latency.pdf", ExportOutcome("SKIPPED_NO_DATA", "no offline_nearlive_report.json for any real paper run", "06_statistics/offline_nearlive_report.json"))

    # --- coverage_results.csv (from RQ1/confirmatory reports' own risk_coverage, when present) ---
    coverage_source = confirmatory_future.get("risk_coverage") if confirmatory_future else None
    if coverage_source and coverage_source.get("status") == "EXECUTED" and coverage_source.get("value"):
        points = coverage_source["value"]
        _write_csv(exports_dir / "coverage_results.csv", points if isinstance(points, list) else [points])
        emit("coverage_results.csv", ExportOutcome("GENERATED", f"real, from {run_dir.name}/06_statistics/confirmatory_future_analysis_report.json"))
        if isinstance(points, list) and points:
            paper_figures.risk_coverage_figure(
                coverage=[p.get("coverage") for p in points], risk=[p.get("risk") for p in points],
                title="Risk-coverage", out_path=figures_dir / "risk_coverage.pdf",
            )
            emit("figures/risk_coverage.pdf", ExportOutcome("GENERATED", "real"))
        else:
            emit("figures/risk_coverage.pdf", ExportOutcome("SKIPPED_NO_DATA", "risk_coverage value is empty", "06_statistics/confirmatory_future_analysis_report.json"))
    else:
        emit("coverage_results.csv", ExportOutcome("SKIPPED_NO_DATA", "no EXECUTED risk_coverage in confirmatory_future_analysis_report.json", "06_statistics/confirmatory_future_analysis_report.json"))
        emit("figures/risk_coverage.pdf", ExportOutcome("SKIPPED_NO_DATA", "no EXECUTED risk_coverage in confirmatory_future_analysis_report.json", "06_statistics/confirmatory_future_analysis_report.json"))

    # --- LaTeX tables: one section per CSV that was actually GENERATED ---
    csv_sections: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        if entry["status"] == "GENERATED" and entry["file"].endswith(".csv"):
            csv_path = exports_dir / entry["file"]
            with csv_path.open(encoding="utf-8") as handle:
                csv_sections[entry["file"].removesuffix(".csv")] = list(csv.DictReader(handle))
    if csv_sections:
        (exports_dir / "paper_tables.tex").write_text(render_latex_tables(csv_sections), encoding="utf-8")
        emit("paper_tables.tex", ExportOutcome("GENERATED", f"real, {len(csv_sections)} table section(s) from real CSVs"))
    else:
        emit("paper_tables.tex", ExportOutcome("SKIPPED_NO_DATA", "no real CSV was generated this run to build tables from", "all of the above, once real"))

    manifest = {
        "schema_version": EXPORT_MANIFEST_SCHEMA_VERSION, "generated_at": _utc_now(),
        "generated_count": sum(1 for e in entries if e["status"] == "GENERATED"),
        "skipped_count": sum(1 for e in entries if e["status"] == "SKIPPED_NO_DATA"),
        "entries": entries,
    }
    atomic_json(exports_dir / "export_manifest.json", manifest)
    return manifest


def _emit_confirmatory_derived_exports(emit: Callable[[str, ExportOutcome], None], confirmatory_future: dict[str, Any] | None, run_dir: Path | None, exports_dir: Path, figures_dir: Path) -> None:
    source = "06_statistics/confirmatory_future_analysis_report.json"
    rq3 = (confirmatory_future or {}).get("rq3_within_device_permutation_test")
    if rq3 and rq3.get("status") == "EXECUTED":
        _write_csv(exports_dir / "rq3_results.csv", statistical_method_rows(confirmatory_future, ["rq3_within_device_permutation_test", "holm_correction"]))
        emit("rq3_results.csv", ExportOutcome("GENERATED", f"real, from {run_dir.name}/{source}" if run_dir else "real"))
        emit("figures/rq3_pre_post.pdf", ExportOutcome("SKIPPED_NO_DATA", "per-unit paired PRE/POST values are not part of the aggregate permutation-test result -- need per-unit series", source))
        emit("figures/rq3_delta_cycle.pdf", ExportOutcome("SKIPPED_NO_DATA", "delta_cycle point estimate exists in the permutation-test result but no CI/distribution is attached to plot yet", source))
    else:
        for name in ("rq3_results.csv", "figures/rq3_pre_post.pdf", "figures/rq3_delta_cycle.pdf"):
            emit(name, ExportOutcome("SKIPPED_NO_DATA", "no EXECUTED rq3_within_device_permutation_test in confirmatory_future_analysis_report.json", source))

    rq4 = (confirmatory_future or {}).get("rq4_paired_comparison")
    non_inferiority = (confirmatory_future or {}).get("non_inferiority")
    if rq4 and rq4.get("status") == "EXECUTED":
        _write_csv(exports_dir / "rq4_results.csv", statistical_method_rows(confirmatory_future, ["rq4_paired_comparison", "non_inferiority", "holm_correction"]))
        emit("rq4_results.csv", ExportOutcome("GENERATED", f"real, from {run_dir.name}/{source}" if run_dir else "real"))
        emit("figures/rq4_region_dependence.pdf", ExportOutcome("SKIPPED_NO_DATA", "per-region (FULL_BURST/ADVA_EXCLUDED/PRE_PDU) recall series not attached to the aggregate paired-comparison result yet", source))
        if non_inferiority and non_inferiority.get("status") == "EXECUTED":
            emit("figures/rq4_noninferiority.pdf", ExportOutcome("SKIPPED_NO_DATA", "non_inferiority result exists but has no plottable CI series attached yet", source))
        else:
            emit("figures/rq4_noninferiority.pdf", ExportOutcome("SKIPPED_NO_DATA", "no EXECUTED non_inferiority in confirmatory_future_analysis_report.json", source))
    else:
        for name in ("rq4_results.csv", "figures/rq4_region_dependence.pdf", "figures/rq4_noninferiority.pdf"):
            emit(name, ExportOutcome("SKIPPED_NO_DATA", "no EXECUTED rq4_paired_comparison in confirmatory_future_analysis_report.json", source))

    for name in ("rq2_results.csv", "figures/rq2_representation_comparison.pdf", "figures/rq2_coverage.pdf"):
        emit(name, ExportOutcome(
            "SKIPPED_NO_DATA",
            "no canonical RQ2 per-branch comparison artifact exists yet -- confirmatory_future_analysis_report.json stores the 11 statistical methods, not a per-branch (engineered_rf/raw_iq/stft/coarse_morphology) table; that aggregation has no producer yet",
            source,
        ))
