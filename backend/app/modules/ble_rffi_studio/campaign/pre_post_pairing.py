"""RQ3 real PRE/POST pairing (2026-08-08): pairs a physical unit's PRE and
POST captures within one device-day and one intervention_arm (RESET or
CONTROL), invalidating a pair whose two captures do not share a receiver_epoch
or (when the caller is about to analyze them together) a qualified
preprocessing profile -- comparing PRE against POST is only meaningful when
nothing about the receiver/analysis pipeline itself changed between them.

day_id/intervention_arm/pre_or_post/receiver_epoch are the same CaptureRecord
fields P0's "adapt the protocol" work already made available (day_id/
receiver_epoch auto-derived where possible -- see acquisition/capture_stage.py;
intervention_arm/pre_or_post remain operator-declared only, 0/150 real
captures populate them today, matching campaign_period's own documented gap).
This module is the real, tested MECHANISM; no real campaign has produced
PRE/POST pairs yet, honestly reflected by build_pre_post_pairs returning []
against every real capture on disk today.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..contracts import CaptureRecord

InterventionArm = str  # "RESET" | "CONTROL" -- CaptureRecord.intervention_arm is a free string field, not yet a Literal (see its docstring)


@dataclass(frozen=True)
class PrePostPair:
    physical_unit_id: str
    day_id: str
    intervention_arm: InterventionArm
    pre_capture_id: str
    post_capture_id: str
    pre_receiver_epoch: str | None
    post_receiver_epoch: str | None
    valid: bool
    invalidation_reason: str | None


def _unit_id(capture: CaptureRecord) -> str | None:
    # target_reference_id (operator-declared, TARGET_DEVICE_ON captures) is
    # preferred; isolation_declared_physical_unit_id covers the
    # physically-isolated-session case. Never the address-resolved
    # physical_unit_id (CaptureRecord does not carry one -- only
    # ExampleRecord does, post-evidence -- see contracts/capture.py).
    return capture.target_reference_id or capture.isolation_declared_physical_unit_id


def build_pre_post_pairs(
    captures: list[CaptureRecord], *, preprocessing_profile_by_capture_id: dict[str, str] | None = None,
) -> list[PrePostPair]:
    """Groups by (physical_unit_id, day_id, intervention_arm), requiring ALL
    FOUR of unit/day_id/intervention_arm/pre_or_post to be genuinely declared
    -- a capture missing any of them is silently excluded from pairing
    (never guessed). A group must resolve to exactly one PRE and one POST
    capture; anything else (0, or more than 1 of either) is recorded as an
    explicitly invalid pair only when at least one PRE and one POST both
    exist (so the ambiguity is auditable), otherwise skipped as simply
    incomplete."""
    groups: dict[tuple[str, str, str], list[CaptureRecord]] = {}
    for capture in captures:
        unit_id = _unit_id(capture)
        if not (unit_id and capture.day_id and capture.intervention_arm and capture.pre_or_post):
            continue
        groups.setdefault((unit_id, capture.day_id, capture.intervention_arm), []).append(capture)

    preprocessing_profile_by_capture_id = preprocessing_profile_by_capture_id or {}
    pairs: list[PrePostPair] = []
    for (unit_id, day_id, arm), group in sorted(groups.items()):
        pres = [c for c in group if c.pre_or_post == "PRE"]
        posts = [c for c in group if c.pre_or_post == "POST"]
        if len(pres) != 1 or len(posts) != 1:
            if pres and posts:
                pairs.append(PrePostPair(
                    physical_unit_id=unit_id, day_id=day_id, intervention_arm=arm,
                    pre_capture_id=pres[0].capture_id, post_capture_id=posts[0].capture_id,
                    pre_receiver_epoch=pres[0].receiver_epoch, post_receiver_epoch=posts[0].receiver_epoch,
                    valid=False, invalidation_reason=f"AMBIGUOUS_PRE_OR_POST_COUNT:{len(pres)}_pre,{len(posts)}_post",
                ))
            continue

        pre, post = pres[0], posts[0]
        invalidation_reason = None
        if pre.receiver_epoch is None or post.receiver_epoch is None:
            invalidation_reason = "RECEIVER_EPOCH_NOT_DOCUMENTED_ON_ONE_OR_BOTH_CAPTURES"
        elif pre.receiver_epoch != post.receiver_epoch:
            invalidation_reason = f"RECEIVER_EPOCH_CHANGED_BETWEEN_PRE_AND_POST:{pre.receiver_epoch}!={post.receiver_epoch}"
        else:
            pre_profile = preprocessing_profile_by_capture_id.get(pre.capture_id)
            post_profile = preprocessing_profile_by_capture_id.get(post.capture_id)
            if preprocessing_profile_by_capture_id and pre_profile != post_profile:
                invalidation_reason = f"QUALIFIED_PREPROCESSING_PROFILE_CHANGED_BETWEEN_PRE_AND_POST:{pre_profile}!={post_profile}"

        pairs.append(PrePostPair(
            physical_unit_id=unit_id, day_id=day_id, intervention_arm=arm,
            pre_capture_id=pre.capture_id, post_capture_id=post.capture_id,
            pre_receiver_epoch=pre.receiver_epoch, post_receiver_epoch=post.receiver_epoch,
            valid=invalidation_reason is None, invalidation_reason=invalidation_reason,
        ))
    return pairs
