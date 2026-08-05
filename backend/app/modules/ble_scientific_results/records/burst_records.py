"""Fase 2, B.3: ScientificBurstRecord builder.

One burst = one row of `candidate_manifest.jsonl` (the pipeline's own real
RF-burst unit -- verified via direct research this session against
`ble_offline_replay.py`, not assumed). Its decode/association details, when
present, come from the matching row of `packet_association_ledger.jsonl`
(same `candidate_id`). Fields with genuinely no source anywhere in either
artifact (sync score, CFO fit quality, competing energy, clipping/
discontinuity overlap, edge margin -- confirmed absent by direct code
research, see docs/ble/SCIENTIFIC_STATUS.md and this module's own tests)
are None + listed in not_documented_fields, never guessed.

burst_class differentiates RF_ACTIVITY / BLE_SYNC_CANDIDATE /
CRC_VALID_PACKET / TARGET_ASSOCIATED_PACKET -- deliberately not E0-E6,
which belong to the unrelated rf_experiment_lab/e6_oracle_style taxonomy.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.modules.ble_rffi_studio.contracts import ExampleRecord

from ..contracts import BurstClass, ScientificBurstRecord

# Confirmed structurally absent from candidate_manifest.jsonl and
# packet_association_ledger.jsonl for every real capture in this
# repository (verified this session, not assumed) -- no sync score, CFO
# fit quality, competing-energy, clipping/discontinuity-overlap, or edge-
# margin field exists at the burst/candidate granularity anywhere in
# ble_rffi_studio's real pipeline.
_STRUCTURALLY_ABSENT_BURST_FIELDS = (
    "synchronization_score", "symbol_phase", "frequency_offset_hz", "frequency_fit_quality",
    "competing_energy", "clipping_overlap", "discontinuity_overlap", "edge_margin_samples", "burst_snr_db",
    "burst_start_utc_estimate", "detector_version", "native_event_id", "association_cost", "burst_quality",
)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _burst_class(candidate: dict, ledger_row: dict | None, physical_unit_id: str | None) -> BurstClass:
    """CRC validity comes from the candidate's OWN crc_status
    (candidate_manifest.jsonl) -- never gated on a ledger row existing.
    packet_association_ledger.jsonl is a separate artifact that adds
    decode/association DETAIL when present; its absence does not demote a
    genuinely CRC-valid candidate back to BLE_SYNC_CANDIDATE."""
    if candidate.get("processing_status") != "PROCESSED":
        return "RF_ACTIVITY"
    if candidate.get("crc_status") != "VALID":
        return "BLE_SYNC_CANDIDATE"
    if physical_unit_id is not None:
        return "TARGET_ASSOCIATED_PACKET"
    return "CRC_VALID_PACKET"


def build_burst_records(*, capture_id: str, replay_dir: Path | None, examples: list[ExampleRecord], association_policy_hash: str | None) -> list[ScientificBurstRecord]:
    if replay_dir is None:
        return []

    candidates = _read_jsonl(replay_dir / "candidate_manifest.jsonl")
    ledger_by_candidate = {row["candidate_id"]: row for row in _read_jsonl(replay_dir / "packet_association_ledger.jsonl") if row.get("candidate_id")}
    example_by_candidate = {example.candidate_id: example for example in examples}

    records: list[ScientificBurstRecord] = []
    for candidate in candidates:
        candidate_id = candidate.get("candidate_id")
        ledger_row = ledger_by_candidate.get(candidate_id)
        example = example_by_candidate.get(candidate_id)
        physical_unit_id = example.physical_unit_id if example else None

        not_documented = list(_STRUCTURALLY_ABSENT_BURST_FIELDS)
        source_artifact_ids = [candidate_id] if candidate_id else []
        if ledger_row:
            source_artifact_ids.append(ledger_row.get("packet_id", ""))
        if example:
            source_artifact_ids.append(example.example_id)

        eligible = candidate.get("processing_status") == "PROCESSED" and candidate.get("crc_status") == "VALID"
        exclusion_reasons: list[str] = []
        if candidate.get("processing_status") != "PROCESSED":
            exclusion_reasons.append(f"PROCESSING_{candidate.get('processing_status') or 'UNKNOWN'}")
        if candidate.get("crc_status") not in ("VALID", None) or (candidate.get("processing_status") == "PROCESSED" and candidate.get("crc_status") != "VALID"):
            exclusion_reasons.append("NO_CRC_VALID_PACKET")
        if ledger_row and ledger_row.get("association_rejection_reason"):
            exclusion_reasons.append(str(ledger_row["association_rejection_reason"]))

        records.append(ScientificBurstRecord(
            burst_id=candidate.get("burst_id") or candidate_id, capture_id=capture_id,
            burst_class=_burst_class(candidate, ledger_row, physical_unit_id),
            sample_start=candidate.get("start_sample", 0), sample_end=candidate.get("end_sample", 0),
            burst_start_utc_estimate=None, decision_window_id=candidate_id, candidate_group_id=candidate_id,
            detector_version=None,
            synchronization_status="LOCKED" if candidate.get("processing_status") == "PROCESSED" else "NOT_LOCKED",
            crc_status=candidate.get("crc_status"),
            decoded_pdu_type=(ledger_row or {}).get("pdu_type"), decoded_adva=(ledger_row or {}).get("advertiser_address_canonical"),
            decoded_payload_hash=(ledger_row or {}).get("payload_sha256"),
            native_event_id=None, association_status=(ledger_row or {}).get("association_strength"),
            association_time_residual_ms=(ledger_row or {}).get("time_delta_ms"), association_cost=None,
            association_policy_hash=association_policy_hash,
            label_authority="EvidenceStage.physical_unit_id" if physical_unit_id else None,
            eligible=eligible, exclusion_reason_codes=exclusion_reasons, source_artifact_ids=source_artifact_ids,
            not_documented_fields=sorted(set(not_documented)),
        ))
    return records
