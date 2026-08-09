"""RQ4 orchestration: ties field_mapping.py's pure sample-range math to real,
already-decoded packets. pdu_type_name comes from the SAME
packet_association_ledger.jsonl EvidenceStage already reads (this row's
"pdu_type" field, itself sourced from the decoder's pdu_type_name -- see
ble_offline_replay.py's _build_ledger) -- read directly here rather than
adding a new field to ExampleRecord, since packet_content is a derived,
on-demand artifact, not part of the evidence identity/labeling schema.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from app.infrastructure.ble.capture.ble_offline_replay import read_jsonl

from ..contracts import ExampleRecord
from .field_mapping import AnalyticalRegion, derive_packet_content_variants


def resolve_latest_replay_dir(legacy_capture_root: Path, capture_id: str) -> Path | None:
    replays_dir = legacy_capture_root / capture_id / "offline_replays"
    if not replays_dir.is_dir():
        return None
    ledgers = sorted(replays_dir.glob("*/packet_association_ledger.jsonl"))
    return ledgers[-1].parent if ledgers else None


def load_pdu_type_by_packet_id(replay_dir: Path) -> dict[str, str | None]:
    ledger_path = replay_dir / "packet_association_ledger.jsonl"
    return {row["packet_id"]: row.get("pdu_type") for row in read_jsonl(ledger_path) if row.get("packet_id")}


def build_packet_content_variants_for_examples(
    examples: list[ExampleRecord], *, legacy_capture_root: Path, capture_iq_paths: dict[str, Path],
) -> dict[str, dict[AnalyticalRegion, np.ndarray | None]]:
    """Real, end-to-end RQ4 derivation over a list of already-evidenced
    examples: for each, loads its own IQ window from the ORIGINAL capture IQ
    file (capture_iq_paths -- the same caller-resolved capture_id -> path
    mapping TrainingService/OfflineInferenceService already take, never
    re-derived from a downstream artifact), looks up its real pdu_type from
    the same capture's packet_association_ledger.jsonl (under
    legacy_capture_root), and returns FULL_BURST/ADVA_MASKED/PRE_PDU. An
    example whose capture has no resolvable replay/ledger yields
    pdu_type_name=None -- ADVA_MASKED becomes None (unknown layout),
    FULL_BURST/PRE_PDU are still always real."""
    from ..preprocessing import load_iq_window

    pdu_type_cache: dict[str, dict[str, str | None]] = {}
    results: dict[str, dict[AnalyticalRegion, np.ndarray | None]] = {}

    for example in examples:
        if example.capture_id not in pdu_type_cache:
            replay_dir = resolve_latest_replay_dir(legacy_capture_root, example.capture_id)
            pdu_type_cache[example.capture_id] = load_pdu_type_by_packet_id(replay_dir) if replay_dir else {}
        pdu_type_name = pdu_type_cache[example.capture_id].get(example.packet_id)

        window = load_iq_window(capture_iq_paths[example.capture_id], example.iq_start_sample, example.iq_end_sample)
        results[example.example_id] = derive_packet_content_variants(
            iq_window=window, iq_start_sample=example.iq_start_sample, sample_rate_sps=float(example.sample_rate_sps), pdu_type_name=pdu_type_name,
        )
    return results
