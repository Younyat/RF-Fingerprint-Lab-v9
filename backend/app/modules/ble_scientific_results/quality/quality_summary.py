"""Fase 2, Section E: descriptive quality summaries. Purely descriptive --
count/mean/median/std/min/max/quartiles/missing count, grouped by the 8
dimensions the user's specification names. No confidence interval, no
p-value, no hypothesis test anywhere in this module (that is Fase 3+,
RQ1-4/S1-S2, explicitly out of scope here).

Operates only on the canonical capture_records/burst_records/
decision_window_records tables Section B already wrote -- never re-reads
ble_rffi_studio directly. Grouping dimensions this repository's real
capture schema cannot populate today (intervention_arm, packet_variant,
receiver_epoch, day_id) collapse to a single NOT_DOCUMENTED group rather
than being silently dropped -- the descriptive table for that dimension
still exists, it just has one honestly-labeled row.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from app.infrastructure.ble.capture.ble_capture_metadata import atomic_json

from .._shared_pandas import fillna_not_documented, read_table

GROUP_DIMENSIONS = ["physical_unit_id", "day_id", "session_id", "pre_or_post", "intervention_arm", "channel", "packet_variant", "receiver_epoch"]

# Only columns that genuinely exist with real, non-fabricated values on the
# canonical records qualify here. SNR/noise/signal-power/clipping/near-zero/
# occupied-bandwidth/frequency-offset have no source at capture OR burst
# granularity in ble_rffi_studio today (see capture_records.py and
# burst_records.py's own not_documented_fields) -- they are deliberately
# absent from this list rather than described from a column of nulls.
CAPTURE_NUMERIC_FIELDS = ["duration_s", "observed_samples", "expected_samples", "overflow_count", "discontinuity_count"]
WINDOW_NUMERIC_FIELDS = ["candidate_burst_count", "crc_valid_burst_count", "target_associated_burst_count", "eligible_burst_count"]


def _describe(frame: pd.DataFrame, group_cols: list[str], value_cols: list[str]) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    present_group_cols = [c for c in group_cols if c in frame.columns]
    present_value_cols = [c for c in value_cols if c in frame.columns]
    if not present_group_cols or not present_value_cols:
        return []
    filled = fillna_not_documented(frame, present_group_cols)
    rows: list[dict[str, Any]] = []
    grouped = filled.groupby(present_group_cols, dropna=False)
    for group_key, group_frame in grouped:
        if not isinstance(group_key, tuple):
            group_key = (group_key,)
        for value_col in present_value_cols:
            series = pd.to_numeric(group_frame[value_col], errors="coerce")
            non_null = series.dropna()
            row = dict(zip(present_group_cols, group_key))
            row["field"] = value_col
            row["n"] = int(len(group_frame))
            row["missing_count"] = int(series.isna().sum())
            if non_null.empty:
                row.update({"mean": None, "median": None, "std": None, "min": None, "max": None, "q1": None, "q3": None})
            else:
                row.update({
                    "mean": float(non_null.mean()), "median": float(non_null.median()),
                    "std": float(non_null.std()) if len(non_null) > 1 else 0.0,
                    "min": float(non_null.min()), "max": float(non_null.max()),
                    "q1": float(non_null.quantile(0.25)), "q3": float(non_null.quantile(0.75)),
                })
            rows.append(row)
    return rows


def build_quality_summary(*, run_dir: Path) -> dict[str, Any]:
    records_dir = run_dir / "01_inputs" / "canonical_records"
    quality_dir = run_dir / "04_quality"
    quality_dir.mkdir(parents=True, exist_ok=True)

    captures = read_table(records_dir, "capture_records")
    bursts = read_table(records_dir, "burst_records")
    windows = read_table(records_dir, "decision_window_records")

    summary_rows = _describe(captures, GROUP_DIMENSIONS, CAPTURE_NUMERIC_FIELDS)
    unit_day_rows = _describe(captures, ["physical_unit_id", "day_id"], CAPTURE_NUMERIC_FIELDS)
    window_rows = _describe(windows, GROUP_DIMENSIONS, WINDOW_NUMERIC_FIELDS)

    # Association summary: real, checkable fields -- CRC-valid rate,
    # association coverage, association timing residual (real per-burst
    # fields from packet_association_ledger.jsonl, via ScientificBurstRecord).
    association_rows: list[dict[str, Any]] = []
    if not bursts.empty:
        total = len(bursts)
        crc_valid = int(bursts["burst_class"].isin(["CRC_VALID_PACKET", "TARGET_ASSOCIATED_PACKET"]).sum())
        associated = int(bursts["association_status"].notna().sum())
        residuals = pd.to_numeric(bursts.get("association_time_residual_ms"), errors="coerce").dropna()
        association_rows.append({
            "capture_count": int(bursts["capture_id"].nunique()), "burst_count": total,
            "crc_valid_rate": (crc_valid / total) if total else None,
            "association_coverage": (associated / total) if total else None,
            "association_time_residual_ms_mean": float(residuals.mean()) if not residuals.empty else None,
            "association_time_residual_ms_n": int(len(residuals)),
        })

    pd.DataFrame(summary_rows).to_csv(quality_dir / "quality_summary.csv", index=False)
    atomic_json(quality_dir / "quality_summary.json", {"capture_field_summary": summary_rows, "window_field_summary": window_rows})
    pd.DataFrame(unit_day_rows).to_csv(quality_dir / "quality_by_unit_day.csv", index=False)
    pd.DataFrame(association_rows).to_csv(quality_dir / "association_summary.csv", index=False)

    return {"capture_field_summary": summary_rows, "window_field_summary": window_rows, "unit_day_summary": unit_day_rows, "association_summary": association_rows}
