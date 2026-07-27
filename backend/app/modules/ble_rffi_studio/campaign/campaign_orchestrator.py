"""Real capture campaign: wraps the EXISTING, already-validated B200 +
native-scan session mechanism (BleHybridCampaignManager) and the EXISTING
resumable offline replay (BleCaptureJobManager.start_offline_replay,
Fase 1) -- it reuses their MECHANISM only, never their scientific
vocabulary or dataset decisions, exactly like CaptureStage/EvidenceStage do
for a legacy capture picked by hand.

Every session always launches with campaign_intent=exploratory_target_search
and target={"kind":"any"}: which physical unit (if any) a packet belongs to
is decided entirely downstream, by THIS module's own AddressBinding +
Evidence Stage -- never by what the legacy campaign manager was told its
"target" was. This also sidesteps the legacy POSITIVE_TARGET_VALIDATION
requirement that a device be freshly re-discovered by a live native scan
right before the session starts, which would otherwise force an extra,
separate discovery step with its own timing race.

The "condicion experimental" (target physically on/off/present/absent) is
whatever the operator declares and physically arranges before clicking
launch -- this code has no way to verify or change the physical setup
itself, and does not pretend otherwise.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Callable

ProgressHook = Callable[[str, float, str], None]

_HYBRID_TERMINAL = {"completed", "failed", "cancelled", "timed_out"}
_JOB_TERMINAL = {"completed", "failed", "cancelled"}

# A single offline-replay invocation stops after this many seconds of actual
# decode work and reports exit_status=PARTIAL with a checkpoint, rather than
# ever silently treating a partially-decoded capture as fully analyzed (a
# real capture's candidate backlog can take far longer than one HTTP-request
# lifetime to fully decode). The orchestrator resumes from checkpoint until
# exit_status=FULLY_PROCESSED, up to _MAX_REPLAY_RESUMES chunks, so evidence
# is only ever built from a complete decode of the capture.
_REPLAY_CHUNK_BUDGET_SECONDS = 1800.0
_MAX_REPLAY_RESUMES = 12

# A real-time USB3 RF stream can drop samples if the host briefly can't keep
# up (this environment's measured historical rate: ~46% of B200 captures,
# even in isolation) -- the worker correctly refuses to treat a
# dropped-sample capture as valid (job state -> "failed", error contains
# "CAPTURE_FAILED"). That is not a misconfiguration an operator can fix by
# reading an error message; it is exactly the kind of transient condition a
# plain retry resolves. Retried automatically here rather than surfaced,
# up to this many real capture attempts, so a routine RF hiccup never shows
# up as an error the operator has to act on.
_MAX_CAPTURE_ATTEMPTS = 6


class CampaignSessionError(Exception):
    pass


_TARGET_STATE_BY_PURPOSE = {
    "TARGET_DEVICE": "POWERED_ON",
    "BACKGROUND_ENVIRONMENT": "OPERATOR_DECLARED_POWERED_OFF_OR_REMOVED",
}
_DATASET_ROLE_BY_PURPOSE = {
    "TARGET_DEVICE": "POSITIVE_CANDIDATE",
    "BACKGROUND_ENVIRONMENT": "NEGATIVE_CANDIDATE",
}


class CampaignOrchestrator:
    def __init__(self, *, hybrid_manager: Any, capture_manager: Any, arbiter: Any, repository: Any) -> None:
        self.hybrid_manager = hybrid_manager
        self.capture_manager = capture_manager
        self.arbiter = arbiter
        self.repository = repository

    def resolve_device_id(self, requested_device_id: str | None = None) -> str:
        return self.capture_manager.resolve_device_id(requested_device_id)

    def _hybrid_payload(
        self, *, device_id: str, ble_channel: int, duration_seconds: float, gain_db: float,
        condition_label: str, physical_unit_id: str | None, project_id: str, campaign_id: str, session_index: int,
        power_state: str,
    ) -> dict[str, Any]:
        metadata = {
            "distance": "0.50 m", "orientation": "0", "location": "LAB-A",
            "physical_unit_id": physical_unit_id or "AMBIENT_UNKNOWN",
            "power_state": power_state,
            "execution_purpose": "EXPLORATORY_TARGET_SEARCH",
            "condition_id": condition_label,
            "project_id": project_id, "campaign_id": campaign_id,
            "operator_notes": f"BLE-RFFI Studio guided campaign, session {session_index}",
        }
        return {
            "device_id": device_id, "channel": ble_channel, "duration_seconds": duration_seconds,
            "gain_db": gain_db, "target": {"kind": "any"}, "campaign_intent": "exploratory_target_search",
            "experimental_metadata": metadata,
        }

    def run_session(
        self,
        *,
        ble_channel: int,
        duration_seconds: float,
        gain_db: float,
        condition_label: str,
        physical_unit_id: str | None,
        project_id: str,
        campaign_id: str,
        session_index: int,
        device_id: str | None = None,
        isolation_declared: bool = False,
        capture_purpose: str = "TARGET_DEVICE",
        operator_confirmed_target_absent: bool = False,
        progress: ProgressHook | None = None,
    ) -> dict[str, Any]:
        def report(phase: str, fraction: float, message: str) -> None:
            if progress:
                progress(phase, fraction, message)

        if capture_purpose not in _TARGET_STATE_BY_PURPOSE:
            raise CampaignSessionError(f"UNKNOWN_CAPTURE_PURPOSE:{capture_purpose}")

        if capture_purpose == "TARGET_DEVICE" and not physical_unit_id:
            raise CampaignSessionError(
                "TARGET_DEVICE_REQUIRES_A_PHYSICAL_UNIT_ID:capturing the target device means selecting which physical unit it is"
            )
        if capture_purpose == "BACKGROUND_ENVIRONMENT" and not operator_confirmed_target_absent:
            raise CampaignSessionError(
                "BACKGROUND_ENVIRONMENT_REQUIRES_OPERATOR_CONFIRMATION:the operator must explicitly confirm the target device "
                "was powered off or removed for the whole capture -- this is never inferred from the absence of a signal"
            )
        # Physical isolation is a TARGET_DEVICE-only ground-truth mechanism: it
        # asserts "only this unit was transmitting nearby", which is precisely
        # the opposite of what a BACKGROUND_ENVIRONMENT capture is for. Forced
        # off here rather than trusted from the caller so a stale/incorrect
        # frontend request can never smuggle a positive label onto a
        # background session.
        if capture_purpose == "BACKGROUND_ENVIRONMENT":
            isolation_declared = False

        # No separate "isolation declared requires a physical_unit_id" check
        # here: isolation_declared can only be True when capture_purpose is
        # TARGET_DEVICE (BACKGROUND_ENVIRONMENT always forces it False above),
        # and TARGET_DEVICE already requires physical_unit_id, above.

        target_state = _TARGET_STATE_BY_PURPOSE[capture_purpose]
        dataset_role = _DATASET_ROLE_BY_PURPOSE[capture_purpose]
        target_reference_id = physical_unit_id

        resolved_device_id = self.resolve_device_id(device_id)
        operation_id = f"campaign-session-{uuid.uuid4().hex[:10]}"
        lease_seconds = max(300.0, duration_seconds * 6)
        acquired = self.arbiter.acquire(resolved_device_id, owner="ble_rffi_studio_campaign", operation_id=operation_id, lease_seconds=lease_seconds)
        if not acquired.granted:
            raise CampaignSessionError(f"B200_BUSY:held_by={acquired.current_owner}:operation={acquired.current_operation_id}")

        try:
            payload = self._hybrid_payload(
                device_id=resolved_device_id, ble_channel=ble_channel, duration_seconds=duration_seconds, gain_db=gain_db,
                condition_label=condition_label, physical_unit_id=physical_unit_id,
                project_id=project_id, campaign_id=campaign_id, session_index=session_index,
                power_state="powered_on" if capture_purpose == "TARGET_DEVICE" else "operator_declared_powered_off_or_removed",
            )

            session: dict[str, Any] | None = None
            for capture_attempt in range(1, _MAX_CAPTURE_ATTEMPTS + 1):
                report("LAUNCH_SESSION", 0.0, f"Iniciando sesion hibrida (B200 + escaneo nativo Windows), intento {capture_attempt}/{_MAX_CAPTURE_ATTEMPTS}")
                session = self.hybrid_manager.start(payload)
                session_id = session["session_id"]

                while session.get("state") not in _HYBRID_TERMINAL:
                    time.sleep(1.0)
                    session = self.hybrid_manager.get(session_id)
                    report("CAPTURING", 0.25, f"Sesion {session_id}: {session.get('state')} (intento {capture_attempt}/{_MAX_CAPTURE_ATTEMPTS})")

                if session.get("state") == "completed":
                    break
                is_transient_rf_failure = "CAPTURE_FAILED" in str(session.get("error") or "")
                if not is_transient_rf_failure or capture_attempt == _MAX_CAPTURE_ATTEMPTS:
                    raise CampaignSessionError(f"HYBRID_SESSION_{str(session.get('state', 'unknown')).upper()}:{session.get('error')}")
                report("CAPTURING", 0.1, f"Adquisicion RF interrumpida (overflow/discontinuidad transitoria de USB) -- reintentando automaticamente ({capture_attempt}/{_MAX_CAPTURE_ATTEMPTS})")

            capture_id = session["capture_id"]
            report("CAPTURE_STAGE", 0.5, f"Construyendo CaptureRecord para {capture_id}")
            # The hybrid session_id IS "which hybrid acquisition session
            # produced this capture" -- pass it explicitly as both
            # execution_id and session_id rather than relying on
            # CaptureStage's manifest/replay inference, since no offline
            # replay exists yet at this point (it runs next) and the raw
            # capture's own experimental_metadata never records a session_id
            # (the hybrid manager only generates one after this payload was
            # already sent).
            capture = self.repository.build_capture(
                capture_id=capture_id, project_id=project_id, campaign_id=campaign_id, execution_id=session_id, session_id=session_id,
                isolation_declared_physical_unit_id=physical_unit_id if isolation_declared else None,
                capture_purpose=capture_purpose, target_state=target_state,
                target_reference_id=target_reference_id, dataset_role=dataset_role,
            )

            report("OFFLINE_REPLAY", 0.6, "Ejecutando replay resumible (puede tardar varios minutos)")
            replay_job = self.capture_manager.start_offline_replay(capture_id, {"job_time_budget_seconds": _REPLAY_CHUNK_BUDGET_SECONDS})
            replay_run_id = replay_job["replay_run_id"]
            replay_state = replay_job
            for resume_attempt in range(_MAX_REPLAY_RESUMES):
                while replay_state.get("state") not in _JOB_TERMINAL:
                    time.sleep(2.0)
                    replay_state = self.capture_manager.offline_replay_job(capture_id, replay_run_id)
                    coverage = ((replay_state.get("progress") or {}).get("coverage_percentage"))
                    report("OFFLINE_REPLAY", 0.7, f"Replay {replay_run_id}: {replay_state.get('state')}" + (f" ({coverage:.1f}% procesado)" if coverage is not None else ""))
                if replay_state.get("state") != "completed":
                    raise CampaignSessionError(f"OFFLINE_REPLAY_{str(replay_state.get('state', 'unknown')).upper()}:{replay_state.get('error')}")
                exit_status = (replay_state.get("result") or {}).get("exit_status")
                if exit_status == "FULLY_PROCESSED":
                    break
                if exit_status != "PARTIAL":
                    raise CampaignSessionError(f"OFFLINE_REPLAY_UNEXPECTED_EXIT_STATUS:{exit_status}")
                report("OFFLINE_REPLAY", 0.7, f"Replay {replay_run_id}: presupuesto de tiempo agotado, retomando desde el ultimo checkpoint (intento {resume_attempt + 2})")
                replay_state = self.capture_manager.start_offline_replay(capture_id, {"replay_run_id": replay_run_id, "job_time_budget_seconds": _REPLAY_CHUNK_BUDGET_SECONDS})
            else:
                raise CampaignSessionError(f"OFFLINE_REPLAY_DID_NOT_REACH_FULLY_PROCESSED_AFTER_{_MAX_REPLAY_RESUMES}_RESUMES:{replay_run_id}")

            report("EVIDENCE", 0.85, "Construyendo evidencia (ExampleRecord + ExampleAnnotation)")
            evidence_summary = self.repository.build_evidence(capture=capture, project_id=project_id, ble_channel=ble_channel, replay_run_id=replay_run_id)

            report("DONE", 1.0, "Sesion de campana completada")
            return {
                "session_id": session_id, "capture_id": capture_id, "replay_run_id": replay_run_id,
                "condition_label": condition_label, "physical_unit_id": physical_unit_id,
                "capture_purpose": capture_purpose, "target_state": target_state, "dataset_role": dataset_role,
                "evidence_summary": evidence_summary,
            }
        finally:
            self.arbiter.release(resolved_device_id, owner="ble_rffi_studio_campaign", operation_id=operation_id)
