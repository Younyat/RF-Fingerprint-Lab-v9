"""Fase 2, B.4: ScientificDecisionWindowRecord builder.

DESIGN DECISION (explicit, not a discovered fact -- documented here and in
the Fase 2 delivery report): ble_rffi_studio has no persisted "decision
window" artifact of its own. The most granular real unit its pipeline
already treats as one independently-decodable segment is exactly the
candidate segment (`candidate_manifest.jsonl` row, [start_sample,
end_sample)). This builder therefore defines one ScientificDecisionWindowRecord
per candidate -- `decision_window_id == candidate_id` -- and its
`selected_burst_ids` is the (0 or 1, in every real capture inspected so
far) burst(s) whose `candidate_group_id` matches. If a future phase
introduces a genuine multi-burst temporal windowing concept, this rule
should be revisited; it is not assumed to be final.

No score/threshold/predicted_class/model decision field exists on this
record -- that is Fase 3+ territory (RQ1-4/S1-S2), explicitly out of scope
here.
"""
from __future__ import annotations

from ..contracts import ScientificBurstRecord, ScientificDecisionWindowRecord


def build_decision_window_records(*, capture_id: str, bursts: list[ScientificBurstRecord], minimum_required_bursts: int | None = None) -> list[ScientificDecisionWindowRecord]:
    records: list[ScientificDecisionWindowRecord] = []
    for index, burst in enumerate(bursts):
        crc_valid = burst.burst_class in ("CRC_VALID_PACKET", "TARGET_ASSOCIATED_PACKET")
        target_associated = burst.burst_class == "TARGET_ASSOCIATED_PACKET"
        eligible = burst.eligible is True

        active = burst.burst_class != "RF_ACTIVITY"
        required = minimum_required_bursts if minimum_required_bursts is not None else 1
        eligible_count = 1 if eligible else 0
        decision_eligible = eligible_count >= required
        ineligibility_reasons: list[str] = [] if decision_eligible else ["BELOW_MINIMUM_REQUIRED_BURSTS"]

        records.append(ScientificDecisionWindowRecord(
            decision_window_id=burst.decision_window_id, capture_id=capture_id, window_index=index,
            window_start_sample=burst.sample_start, window_end_sample=burst.sample_end,
            window_start_utc=None, window_end_utc=None, active=active,
            candidate_burst_count=1, crc_valid_burst_count=1 if crc_valid else 0,
            target_associated_burst_count=1 if target_associated else 0, eligible_burst_count=eligible_count,
            selected_burst_ids=[burst.burst_id] if eligible else [],
            selection_policy_hash=burst.association_policy_hash, minimum_required_bursts=required,
            decision_eligible=decision_eligible, ineligibility_reason_codes=ineligibility_reasons,
            not_documented_fields=["window_start_utc", "window_end_utc"],
        ))
    return records
