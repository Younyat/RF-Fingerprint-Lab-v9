"""Paper export structure (2026-08-10) -- writes `paper_exports/` under the
repository root. Pure reporting: never computes a scientific value itself,
only reads what `ScientificResultsRepository` already computed/persisted
for real (`get_study_status`, `get_paper_readiness`) and, for every other
planned export this study will eventually need, checks whether its real
source artifact exists.

Every planned export that has no real source data yet is recorded as
SKIPPED_NO_DATA in `export_manifest.json` -- never a fabricated CSV row, an
empty placeholder PDF, or a zero-filled table. The manifest itself is
always real and always written; only the fabrication is refused.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.infrastructure.ble.capture.ble_capture_metadata import atomic_json

EXPORT_MANIFEST_SCHEMA_VERSION = "ble-scientific-results-paper-export-manifest-v1"

# (relative output path, human description, real source artifact this
# export would be derived from -- documented so a future implementer knows
# exactly what to read, never guesses).
_PLANNED_EXPORTS: tuple[tuple[str, str, str], ...] = (
    ("qualification_summary.csv", "Per-capture qualification results", "campaign_qualification_preflight_report.json"),
    ("association_summary.csv", "Association calibration summary", "guided_validation/*/association_policy.json"),
    ("dataset_summary.csv", "Dataset/campaign composition", "canonical capture/burst records (01_inputs/canonical_records)"),
    ("exclusions_summary.csv", "Exclusion/deviation reasons", "campaign_deviations canonical records"),
    ("rq1_results.csv", "RQ1 acquisition-dependence table", "06_statistics/rq1_acquisition_dependence_report.json"),
    ("rq2_results.csv", "RQ2 representation-comparison table", "06_statistics/confirmatory_future_analysis_report.json"),
    ("rq3_results.csv", "RQ3 reset-associated displacement table", "06_statistics/confirmatory_future_analysis_report.json"),
    ("rq4_results.csv", "RQ4 packet-content-dependence table", "06_statistics/confirmatory_future_analysis_report.json"),
    ("coverage_results.csv", "Coverage/abstention table", "evaluation_report.json risk_coverage"),
    ("sensitivity_results.csv", "LODO / offset-retaining / seed-variability table", "06_statistics/confirmatory_future_analysis_report.json (leave_one_device_out) + seed-variability run output"),
    ("channel_transport_results.csv", "CH37->38/39 engineering transport table", "not yet implemented (engineering analysis, out of RQ1-4 scope)"),
    ("offline_nearlive_results.csv", "Offline vs near-live engineering table", "not yet instrumented"),
    ("confusion_matrix_capture.csv", "Capture-disjoint confusion matrix", "SplitEvaluationReport.confusion_matrix (capture-disjoint domain)"),
    ("confusion_matrix_future.csv", "FUTURE confusion matrix", "SplitEvaluationReport.confusion_matrix (FUTURE domain)"),
    ("paper_tables.tex", "LaTeX paper tables", "all of the above, once real"),
    ("figures/rq1_acquisition_dependence.pdf", "RQ1 BA-by-domain figure", "rq1_acquisition_dependence_report.json"),
    ("figures/rq1_per_unit_recall.pdf", "RQ1 per-unit recall figure", "rq1_acquisition_dependence_report.json"),
    ("figures/rq2_representation_comparison.pdf", "RQ2 branch comparison figure", "confirmatory_future_analysis_report.json"),
    ("figures/rq2_coverage.pdf", "RQ2 coverage figure", "confirmatory_future_analysis_report.json"),
    ("figures/rq3_pre_post.pdf", "RQ3 paired PRE/POST figure", "confirmatory_future_analysis_report.json"),
    ("figures/rq3_delta_cycle.pdf", "RQ3 delta_cycle figure", "confirmatory_future_analysis_report.json"),
    ("figures/rq4_region_dependence.pdf", "RQ4 region-dependence figure", "confirmatory_future_analysis_report.json"),
    ("figures/rq4_noninferiority.pdf", "RQ4 non-inferiority figure", "confirmatory_future_analysis_report.json"),
    ("figures/risk_coverage.pdf", "Risk-coverage curve figure", "evaluation_report.json risk_coverage"),
    ("figures/channel_transport.pdf", "Channel-transport figure", "not yet implemented"),
    ("figures/offline_nearlive_latency.pdf", "Offline/near-live latency figure", "not yet instrumented"),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def generate_paper_exports(repository: Any) -> dict[str, Any]:
    """`repository` is a ScientificResultsRepository. Writes
    `<repository.root>/paper_exports/`: `study_status.json` and
    `paper_readiness.json` for real (from the repository's own real
    aggregators), and `export_manifest.json` recording every other planned
    export as SKIPPED_NO_DATA with its reason, since no real campaign has
    produced source data for any of them yet. Idempotent -- re-running
    overwrites the same files with the current real state, never appends
    duplicates."""
    exports_dir = repository.root / "paper_exports"
    exports_dir.mkdir(parents=True, exist_ok=True)

    study_status = repository.get_study_status()
    atomic_json(exports_dir / "study_status.json", study_status)

    readiness = repository.get_paper_readiness()
    atomic_json(exports_dir / "paper_readiness.json", {"generated_at": _utc_now(), "elements": readiness})

    manifest_entries: list[dict[str, Any]] = [
        {"file": "study_status.json", "status": "GENERATED", "detail": "real, from get_study_status()"},
        {"file": "paper_readiness.json", "status": "GENERATED", "detail": "real, from get_paper_readiness()"},
    ]
    for filename, description, source in _PLANNED_EXPORTS:
        manifest_entries.append({
            "file": filename, "status": "SKIPPED_NO_DATA",
            "detail": description, "would_be_derived_from": source,
        })

    manifest = {
        "schema_version": EXPORT_MANIFEST_SCHEMA_VERSION, "generated_at": _utc_now(),
        "generated_count": sum(1 for e in manifest_entries if e["status"] == "GENERATED"),
        "skipped_count": sum(1 for e in manifest_entries if e["status"] == "SKIPPED_NO_DATA"),
        "entries": manifest_entries,
    }
    atomic_json(exports_dir / "export_manifest.json", manifest)
    return manifest
