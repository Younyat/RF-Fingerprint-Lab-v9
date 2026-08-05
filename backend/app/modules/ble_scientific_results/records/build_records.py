"""Fase 2, B.1: orchestrates the four canonical record builders for one
paper_run_id and writes them to `01_inputs/canonical_records/` as both
`.parquet` (for pandas-based downstream aggregation in campaign_accounting/
quality_summary) and `.json` (for direct inspection/drill-down from the
frontend). Read-only over ble_rffi_studio -- nothing here writes back to
`storage/ble_rffi_studio/` or `storage/ble/iq_captures/`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pandas as pd

from app.infrastructure.ble.capture.ble_capture_metadata import atomic_json
from app.modules.ble_rffi_studio.contracts import CaptureRecord, DatasetManifest, ExampleRecord, SplitManifest

from ..contracts import RecordBuildResult, ScientificBurstRecord, ScientificCampaignDeviationRecord, ScientificCaptureRecord, ScientificDecisionWindowRecord
from .burst_records import build_burst_records
from .campaign_deviations import build_campaign_deviations
from .capture_records import build_capture_record
from .decision_window_records import build_decision_window_records
from .iq_resolution import resolve_replay_dir

ProgressHook = Callable[[str, float, str], None] | None


def _write_table(records: list, path_stem: Path) -> None:
    payload = [record.model_dump(mode="json") for record in records]
    atomic_json(path_stem.with_suffix(".json"), payload)
    frame = pd.DataFrame(payload)
    frame.to_parquet(path_stem.with_suffix(".parquet"), index=False)


def build_records(
    *, paper_run_id: str, protocol_id: str, campaign_id: str, association_policy_hash: str,
    dataset: DatasetManifest, split: SplitManifest, run_dir: Path, ble_root: Path, legacy_capture_root: Path,
    load_capture: Callable[[str], CaptureRecord | None], load_examples: Callable[[str], list[ExampleRecord]],
    progress: ProgressHook = None,
) -> RecordBuildResult:
    output_dir = run_dir / "01_inputs" / "canonical_records"
    output_dir.mkdir(parents=True, exist_ok=True)

    capture_records: list[ScientificCaptureRecord] = []
    burst_records: list[ScientificBurstRecord] = []
    window_records: list[ScientificDecisionWindowRecord] = []
    captures_without_replay: list[str] = []
    ambiguous_association_burst_ids: list[str] = []

    total = max(len(dataset.captures), 1)
    for index, capture_id in enumerate(dataset.captures):
        if progress:
            progress("capture_and_burst_records", index / total, f"Building records for capture {index + 1}/{total}")
        capture = load_capture(capture_id)
        if capture is None:
            continue
        examples = load_examples(capture_id)
        capture_records.append(build_capture_record(
            paper_run_id=paper_run_id, protocol_id=protocol_id, campaign_id=campaign_id, capture=capture,
            examples=examples, dataset=dataset, split=split, ble_root=ble_root, legacy_capture_root=legacy_capture_root,
        ))

        replay_dir = resolve_replay_dir(legacy_capture_root, capture_id)
        if replay_dir is None:
            captures_without_replay.append(capture_id)
        bursts = build_burst_records(capture_id=capture_id, replay_dir=replay_dir, examples=examples, association_policy_hash=association_policy_hash)
        burst_records.extend(bursts)
        window_records.extend(build_decision_window_records(capture_id=capture_id, bursts=bursts))
        ambiguous_association_burst_ids.extend(
            burst.burst_id for burst in bursts
            if "MULTIPLE_NATIVE_CALLBACKS" in burst.exclusion_reason_codes or "AMBIGUOUS" == burst.association_status
        )

    if progress:
        progress("campaign_deviations", 0.9, "Detecting campaign deviations")
    deviation_records = build_campaign_deviations(
        paper_run_id=paper_run_id, campaign_id=campaign_id, dataset=dataset, split=split,
        capture_records=capture_records, ambiguous_association_burst_ids=ambiguous_association_burst_ids,
    )

    if progress:
        progress("writing_tables", 0.95, "Writing canonical record tables")
    _write_table(capture_records, output_dir / "capture_records")
    _write_table(burst_records, output_dir / "burst_records")
    _write_table(window_records, output_dir / "decision_window_records")
    _write_table(deviation_records, output_dir / "campaign_deviations")

    result = RecordBuildResult(
        paper_run_id=paper_run_id, generated_at=_utc_now(),
        capture_record_count=len(capture_records), burst_record_count=len(burst_records),
        decision_window_record_count=len(window_records), campaign_deviation_count=len(deviation_records),
        captures_without_replay=captures_without_replay,
    )
    atomic_json(output_dir / "build_result.json", result.model_dump(mode="json"))
    if progress:
        progress("done", 1.0, "Canonical records built")
    return result


def _utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
