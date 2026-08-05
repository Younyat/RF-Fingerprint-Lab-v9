"""ScientificCampaignDeviationRecord builder.

**Correction (post Fase-2 review)**: every deviation now carries a
`classification` (CANDIDATE_EXCLUSION / CAPTURE_EXCLUSION /
PROTOCOL_DEVIATION), and normal per-burst association ambiguity
(MULTIPLE_NATIVE_CALLBACKS) is no longer manufactured as a deviation row at
all here -- it already lives as a `diagnostic_flag` directly on the
affected `ScientificBurstRecord` (see burst_records.py), which is where a
routine, expected candidate-level ambiguity belongs. Fase 2 first shipped
419 such rows as generic "campaign deviations" against a real dataset with
no actual protocol failures; that conflation is what this correction
removes. `PROTOCOL_DEVIATION` is now reserved for genuine departures from
the frozen design: a capture the design expected but that never happened,
duplicated, out of schedule, wrong arm/order/firmware/epoch/channel/
variant, or a split that structurally cannot be trained on.

`make_deviation_record` is exported so `paper_campaign_runner.py` (which
detects the genuinely NEW protocol-deviation types -- CAPTURE_OUT_OF_
SCHEDULE, WRONG_ACQUISITION_ORDER, UNIT_WRONG_ARM, FIRMWARE_MISMATCH,
RECEIVER_EPOCH_NOT_ALLOWED, INTERVENTION_NOT_EXECUTED, EARLY_HOLDOUT_ACCESS,
CHANNEL_OR_VARIANT_MISMATCH) never has to build a second, competing
deviation-record factory.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from app.modules.ble_rffi_studio.contracts import DatasetManifest, SplitManifest

from ..contracts import DeviationClassification, ScientificCampaignDeviationRecord, ScientificCaptureRecord

_NOT_DOCUMENTED_DESIGN_DIMENSIONS = ("pre_post_pairing", "reset_control_pairing", "receiver_epoch_drift", "firmware_configuration_drift", "content_variant_coverage")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_id(*parts: str) -> str:
    return "dev-" + hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()[:24]


def make_deviation_record(
    *, paper_run_id: str, campaign_id: str, classification: DeviationClassification, object_type: str, object_id: str,
    deviation_type: str, description: str, severity: str, blocking: bool, action: str, impact: str,
    source_ids: list[str], observed=None, expected=None, day_id: str | None = None, session_id: str | None = None,
    protocol_rule: str | None = None,
) -> ScientificCampaignDeviationRecord:
    return ScientificCampaignDeviationRecord(
        deviation_id=_new_id(paper_run_id, object_type, object_id, deviation_type), paper_run_id=paper_run_id, campaign_id=campaign_id,
        classification=classification, affected_object_type=object_type, affected_object_id=object_id, day_id=day_id, session_id=session_id,
        deviation_type=deviation_type, description=description, detected_stage="RECORD_BUILD", detected_before_outcome_access=True,
        severity=severity, blocking=blocking, protocol_rule=protocol_rule,
        observed_value=str(observed) if observed is not None else None, expected_value=str(expected) if expected is not None else None,
        action=action, scientific_impact=impact, source_artifact_ids=source_ids,
    )


def build_campaign_deviations(
    *, paper_run_id: str, campaign_id: str, dataset: DatasetManifest, split: SplitManifest,
    capture_records: list[ScientificCaptureRecord],
) -> list[ScientificCampaignDeviationRecord]:
    deviations: list[ScientificCampaignDeviationRecord] = []

    def add(*, classification: DeviationClassification, object_type: str, object_id: str, deviation_type: str, description: str, severity: str, blocking: bool, observed=None, expected=None, action: str, impact: str, source_ids: list[str]) -> None:
        deviations.append(make_deviation_record(
            paper_run_id=paper_run_id, campaign_id=campaign_id, classification=classification, object_type=object_type, object_id=object_id,
            deviation_type=deviation_type, description=description, severity=severity, blocking=blocking, observed=observed, expected=expected,
            action=action, impact=impact, source_ids=source_ids,
        ))

    # Protocol deviations: a capture the dataset expected is missing or duplicated.
    seen: dict[str, int] = {}
    for capture_id in dataset.captures:
        seen[capture_id] = seen.get(capture_id, 0) + 1
    for capture_id, count in seen.items():
        if count > 1:
            add(
                classification="PROTOCOL_DEVIATION", object_type="capture", object_id=capture_id, deviation_type="DUPLICATE_CAPTURE",
                description=f"capture_id {capture_id} appears {count} times in dataset.captures.", severity="HIGH", blocking=True,
                observed=count, expected=1, action="Investigate dataset composition; a capture must be referenced at most once.",
                impact="A duplicated capture inflates its examples' effective weight without new independent evidence.",
                source_ids=[capture_id],
            )
    found_ids = {record.capture_id for record in capture_records}
    for capture_id in dataset.captures:
        if capture_id not in found_ids:
            add(
                classification="PROTOCOL_DEVIATION", object_type="capture", object_id=capture_id, deviation_type="CAPTURE_NOT_FOUND",
                description=f"capture_id {capture_id} is referenced by the dataset but has no CaptureRecord on disk.",
                severity="CRITICAL", blocking=True, action="Re-run capture ingestion or remove the reference from the dataset.",
                impact="This capture's evidence cannot be traced back to raw IQ at all.", source_ids=[capture_id],
            )

    # Capture exclusions: affect one capture's usability, not the design itself.
    for record in capture_records:
        if (record.overflow_count or 0) > 0:
            add(
                classification="CAPTURE_EXCLUSION", object_type="capture", object_id=record.capture_id, deviation_type="OVERFLOW",
                description=f"{record.overflow_count} overflow event(s) recorded during acquisition.", severity="MEDIUM", blocking=False,
                observed=record.overflow_count, expected=0, action="Include in sensitivity analysis excluding doubtful captures.",
                impact="Possible sample loss during this capture; downstream examples may be affected.", source_ids=[record.capture_id],
            )
        if (record.discontinuity_count or 0) > 0:
            add(
                classification="CAPTURE_EXCLUSION", object_type="capture", object_id=record.capture_id, deviation_type="DISCONTINUITY",
                description=f"{record.discontinuity_count} discontinuity event(s) recorded during acquisition.", severity="MEDIUM", blocking=False,
                observed=record.discontinuity_count, expected=0, action="Include in sensitivity analysis excluding doubtful captures.",
                impact="Possible timing gap during this capture; sample-index-based windows may misalign.", source_ids=[record.capture_id],
            )
        if record.metadata_sha256 is None:
            add(
                classification="CAPTURE_EXCLUSION", object_type="capture", object_id=record.capture_id, deviation_type="METADATA_INCOMPLETE",
                description="No capture_manifest.json could be read for this capture.", severity="HIGH", blocking=True,
                action="Re-verify capture ingestion for this capture_id.", impact="Capture provenance cannot be fully confirmed.",
                source_ids=[record.capture_id],
            )

    # Note: normal per-candidate association ambiguity (MULTIPLE_NATIVE_
    # CALLBACKS) is intentionally NOT reported here anymore -- it is a
    # CANDIDATE_EXCLUSION-level, expected occurrence, already visible as a
    # diagnostic_flag on the affected ScientificBurstRecord itself.

    if split.split_status != "READY" or split.leakage_check.status != "PASSED":
        add(
            classification="PROTOCOL_DEVIATION", object_type="split", object_id=f"{split.dataset_id}__{split.dataset_version}__{split.scientific_task}",
            deviation_type="SPLIT_CONFLICT", description=f"split_status={split.split_status}, leakage_check.status={split.leakage_check.status}.",
            severity="CRITICAL", blocking=True, action="No training-eligible split exists for this dataset/task; do not proceed to modeling.",
            impact="Records can still be built for accounting purposes, but no confirmatory analysis may use this split.",
            source_ids=[split.dataset_id],
        )

    # CaptureRecord/ScientificCaptureRecord now HAVE these fields (added in
    # this pass) -- a campaign only gets this note when NONE of its
    # captures actually populated the relevant field, i.e. it predates the
    # paper campaign runner (§8) or was captured outside it. This is no
    # longer "the schema doesn't exist" -- it is "this campaign's real
    # data doesn't have it", a materially different and more precise claim.
    dimension_fields = {
        "pre_post_pairing": "pre_or_post", "reset_control_pairing": "intervention_arm",
        "receiver_epoch_drift": "receiver_epoch", "firmware_configuration_drift": "firmware_hash",
        "content_variant_coverage": "packet_variant",
    }
    for dimension, field_name in dimension_fields.items():
        if all(getattr(record, field_name, None) is None for record in capture_records):
            add(
                classification="PROTOCOL_DEVIATION", object_type="campaign", object_id=campaign_id, deviation_type="NOT_DOCUMENTED_DESIGN_DIMENSION",
                description=f"{dimension}: field '{field_name}' exists on CaptureRecord but is None for every capture in this campaign's dataset.",
                severity="INFO", blocking=False, action="Run captures through paper_campaign_runner.py, which declares this field before capture.",
                impact="This dimension cannot currently contribute to paper-campaign completeness (see PaperCampaignCompletenessResult).",
                source_ids=[],
            )

    return deviations
