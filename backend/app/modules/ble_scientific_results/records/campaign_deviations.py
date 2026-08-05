"""Fase 2, B.5: ScientificCampaignDeviationRecord builder.

Each deviation is computed from a real, concrete comparison against
already-built records/manifests -- never fabricated, never silently
dropped. Deviation types this builder can genuinely detect from current
real artifacts: CAPTURE_NOT_FOUND, DUPLICATE_CAPTURE, OVERFLOW,
DISCONTINUITY, METADATA_INCOMPLETE, AMBIGUOUS_ASSOCIATION, SPLIT_CONFLICT.
Design dimensions the user's specification also lists (pre/post pairing,
reset/control pairing, receiver-epoch drift, firmware/configuration drift,
content-variant coverage) have no source field anywhere in
ble_rffi_studio's real schema today (see capture_records.py's
_STRUCTURALLY_ABSENT_CAPTURE_FIELDS) -- rather than fabricate a per-object
deviation for a field that does not exist, ONE campaign-level
NOT_DOCUMENTED_DESIGN_DIMENSION deviation is emitted per such dimension,
honestly stating it cannot be checked, never silently omitted.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.modules.ble_rffi_studio.contracts import DatasetManifest, SplitManifest

from ..contracts import ScientificCampaignDeviationRecord, ScientificCaptureRecord

_NOT_DOCUMENTED_DESIGN_DIMENSIONS = ("pre_post_pairing", "reset_control_pairing", "receiver_epoch_drift", "firmware_configuration_drift", "content_variant_coverage")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_id(*parts: str) -> str:
    import hashlib
    return "dev-" + hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()[:24]


def build_campaign_deviations(
    *, paper_run_id: str, campaign_id: str, dataset: DatasetManifest, split: SplitManifest,
    capture_records: list[ScientificCaptureRecord], ambiguous_association_burst_ids: list[str],
) -> list[ScientificCampaignDeviationRecord]:
    deviations: list[ScientificCampaignDeviationRecord] = []
    now = _utc_now()

    def add(*, object_type: str, object_id: str, deviation_type: str, description: str, severity: str, blocking: bool, observed=None, expected=None, action: str, impact: str, source_ids: list[str]) -> None:
        deviations.append(ScientificCampaignDeviationRecord(
            deviation_id=_new_id(paper_run_id, object_type, object_id, deviation_type), paper_run_id=paper_run_id, campaign_id=campaign_id,
            affected_object_type=object_type, affected_object_id=object_id, deviation_type=deviation_type, description=description,
            detected_stage="RECORD_BUILD", detected_before_outcome_access=True, severity=severity, blocking=blocking,
            observed_value=str(observed) if observed is not None else None, expected_value=str(expected) if expected is not None else None,
            action=action, scientific_impact=impact, source_artifact_ids=source_ids,
        ))

    # Captura prevista no encontrada / captura duplicada.
    seen: dict[str, int] = {}
    for capture_id in dataset.captures:
        seen[capture_id] = seen.get(capture_id, 0) + 1
    for capture_id, count in seen.items():
        if count > 1:
            add(
                object_type="capture", object_id=capture_id, deviation_type="DUPLICATE_CAPTURE",
                description=f"capture_id {capture_id} appears {count} times in dataset.captures.", severity="HIGH", blocking=True,
                observed=count, expected=1, action="Investigate dataset composition; a capture must be referenced at most once.",
                impact="A duplicated capture inflates its examples' effective weight without new independent evidence.",
                source_ids=[capture_id],
            )
    found_ids = {record.capture_id for record in capture_records}
    for capture_id in dataset.captures:
        if capture_id not in found_ids:
            add(
                object_type="capture", object_id=capture_id, deviation_type="CAPTURE_NOT_FOUND",
                description=f"capture_id {capture_id} is referenced by the dataset but has no CaptureRecord on disk.",
                severity="CRITICAL", blocking=True, action="Re-run capture ingestion or remove the reference from the dataset.",
                impact="This capture's evidence cannot be traced back to raw IQ at all.", source_ids=[capture_id],
            )

    # Overflow / discontinuity / metadata incomplete, per capture record.
    for record in capture_records:
        if (record.overflow_count or 0) > 0:
            add(
                object_type="capture", object_id=record.capture_id, deviation_type="OVERFLOW",
                description=f"{record.overflow_count} overflow event(s) recorded during acquisition.", severity="MEDIUM", blocking=False,
                observed=record.overflow_count, expected=0, action="Include in sensitivity analysis excluding doubtful captures.",
                impact="Possible sample loss during this capture; downstream examples may be affected.", source_ids=[record.capture_id],
            )
        if (record.discontinuity_count or 0) > 0:
            add(
                object_type="capture", object_id=record.capture_id, deviation_type="DISCONTINUITY",
                description=f"{record.discontinuity_count} discontinuity event(s) recorded during acquisition.", severity="MEDIUM", blocking=False,
                observed=record.discontinuity_count, expected=0, action="Include in sensitivity analysis excluding doubtful captures.",
                impact="Possible timing gap during this capture; sample-index-based windows may misalign.", source_ids=[record.capture_id],
            )
        if record.metadata_sha256 is None:
            add(
                object_type="capture", object_id=record.capture_id, deviation_type="METADATA_INCOMPLETE",
                description="No capture_manifest.json could be read for this capture.", severity="HIGH", blocking=True,
                action="Re-verify capture ingestion for this capture_id.", impact="Capture provenance cannot be fully confirmed.",
                source_ids=[record.capture_id],
            )

    for burst_id in ambiguous_association_burst_ids:
        add(
            object_type="burst", object_id=burst_id, deviation_type="AMBIGUOUS_ASSOCIATION",
            description="Native/SDR association was AMBIGUOUS (MULTIPLE_NATIVE_CALLBACKS) for this burst.", severity="LOW", blocking=False,
            action="Excluded from STRONG-association-dependent analyses by association_status already.",
            impact="This burst cannot contribute independently-corroborated label evidence.", source_ids=[burst_id],
        )

    if split.split_status != "READY" or split.leakage_check.status != "PASSED":
        add(
            object_type="split", object_id=f"{split.dataset_id}__{split.dataset_version}__{split.scientific_task}", deviation_type="SPLIT_CONFLICT",
            description=f"split_status={split.split_status}, leakage_check.status={split.leakage_check.status}.", severity="CRITICAL", blocking=True,
            action="No training-eligible split exists for this dataset/task; do not proceed to modeling.",
            impact="Records can still be built for accounting purposes, but no confirmatory analysis may use this split.",
            source_ids=[split.dataset_id],
        )

    for dimension in _NOT_DOCUMENTED_DESIGN_DIMENSIONS:
        add(
            object_type="campaign", object_id=campaign_id, deviation_type="NOT_DOCUMENTED_DESIGN_DIMENSION",
            description=f"{dimension}: no field exists anywhere in ble_rffi_studio's real capture/example schema to check this dimension.",
            severity="INFO", blocking=False, action="Requires a future capture-schema extension before this dimension can be assessed.",
            impact="This dimension cannot currently contribute to paper-campaign completeness (see PaperCampaignCompletenessResult).",
            source_ids=[],
        )

    return deviations
