"""GuidedBleScientificValidationService -- orchestrates ALREADY-EXISTING
services into one guided flow. It invokes:
  ScientificResultsRepository.freeze_protocol/create_run/build_records
  calibration.evaluate_capture_eligibility/calibration_event_from_ledger_row/
    find_enrolled_devices_in_native_scan
  calibration.select_association_policy

It never re-implements a decoder, a records builder, or a statistics
engine, and it never trains a model or reads FUTURE_TEST holdout data --
this module reads only real, already-frozen datasets/splits/replays.
"""
from __future__ import annotations

import json
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.infrastructure.ble.capture.ble_capture_metadata import atomic_json

from ..api.scientific_results_repository import ScientificResultsRepository
from ..calibration import (
    NoThresholdSatisfiesCriteriaError,
    calibration_event_from_ledger_row,
    evaluate_capture_eligibility,
    find_enrolled_devices_in_native_scan,
    select_association_policy,
)
from ..contracts import CalibrationEventRecord
from ..records.iq_resolution import resolve_replay_dir
from .contracts import GuidedValidationStage, GuidedValidationSummary, CapabilityFlag

ProgressHook = Callable[[str, float, str], None] | None

_ASSOCIATION_THRESHOLD_GRID = [50.0, 100.0, 150.0, 200.0, 250.0, 300.0, 400.0, 500.0]
_PILOT_FIELDS = ("day_id", "campaign_period", "pre_or_post", "intervention_arm", "capture_order", "receiver_epoch")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_jsonl(path: Path | None) -> list[dict]:
    if path is None or not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else {}


