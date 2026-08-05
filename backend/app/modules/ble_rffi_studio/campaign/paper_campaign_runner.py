"""Minimal paper-campaign runner (user's explicit request: "no otra
interfaz compleja"). A script/service, not a new UI: reads a frozen
schedule, refuses to execute anything not on it, and links every real
capture back to the `planned_capture_id` that was declared before it ran.

Reuses `CampaignOrchestrator.run_session()` for the actual capture (real
hardware, real B200 lease, real Evidence Stage trigger) unchanged -- this
module never talks to the SDR/arbiter/capture worker directly, and never
duplicates that logic. The declared schedule metadata (day_id, pre_or_post,
intervention_arm, ...) is written onto the resulting capture's
`capture_manifest.json` immediately after the real capture completes, using
ONLY values already frozen in the schedule before the capture was issued --
never inferred, never reconstructed from anything observed after the fact.

Off-schedule attempts are rejected and recorded as a real
PROTOCOL_DEVIATION (reusing `ble_scientific_results.records.
campaign_deviations.make_deviation_record` -- never a second, competing
deviation format).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.infrastructure.ble.capture.ble_capture_metadata import atomic_json

from ..contracts import CaptureRecord, PaperCampaignSchedule, PaperCampaignScheduleEntry

ProgressHook = Callable[[str, float, str], None] | None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class PaperCampaignSchedulingError(Exception):
    pass


class PaperCampaignRunner:
    def __init__(self, *, storage_root: Path, legacy_capture_root: Path, campaign_orchestrator: Any = None) -> None:
        self.storage_root = storage_root
        self.legacy_capture_root = legacy_capture_root
        self.campaign_orchestrator = campaign_orchestrator
        self.storage_root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Schedule freeze / load
    # ------------------------------------------------------------------

    def _schedule_dir(self, schedule_id: str) -> Path:
        if any(part in schedule_id for part in ("/", "\\", "..")):
            raise ValueError("INVALID_SCHEDULE_ID")
        return self.storage_root / "paper_campaign" / "schedules" / schedule_id

    def _existing_versions(self, schedule_id: str) -> list[int]:
        directory = self._schedule_dir(schedule_id)
        if not directory.is_dir():
            return []
        versions = []
        for path in directory.glob("*.json"):
            try:
                versions.append(int(path.stem))
            except ValueError:
                continue
        return versions

    def freeze_schedule(self, *, schedule_id: str, protocol_id: str, entries: list[dict], qualification_only: bool = False) -> PaperCampaignSchedule:
        entry_models = [PaperCampaignScheduleEntry(**entry) for entry in entries]
        planned_ids = [entry.planned_capture_id for entry in entry_models]
        if len(planned_ids) != len(set(planned_ids)):
            raise PaperCampaignSchedulingError(f"DUPLICATE_PLANNED_CAPTURE_ID_IN_SCHEDULE:{schedule_id}")

        next_version = (max(self._existing_versions(schedule_id), default=0)) + 1
        schedule = PaperCampaignSchedule(
            schedule_id=schedule_id, schedule_version=next_version, protocol_id=protocol_id,
            entries=entry_models, qualification_only=qualification_only, frozen_at=utc_now(),
        )
        atomic_json(self._schedule_dir(schedule_id) / f"{next_version}.json", schedule.model_dump(mode="json"))
        return schedule

    def load_schedule(self, schedule_id: str, version: int | None = None) -> PaperCampaignSchedule:
        target_version = version or max(self._existing_versions(schedule_id), default=None)
        if target_version is None:
            raise FileNotFoundError(f"SCHEDULE_NOT_FOUND:{schedule_id}")
        path = self._schedule_dir(schedule_id) / f"{target_version}.json"
        return PaperCampaignSchedule.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def _save_schedule(self, schedule: PaperCampaignSchedule) -> None:
        # A schedule's own per-entry `executed`/`executed_capture_id` is the
        # one exception to "never edit a frozen object" -- it is bookkeeping
        # about what has run, not a redeclaration of the plan itself. Still
        # written to the SAME version file (never a silent new schedule
        # version) so "what was planned" and "what has run against it" stay
        # visibly the same document.
        atomic_json(self._schedule_dir(schedule.schedule_id) / f"{schedule.schedule_version}.json", schedule.model_dump(mode="json"))

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def next_planned_capture(self, schedule: PaperCampaignSchedule) -> PaperCampaignScheduleEntry | None:
        for entry in schedule.entries:
            if not entry.executed:
                return entry
        return None

    def find_entry(self, schedule: PaperCampaignSchedule, planned_capture_id: str) -> PaperCampaignScheduleEntry | None:
        for entry in schedule.entries:
            if entry.planned_capture_id == planned_capture_id:
                return entry
        return None

    def _capture_metadata_payload(self, entry: PaperCampaignScheduleEntry) -> dict[str, Any]:
        return {
            "day_id": entry.day_id, "campaign_period": entry.campaign_period,
            "pre_or_post": None if entry.pre_or_post == "NOT_APPLICABLE" else entry.pre_or_post,
            "intervention_arm": None if entry.intervention_arm == "NOT_APPLICABLE" else entry.intervention_arm,
            "packet_variant": entry.packet_variant, "receiver_epoch": entry.receiver_epoch,
            "firmware_hash": entry.firmware_hash, "configuration_hash": entry.configuration_hash,
            "time_since_power_on_s": entry.time_since_power_on_s, "time_since_intervention_s": entry.time_since_intervention_s,
            "capture_order": entry.capture_order, "planned_capture_id": entry.planned_capture_id,
        }

    def _apply_declared_metadata_to_manifest(self, capture_id: str, entry: PaperCampaignScheduleEntry) -> None:
        manifest_path = self.legacy_capture_root / capture_id / "capture_manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"CAPTURE_MANIFEST_NOT_FOUND_AFTER_CAPTURE:{capture_id}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        # Every value here was already frozen in the schedule BEFORE this
        # capture was issued -- this is the "write it down" step, not a
        # reconstruction of anything observed after the fact.
        manifest.update(self._capture_metadata_payload(entry))
        atomic_json(manifest_path, manifest)

    def execute(self, schedule: PaperCampaignSchedule, planned_capture_id: str, *, build_capture_record: Callable[[str], CaptureRecord], progress: ProgressHook = None, **run_session_kwargs: Any) -> CaptureRecord:
        """`build_capture_record` re-reads the just-updated manifest into a
        real CaptureRecord (e.g. StudioRepository/CaptureStage's own
        build_capture, injected so this runner never re-implements that
        parsing)."""
        if self.campaign_orchestrator is None:
            raise PaperCampaignSchedulingError("NO_CAMPAIGN_ORCHESTRATOR_CONFIGURED:cannot execute a real capture without one")
        entry = self.find_entry(schedule, planned_capture_id)
        if entry is None:
            raise PaperCampaignSchedulingError(f"PLANNED_CAPTURE_ID_NOT_IN_SCHEDULE:{planned_capture_id}")
        if entry.executed:
            raise PaperCampaignSchedulingError(f"PLANNED_CAPTURE_ALREADY_EXECUTED:{planned_capture_id}")

        result = self.campaign_orchestrator.run_session(
            ble_channel=entry.channel, physical_unit_id=entry.physical_unit_id, capture_purpose=entry.capture_purpose,
            progress=progress, **run_session_kwargs,
        )
        capture_id = result["capture_id"] if isinstance(result, dict) else result.capture_id

        self._apply_declared_metadata_to_manifest(capture_id, entry)
        capture_record = build_capture_record(capture_id)

        updated_entries = [
            e.model_copy(update={"executed": True, "executed_capture_id": capture_id}) if e.planned_capture_id == planned_capture_id else e
            for e in schedule.entries
        ]
        updated_schedule = schedule.model_copy(update={"entries": updated_entries})
        self._save_schedule(updated_schedule)
        return capture_record

    def reject_out_of_schedule(self, *, schedule: PaperCampaignSchedule, attempted: dict[str, Any], reason: str) -> dict[str, Any]:
        """Refuses execution (the real enforcement -- execute() itself
        already raises PaperCampaignSchedulingError for anything not in the
        schedule) and returns a plain record of the rejection for the
        caller to log/display. The canonical, schema-versioned
        PROTOCOL_DEVIATION record for this event is produced later, at
        record-build time, by ble_scientific_results (which already reads
        this schedule read-only -- see records/campaign_deviations.py) --
        this module deliberately never constructs a
        ScientificCampaignDeviationRecord itself, to keep the dependency
        direction one-way (ble_scientific_results depends on
        ble_rffi_studio, never the reverse)."""
        return {
            "schedule_id": schedule.schedule_id, "reason": reason, "attempted": attempted, "rejected_at": utc_now(),
        }
