"""Sequential receiver-epoch assignment (2026-08-08 correction, point 1): a
qualified receiver epoch is an interval during which BOTH the physical
receiver (receiver_identity_id) AND its qualified acquisition profile
(qualified_acquisition_profile_hash) stay unchanged, AND no session boundary
(reinitialization/reconnection proxy) has been crossed. This requires
sequential knowledge across ALL captures of one identity ordered by real
acquisition time, so it cannot live in capture_stage.py's per-manifest,
single-capture builder -- it is invoked once per identity group, either by
StudioRepository at capture-build time (looking at already-persisted sibling
captures) or by a historical backfill migration.

Reinitialization proxy -- documented limitation, not a real boot/reconnect
signal: no field anywhere in the legacy capture_manifest.json records a USRP
boot/session id, so a time gap since the previous capture of the SAME
identity exceeding RECEIVER_SESSION_GAP_S is treated as "this looks like a
new acquisition session". This threshold is not arbitrary: checked against
every real B200 capture on disk (154 captures, single physical serial
E3R04Z1B2), exactly 9 gaps exceed 1 hour (from ~1.7h up to ~4 days),
consistent with real distinct capture-day boundaries in this campaign's
actual history, not a guess.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

RECEIVER_SESSION_GAP_S = 3600.0

FIRST_CAPTURE_FOR_IDENTITY = "FIRST_CAPTURE_FOR_IDENTITY"
QUALIFIED_PROFILE_CHANGED = "QUALIFIED_PROFILE_CHANGED"
SESSION_GAP_EXCEEDED = "SESSION_GAP_EXCEEDED"
MANIFEST_DECLARED = "MANIFEST_DECLARED"
SAME_SESSION_AS_PREVIOUS = "SAME_SESSION_AS_PREVIOUS"


@dataclass(frozen=True)
class ReceiverEpochInput:
    capture_id: str
    receiver_identity_id: str | None
    qualified_acquisition_profile_hash: str | None
    acquisition_started_at: str  # ISO8601 UTC -- see day_id_source for which manifest field this should be
    declared_receiver_epoch: str | None = None  # manifest-declared override (e.g. paper campaign runner, post-recalibration)


@dataclass(frozen=True)
class ReceiverEpochAssignment:
    capture_id: str
    receiver_epoch: str | None
    receiver_epoch_boundary_reason: str | None


def _parse(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


def assign_receiver_epochs(captures: list[ReceiverEpochInput]) -> list[ReceiverEpochAssignment]:
    """Deterministic and reproducible given the same input set, regardless
    of input order -- internally sorts each identity group by
    acquisition_started_at before assigning epoch boundaries. A capture with
    no receiver_identity_id (no real serial on file) gets
    receiver_epoch=None -- never guessed."""
    by_identity: dict[str, list[ReceiverEpochInput]] = {}
    unresolved: list[ReceiverEpochInput] = []
    for capture in captures:
        if capture.receiver_identity_id is None:
            unresolved.append(capture)
        else:
            by_identity.setdefault(capture.receiver_identity_id, []).append(capture)

    results: list[ReceiverEpochAssignment] = []
    for identity, group in by_identity.items():
        ordered = sorted(group, key=lambda c: _parse(c.acquisition_started_at))
        epoch_index = 0
        current_epoch_id: str | None = None
        previous: ReceiverEpochInput | None = None
        for capture in ordered:
            if capture.declared_receiver_epoch:
                results.append(ReceiverEpochAssignment(capture.capture_id, capture.declared_receiver_epoch, MANIFEST_DECLARED))
                previous = capture
                continue

            reason = SAME_SESSION_AS_PREVIOUS
            if previous is None:
                reason = FIRST_CAPTURE_FOR_IDENTITY
            elif previous.qualified_acquisition_profile_hash != capture.qualified_acquisition_profile_hash:
                reason = QUALIFIED_PROFILE_CHANGED
            else:
                gap_s = (_parse(capture.acquisition_started_at) - _parse(previous.acquisition_started_at)).total_seconds()
                if gap_s > RECEIVER_SESSION_GAP_S:
                    reason = SESSION_GAP_EXCEEDED

            if reason != SAME_SESSION_AS_PREVIOUS:
                epoch_index += 1
                current_epoch_id = f"{identity}-session-{epoch_index:03d}"
            results.append(ReceiverEpochAssignment(capture.capture_id, current_epoch_id, reason))
            previous = capture

    for capture in unresolved:
        results.append(ReceiverEpochAssignment(capture.capture_id, None, None))
    return results