class GuidedBleScientificValidationService:
    def __init__(self, repository: ScientificResultsRepository) -> None:
        self.repository = repository
        self.ble_root = repository.ble_root
        self.legacy_capture_root = repository.legacy_capture_root
        self.native_scan_root = self.legacy_capture_root.parent / "native" / "scans"
        self.output_root = repository.root / "guided_validation"
        self.output_root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Discovery (step 1)
    # ------------------------------------------------------------------

    def _discover_enrolled_devices(self) -> list[str]:
        registry_dir = self.ble_root / "registry" / "physical_units"
        if not registry_dir.is_dir():
            return []
        device_ids = []
        for path in sorted(registry_dir.glob("*.json")):
            data = _read_json(path)
            unit_id = data.get("physical_unit_id")
            if unit_id and not unit_id.upper().startswith("SYNTHETIC"):
                device_ids.append(unit_id)
        return device_ids

    def _discover_device_datasets(self, device_ids: list[str]) -> dict[str, tuple[str, str]]:
        """For each enrolled device, the most recent dataset whose
        TARGET_VS_BACKGROUND split is READY with leakage PASSED and whose
        class_distribution names the device as a positive class -- the
        SAME real freeze/split artifacts ble_rffi_studio already produced,
        never rebuilt here."""
        datasets_dir, splits_dir = self.ble_root / "datasets", self.ble_root / "splits"
        result: dict[str, tuple[str, str]] = {}
        if not datasets_dir.is_dir():
            return result
        for device_id in device_ids:
            candidates = []
            for path in datasets_dir.glob("*.json"):
                data = _read_json(path)
                if device_id not in (data.get("class_distribution") or {}):
                    continue
                dataset_id, dataset_version = data.get("dataset_id"), data.get("dataset_version")
                split_path = splits_dir / f"{dataset_id}__{dataset_version}__TARGET_VS_BACKGROUND.json"
                split = _read_json(split_path)
                if split.get("split_status") == "READY" and (split.get("leakage_check") or {}).get("status") == "PASSED":
                    candidates.append((dataset_id, dataset_version))
            if candidates:
                candidates.sort(key=lambda item: item[1])  # dataset_version sorts chronologically (ISO timestamp)
                result[device_id] = candidates[-1]
        return result

    # ------------------------------------------------------------------
    # Device addresses (for the target-absence cross-check)
    # ------------------------------------------------------------------

    def _device_addresses(self) -> dict[str, str]:
        bindings_dir = self.ble_root / "registry" / "address_bindings"
        result: dict[str, str] = {}
        if not bindings_dir.is_dir():
            return result
        for path in bindings_dir.glob("*.json"):
            data = _read_json(path)
            unit, address = data.get("bound_physical_unit_id"), data.get("address")
            if unit and address and data.get("binding_status") == "BOUND":
                result[unit] = address
        return result

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self, *, progress: ProgressHook = None) -> GuidedValidationSummary:
        run_id = "GVAL-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
        run_dir = self.output_root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)

        def report(stage: str, fraction: float, message: str) -> None:
            if progress:
                progress(stage, fraction, message)

        report("discover", 0.02, "Discovering enrolled devices and existing BLE datasets")
        device_ids = self._discover_enrolled_devices()
        device_datasets = self._discover_device_datasets(device_ids)

        device_summary: dict[str, Any] = {}
        capture_rows: list[dict[str, Any]] = []
        calibration_events: list[CalibrationEventRecord] = []
        association_status_totals: Counter = Counter()
        artifact_index: dict[str, Any] = {}

        total_devices = max(len(device_datasets), 1)
        for index, (device_id, (dataset_id, dataset_version)) in enumerate(device_datasets.items()):
            report("reconstruct", 0.05 + 0.55 * (index / total_devices), f"Reconstructing canonical records for {device_id}")
            contract = self.repository.freeze_protocol({
                "hardware_profile_id": "usrp-b200-guided-validation", "receiver_profile_hash": "guided-validation",
                "interpretation_matrix_hash": f"guided-validation-{device_id}-{run_id}",
            })
            paper_run = self.repository.create_run(
                protocol_id=contract.protocol_id, protocol_version=contract.protocol_version,
                campaign_id="GUIDED-VALIDATION", dataset_id=dataset_id, dataset_version=dataset_version,
                scientific_task="TARGET_VS_BACKGROUND",
            )
            self.repository.build_records(paper_run.paper_run_id)
            captures = self.repository.list_capture_records(paper_run.paper_run_id, limit=100000)
            bursts = self.repository.list_burst_records(paper_run.paper_run_id, limit=1000000)
            windows = self.repository.list_window_records(paper_run.paper_run_id, limit=1000000)

            device_result = self._process_device(
                device_id=device_id, captures=captures, bursts=bursts, windows=windows,
                capture_rows=capture_rows, calibration_events=calibration_events,
                association_status_totals=association_status_totals,
            )
            device_summary[device_id] = device_result
            artifact_index[device_id] = {"paper_run_id": paper_run.paper_run_id, "dataset_id": dataset_id, "dataset_version": dataset_version}

        report("target_absence", 0.65, "Searching for valid target-absence control captures")
        target_absence_summary = self._search_target_absence(device_ids)

        report("association_policy", 0.8, "Attempting association-policy selection")
        association_policy_summary = self._attempt_policy(calibration_events, target_absence_summary, run_id)

        capture_totals = {
            "total_captures": len(capture_rows),
            "association_calibration_eligible": sum(1 for row in capture_rows if row["classification"] == "ASSOCIATION_CALIBRATION_ELIGIBLE"),
            "qualification_pilot_eligible": sum(1 for row in capture_rows if row["classification"] == "QUALIFICATION_PILOT_ELIGIBLE"),
            "diagnostic_only": sum(1 for row in capture_rows if row["classification"] == "DIAGNOSTIC_ONLY"),
        }
        total_events = sum(association_status_totals.values()) or 1
        association_summary = {
            "total_calibration_events": sum(association_status_totals.values()),
            "by_status": dict(association_status_totals),
            "by_status_percent": {status: round(100 * count / total_events, 1) for status, count in association_status_totals.items()},
            "matched_target_count": association_status_totals.get("MATCHED_TARGET", 0),
        }

        report("assemble", 0.9, "Assembling guided validation stages and conclusion")
        stages = self._build_stages(
            device_datasets=device_datasets, capture_totals=capture_totals, association_summary=association_summary,
            target_absence_summary=target_absence_summary, association_policy_summary=association_policy_summary,
        )
        capability_flags = self._build_capability_flags(capture_totals, association_summary)
        overall_status = self._overall_status(stages)
        simplified_conclusion = self._build_conclusion(association_summary, association_policy_summary)
        next_required_action = self._next_required_action(stages)

        summary = GuidedValidationSummary(
            run_id=run_id, generated_at=utc_now(), overall_status=overall_status, stages=stages, capability_flags=capability_flags,
            device_summary=device_summary, capture_totals=capture_totals, association_summary=association_summary,
            target_absence_summary=target_absence_summary, association_policy_summary=association_policy_summary,
            simplified_conclusion=simplified_conclusion, next_required_action=next_required_action, artifact_index=artifact_index,
        )
        self._persist(run_dir, summary, capture_rows, calibration_events)
        report("done", 1.0, "Guided validation complete")
        return summary

    # ------------------------------------------------------------------
    # Per-device reconstruction
    # ------------------------------------------------------------------

    def _process_device(
        self, *, device_id: str, captures: list[dict], bursts: list[dict], windows: list[dict],
        capture_rows: list[dict], calibration_events: list[CalibrationEventRecord], association_status_totals: Counter,
    ) -> dict[str, Any]:
        bursts_by_capture: dict[str, list[dict]] = {}
        for burst in bursts:
            bursts_by_capture.setdefault(burst["capture_id"], []).append(burst)
        windows_by_capture: dict[str, list[dict]] = {}
        for window in windows:
            windows_by_capture.setdefault(window["capture_id"], []).append(window)

        native_event_total = 0
        crc_valid_total = 0
        strong_total = 0
        eligible_count = 0

        for capture in captures:
            capture_id = capture["capture_id"]
            capture_bursts = bursts_by_capture.get(capture_id, [])
            capture_windows = windows_by_capture.get(capture_id, [])

            manifest = _read_json(self.legacy_capture_root / capture_id / "capture_manifest.json")
            studio_capture = _read_json(self.ble_root / "captures" / f"{capture_id}.json")
            session_id = studio_capture.get("session_id") or studio_capture.get("execution_id")
            native_rows = _read_jsonl(self.native_scan_root / str(session_id) / "advertisements.jsonl") if session_id else []

            crc_valid_count = sum(1 for burst in capture_bursts if burst.get("crc_status") == "VALID")
            has_target = studio_capture.get("target_reference_id") == device_id or (manifest.get("experimental_metadata") or {}).get("physical_unit_id") == device_id
            pilot_fields_present = {name: capture.get(name) not in (None, "") for name in _PILOT_FIELDS}

            eligibility = evaluate_capture_eligibility(
                has_source_iq=bool(manifest.get("data_sha256")), has_channel=manifest.get("ble_channel") is not None,
                has_sample_rate=manifest.get("sample_rate_sps") is not None, has_timestamp=bool(manifest.get("created_at_utc")),
                has_native_observations=len(native_rows) > 0, has_association_ledger=len(capture_bursts) > 0,
                has_crc_valid_packets=crc_valid_count > 0, has_declared_target_device=has_target,
                pilot_fields_present=pilot_fields_present,
            )

            capture_rows.append({
                "device_id": device_id, "capture_id": capture_id, "classification": eligibility.classification,
                "missing_fields": list(eligibility.missing_fields), "native_event_count": len(native_rows),
                "candidate_count": len(capture_bursts), "crc_valid_count": crc_valid_count,
                "active_windows": len(capture_windows), "eligible_windows": sum(1 for w in capture_windows if w["window_status"] == "ACTIVE_ELIGIBLE"),
            })

            native_event_total += len(native_rows)
            crc_valid_total += crc_valid_count
            strong_total += sum(1 for burst in capture_bursts if burst.get("association_status") == "STRONG")

            if eligibility.classification != "DIAGNOSTIC_ONLY":
                eligible_count += 1
                replay_dir = resolve_replay_dir(self.legacy_capture_root, capture_id)
                ledger_rows = _read_jsonl((replay_dir / "packet_association_ledger.jsonl") if replay_dir else None)
                fallback_ts = manifest.get("created_at_utc") or "1970-01-01T00:00:00Z"
                for row in ledger_rows:
                    calibration_events.append(calibration_event_from_ledger_row(row, device_id=device_id, capture_id=capture_id, fallback_timestamp=fallback_ts))
                    status = row.get("address_match_status")
                    if status == "MATCHED":
                        association_status_totals["MATCHED_TARGET"] += 1
                    elif status:
                        association_status_totals[status] += 1

        return {
            "capture_count": len(captures), "calibration_eligible_or_better_captures": eligible_count,
            "native_event_count": native_event_total, "crc_valid_packet_count": crc_valid_total,
            "strong_association_count": strong_total,
            "active_windows": sum(len(v) for v in windows_by_capture.values()),
            "eligible_windows": sum(1 for wlist in windows_by_capture.values() for w in wlist if w["window_status"] == "ACTIVE_ELIGIBLE"),
        }

    # ------------------------------------------------------------------
    # Target-absence control search
    # ------------------------------------------------------------------

    def _search_target_absence(self, device_ids: list[str]) -> dict[str, Any]:
        device_addresses = self._device_addresses()
        captures_dir = self.ble_root / "captures"
        candidates = []
        if captures_dir.is_dir():
            for path in sorted(captures_dir.glob("*.json")):
                studio_capture = _read_json(path)
                is_background_off = studio_capture.get("capture_purpose") == "BACKGROUND_TARGET_OFF" or studio_capture.get("target_state") == "OPERATOR_DECLARED_POWERED_OFF_OR_REMOVED"
                if not is_background_off:
                    continue
                capture_id = studio_capture.get("capture_id") or path.stem
                session_id = studio_capture.get("session_id") or studio_capture.get("execution_id")
                native_dir = self.native_scan_root / str(session_id) if session_id else None
                native_rows = _read_jsonl((native_dir / "advertisements.jsonl")) if native_dir else []
                scanner_ran = bool(native_dir and native_dir.is_dir())
                present = find_enrolled_devices_in_native_scan(native_rows, device_addresses)
                candidates.append({
                    "capture_id": capture_id, "session_id": session_id, "native_event_count": len(native_rows),
                    "scanner_ran": scanner_ran, "enrolled_devices_seen": present,
                    "valid_reinforced_control": scanner_ran and len(native_rows) > 0 and not present,
                })
        valid = [c for c in candidates if c["valid_reinforced_control"]]
        invalid_reasons = {}
        for c in candidates:
            if c["valid_reinforced_control"]:
                continue
            if not c["scanner_ran"] or c["native_event_count"] == 0:
                invalid_reasons[c["capture_id"]] = "NO_NATIVE_SCANNER_RECORD_FOR_THIS_SESSION"
            elif c["enrolled_devices_seen"]:
                invalid_reasons[c["capture_id"]] = f"ENROLLED_DEVICES_STILL_DETECTED:{','.join(c['enrolled_devices_seen'])}"
        return {
            "candidates_checked": len(candidates), "valid_reinforced_controls": valid,
            "has_valid_control": len(valid) > 0, "invalid_reasons_by_capture": invalid_reasons,
        }

    # ------------------------------------------------------------------
    # Association policy attempt
    # ------------------------------------------------------------------

    def _attempt_policy(self, calibration_events: list[CalibrationEventRecord], target_absence_summary: dict, run_id: str) -> dict[str, Any] | None:
        if not calibration_events:
            return None
        absence_events: list[CalibrationEventRecord] = []  # no real target-absence calibration events exist without a valid control
        device_family_by_unit = {event.physical_unit_id: event.physical_unit_id for event in calibration_events}
        try:
            result = select_association_policy(
                calibration_events=calibration_events, target_absence_events=absence_events, device_family_by_unit=device_family_by_unit,
                threshold_grid=_ASSOCIATION_THRESHOLD_GRID, calibration_campaign_id=f"GUIDED-VALIDATION-{run_id}",
                devices_used=sorted(device_family_by_unit.keys()), captures_used=sorted({event.capture_id for event in calibration_events}),
                callback_batching_policy="per-capture", duplicate_policy="first-decoded-wins", field_match_policy="address+PDU-type",
                minimum_coverage=0.95,
            )
        except NoThresholdSatisfiesCriteriaError as error:
            return {"status": "NO_THRESHOLD_SATISFIES_CRITERIA", "detail": str(error), "policy_scope": None}

        if not isinstance(result, dict):
            return {"status": "FROZEN", "policy_scope": "GLOBAL_POLICY", "policy": result.model_dump(mode="json")}

        policies = {}
        for family, policy in result.items():
            scope = "DEVICE_SPECIFIC_POLICY" if len(policy.devices_used) <= 1 else "VERIFIED_FAMILY_POLICY"
            policies[family] = {"policy_scope": scope, "policy": policy.model_dump(mode="json")}
        return {"status": "FROZEN_STRATIFIED", "policy_scope": "STRATIFIED", "policies_by_family": policies}

    # ------------------------------------------------------------------
    # Stages / conclusion / capability flags
    # ------------------------------------------------------------------

    def _build_stages(self, *, device_datasets, capture_totals, association_summary, target_absence_summary, association_policy_summary) -> list[GuidedValidationStage]:
        stages = []
        stages.append(GuidedValidationStage(
            stage_id="objective", label="Objective", status="COMPLETED",
            plain_explanation="Determine whether BLE packets recovered by the USRP B200 can be reliably associated with native BLE adapter observations, and later used as physical-identity-backed training examples.",
            technical_details={}, evidence_artifacts=[], next_action=None,
        ))
        available_status = "PASSED" if device_datasets else "BLOCKED"
        stages.append(GuidedValidationStage(
            stage_id="available_data", label="Available Data", status=available_status,
            plain_explanation=f"{len(device_datasets)} enrolled device(s) have a ready, leakage-checked dataset available." if device_datasets else "No ready dataset was found for any enrolled device.",
            technical_details={"devices": list(device_datasets.keys())}, evidence_artifacts=[], next_action=None if device_datasets else "Build and freeze a dataset/split for at least one enrolled device.",
        ))
        integrity_status = "PASSED" if capture_totals.get("total_captures", 0) > 0 else "BLOCKED"
        stages.append(GuidedValidationStage(
            stage_id="capture_integrity", label="Capture Integrity", status=integrity_status,
            plain_explanation=f"{capture_totals.get('association_calibration_eligible', 0) + capture_totals.get('qualification_pilot_eligible', 0)} of {capture_totals.get('total_captures', 0)} captures have verified I/Q, timestamps, native observations and an association ledger.",
            technical_details=capture_totals, evidence_artifacts=["existing_capture_eligibility_report.json"], next_action=None,
        ))
        crc_ok = capture_totals.get("association_calibration_eligible", 0) + capture_totals.get("qualification_pilot_eligible", 0) > 0
        stages.append(GuidedValidationStage(
            stage_id="packet_recovery", label="Packet Recovery", status="PASSED" if crc_ok else "BLOCKED",
            plain_explanation="CRC-valid BLE packets were recovered from real I/Q." if crc_ok else "No CRC-valid packets were recovered.",
            technical_details={}, evidence_artifacts=[], next_action=None,
        ))
        matched = association_summary.get("matched_target_count", 0)
        association_status = "PASSED" if matched > 0 else "BLOCKED"
        stages.append(GuidedValidationStage(
            stage_id="source_association", label="Source Association", status=association_status,
            plain_explanation=f"{matched} SDR packet(s) matched a native observation of the declared target." if matched else "No SDR packet was matched to a native observation of the declared target under the current timing rule.",
            technical_details=association_summary, evidence_artifacts=["existing_capture_calibration_summary.json"],
            next_action=None if matched else "Run Live Timing Diagnostic",
        ))
        negative_status = "PASSED" if target_absence_summary.get("has_valid_control") else "REQUIRES_PHYSICAL_ACTION"
        stages.append(GuidedValidationStage(
            stage_id="negative_control", label="Negative Control", status=negative_status,
            plain_explanation="A valid reinforced target-absence control was found." if target_absence_summary.get("has_valid_control") else "No existing capture qualifies as a reinforced target-absence control (all five enrolled devices confirmed absent, native scanner confirmed running).",
            technical_details=target_absence_summary, evidence_artifacts=["association_target_absence_control.json"],
            next_action=None if target_absence_summary.get("has_valid_control") else "Run Reinforced Target-Absence Control",
        ))
        policy_status = "PASSED" if association_policy_summary and association_policy_summary.get("status") in ("FROZEN", "FROZEN_STRATIFIED") else "BLOCKED"
        stages.append(GuidedValidationStage(
            stage_id="association_policy", label="Association Policy", status=policy_status,
            plain_explanation="A frozen association policy is available." if policy_status == "PASSED" else "No association policy could be frozen from the available evidence.",
            technical_details=association_policy_summary or {}, evidence_artifacts=["association_policy.json"] if policy_status == "PASSED" else [],
            next_action=None if policy_status == "PASSED" else "Freeze Association Policy (requires source association and a valid negative control first)",
        ))
        stages.append(GuidedValidationStage(
            stage_id="next_required_action", label="Next Required Action", status="COMPLETED",
            plain_explanation=self._next_required_action(stages), technical_details={}, evidence_artifacts=[], next_action=None,
        ))
        return stages

    def _build_capability_flags(self, capture_totals: dict, association_summary: dict) -> list[CapabilityFlag]:
        return [
            CapabilityFlag(capability="RF capture", supported=capture_totals.get("total_captures", 0) > 0, plain_explanation="Can the platform preserve real I/Q?"),
            CapabilityFlag(capability="BLE packet recovery", supported=(capture_totals.get("association_calibration_eligible", 0) + capture_totals.get("qualification_pilot_eligible", 0)) > 0, plain_explanation="Can the platform recover CRC-valid BLE packets?"),
            CapabilityFlag(capability="Physical-source association", supported=association_summary.get("matched_target_count", 0) > 0, plain_explanation="Can the platform currently assign strong physical labels?"),
        ]

    def _overall_status(self, stages: list[GuidedValidationStage]) -> str:
        if any(stage.status == "BLOCKED" for stage in stages if stage.stage_id not in ("negative_control",)):
            return "BLOCKED"
        if any(stage.status == "REQUIRES_PHYSICAL_ACTION" for stage in stages):
            return "REQUIRES_PHYSICAL_ACTION"
        return "PASSED"

    def _build_conclusion(self, association_summary: dict, association_policy_summary: dict | None) -> str:
        if association_policy_summary and association_policy_summary.get("status") in ("FROZEN", "FROZEN_STRATIFIED"):
            return (
                "A frozen source-association policy was obtained from independent native and SDR observations. "
                "Its use is limited to the devices, receiver configuration and calibration conditions shown below."
            )
        return (
            "The existing datasets demonstrate real BLE I/Q acquisition, CRC-valid packet recovery and reconstruction "
            "of fixed-duration analysis windows. They do not yet support strong physical-source labels because no "
            "native target observation was matched to an SDR packet under the available association records. Model "
            "training with strong labels remains blocked. A short live timing diagnostic and one reinforced "
            "target-absence control are the minimum required next actions."
        )

    def _next_required_action(self, stages: list[GuidedValidationStage]) -> str:
        order = ["source_association", "negative_control", "association_policy"]
        by_id = {stage.stage_id: stage for stage in stages}
        for stage_id in order:
            stage = by_id.get(stage_id)
            if stage and stage.status not in ("PASSED", "COMPLETED"):
                return stage.next_action or f"Resolve stage: {stage.label}"
        return "Run Qualification Pilot"

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self, run_dir: Path, summary: GuidedValidationSummary, capture_rows: list[dict], calibration_events: list[CalibrationEventRecord]) -> None:
        atomic_json(run_dir / "guided_validation_summary.json", summary.model_dump(mode="json"))
        atomic_json(run_dir / "device_summary.json", summary.device_summary)
        atomic_json(run_dir / "capture_eligibility.json", capture_rows)
        atomic_json(run_dir / "association_summary.json", summary.association_summary)
        atomic_json(run_dir / "target_absence_summary.json", summary.target_absence_summary)
        if summary.association_policy_summary:
            atomic_json(run_dir / "association_policy.json", summary.association_policy_summary)

        # The full per-event CSV can be tens of megabytes -- never
        # committed to git (see .gitignore under storage/), only indexed
        # by path/size/sha256/row count so the UI can offer it without
        # loading it into a JSON response.
        import csv
        import hashlib
        csv_path = run_dir / "calibration_records.csv"
        fieldnames = list(CalibrationEventRecord.model_fields.keys())
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for event in calibration_events:
                writer.writerow(event.model_dump(mode="json"))
        sha256 = hashlib.sha256(csv_path.read_bytes()).hexdigest()
        atomic_json(run_dir / "artifact_index.json", {
            "calibration_records_csv": {"path": str(csv_path), "size_bytes": csv_path.stat().st_size, "sha256": sha256, "row_count": len(calibration_events)},
        })
