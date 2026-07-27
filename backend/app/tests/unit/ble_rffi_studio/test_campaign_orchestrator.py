"""CampaignOrchestrator wires together three EXISTING, separately-tested
mechanisms (BleHybridCampaignManager, BleCaptureJobManager's resumable
offline replay, SdrDeviceArbiter) -- these tests use fakes for all three so
the orchestration logic itself (session lifecycle, the offline-replay
resume-until-FULLY_PROCESSED loop, arbiter release-on-error) is covered
without touching real hardware or real decode workers.

The resume loop specifically guards against a real bug found via a live
B200 capture: a single offline-replay invocation can report job
state="completed" while its own exit_status is "PARTIAL" (time budget
exceeded, checkpointed, most of the capture still undecoded) -- treating
that "completed" as "done" would silently build evidence from a small
fraction of the capture.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.modules.ble_rffi_studio.campaign.campaign_orchestrator import (
    CampaignOrchestrator,
    CampaignSessionError,
    _MAX_CAPTURE_ATTEMPTS,
    _MAX_REPLAY_RESUMES,
)


class FakeAcquireResult:
    def __init__(self, granted: bool, current_owner: str | None = None, current_operation_id: str | None = None) -> None:
        self.granted = granted
        self.current_owner = current_owner
        self.current_operation_id = current_operation_id


class FakeArbiter:
    def __init__(self, granted: bool = True) -> None:
        self.granted = granted
        self.acquired: list[tuple] = []
        self.released: list[tuple] = []

    def acquire(self, device_id, *, owner, operation_id, lease_seconds):
        self.acquired.append((device_id, owner, operation_id, lease_seconds))
        return FakeAcquireResult(self.granted, current_owner="someone_else", current_operation_id="op-x")

    def release(self, device_id, *, owner, operation_id):
        self.released.append((device_id, owner, operation_id))


class FakeHybridManager:
    def __init__(self, final_state: str = "completed", capture_id: str = "BLE-IQ-fake") -> None:
        self.final_state = final_state
        self.capture_id = capture_id
        self.started_payloads: list[dict[str, Any]] = []

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.started_payloads.append(payload)
        # Terminal immediately -- the orchestrator's polling loop body never
        # needs to run for these tests.
        return {"session_id": "BLE-HYBRID-fake-0001", "state": self.final_state, "capture_id": self.capture_id, "error": "boom" if self.final_state != "completed" else None}

    def get(self, session_id):  # pragma: no cover - not reached when start() is already terminal
        return {"session_id": session_id, "state": self.final_state, "capture_id": self.capture_id}


class FlakyThenSucceedsHybridManager:
    """Fails with the real, observed transient signature
    (error contains "CAPTURE_FAILED") for the first `failures_before_success`
    attempts, then succeeds -- models the real, measured ~46% single-attempt
    RF acquisition overflow rate this environment's B200 sees, which the
    orchestrator must absorb via retry rather than surface as an error."""
    def __init__(self, failures_before_success: int, capture_id: str = "BLE-IQ-fake") -> None:
        self.failures_before_success = failures_before_success
        self.capture_id = capture_id
        self.start_calls = 0

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.start_calls += 1
        session_id = f"BLE-HYBRID-fake-{self.start_calls:04d}"
        if self.start_calls <= self.failures_before_success:
            return {"session_id": session_id, "state": "failed", "capture_id": None, "error": "RuntimeError:CAPTURE_FAILED"}
        return {"session_id": session_id, "state": "completed", "capture_id": self.capture_id, "error": None}

    def get(self, session_id):  # pragma: no cover - not reached when start() is already terminal
        return {"session_id": session_id, "state": "completed", "capture_id": self.capture_id}


class FakeCaptureManager:
    def __init__(self, replay_chunks: list[dict[str, Any]]) -> None:
        # Each entry simulates the terminal job state a start/resume call's
        # first offline_replay_job() poll would observe.
        self.replay_chunks = list(replay_chunks)
        self.resume_calls: list[dict[str, Any] | None] = []

    def resolve_device_id(self, requested_device_id=None):
        return requested_device_id or "sdr-fake"

    def start_offline_replay(self, capture_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        self.resume_calls.append(payload)
        chunk = self.replay_chunks.pop(0)
        return {"replay_run_id": "BLE-RFFI-REPLAY-fake", **chunk}

    def offline_replay_job(self, capture_id: str, replay_run_id: str) -> dict[str, Any]:  # pragma: no cover - only reached if a chunk starts non-terminal
        raise AssertionError("test chunks should already be terminal on start_offline_replay")


class FakeRepository:
    def __init__(self) -> None:
        self.built_captures: list[dict[str, Any]] = []
        self.evidence_calls: list[dict[str, Any]] = []

    def build_capture(
        self, *, capture_id, project_id, campaign_id, execution_id=None, session_id=None,
        isolation_declared_physical_unit_id=None, capture_purpose=None, target_state=None,
        target_reference_id=None, dataset_role=None,
    ):
        record = {
            "capture_id": capture_id, "project_id": project_id, "campaign_id": campaign_id, "execution_id": execution_id,
            "session_id": session_id, "isolation_declared_physical_unit_id": isolation_declared_physical_unit_id,
            "capture_purpose": capture_purpose, "target_state": target_state,
            "target_reference_id": target_reference_id, "dataset_role": dataset_role,
        }
        self.built_captures.append(record)
        return record

    def build_evidence(self, *, capture, project_id, ble_channel, replay_run_id=None, progress=None):
        self.evidence_calls.append({"capture": capture, "project_id": project_id, "ble_channel": ble_channel, "replay_run_id": replay_run_id})
        return {"eligible_examples": 5}


def _orchestrator(hybrid_manager=None, capture_manager=None, arbiter=None, repository=None) -> tuple[CampaignOrchestrator, dict[str, Any]]:
    fakes = {
        "hybrid_manager": hybrid_manager or FakeHybridManager(),
        "capture_manager": capture_manager or FakeCaptureManager([{"state": "completed", "result": {"exit_status": "FULLY_PROCESSED"}}]),
        "arbiter": arbiter or FakeArbiter(),
        "repository": repository or FakeRepository(),
    }
    return CampaignOrchestrator(**fakes), fakes


def _run(orchestrator: CampaignOrchestrator, **overrides) -> dict[str, Any]:
    kwargs = dict(
        ble_channel=37, duration_seconds=10.0, gain_db=20.0, condition_label="target on",
        physical_unit_id="UNIT-01", project_id="P1", campaign_id="C1", session_index=1,
    )
    kwargs.update(overrides)
    return orchestrator.run_session(**kwargs)


def test_run_session_succeeds_end_to_end_on_a_single_fully_processed_chunk():
    orchestrator, fakes = _orchestrator()
    result = _run(orchestrator)

    assert result["capture_id"] == "BLE-IQ-fake"
    assert result["session_id"] == "BLE-HYBRID-fake-0001"
    assert result["evidence_summary"] == {"eligible_examples": 5}
    assert fakes["repository"].evidence_calls  # evidence was actually built
    assert fakes["arbiter"].acquired and fakes["arbiter"].released  # always released


def test_run_session_resumes_a_partial_replay_until_fully_processed():
    capture_manager = FakeCaptureManager([
        {"state": "completed", "result": {"exit_status": "PARTIAL"}},
        {"state": "completed", "result": {"exit_status": "PARTIAL"}},
        {"state": "completed", "result": {"exit_status": "FULLY_PROCESSED"}},
    ])
    orchestrator, fakes = _orchestrator(capture_manager=capture_manager)
    result = _run(orchestrator)

    assert result["capture_id"] == "BLE-IQ-fake"
    # First call starts fresh (no replay_run_id yet); the two resumes must
    # reference the SAME replay_run_id to actually continue from checkpoint.
    assert capture_manager.resume_calls[0].get("replay_run_id") is None
    assert capture_manager.resume_calls[1]["replay_run_id"] == "BLE-RFFI-REPLAY-fake"
    assert capture_manager.resume_calls[2]["replay_run_id"] == "BLE-RFFI-REPLAY-fake"
    assert len(capture_manager.resume_calls) == 3


def test_run_session_gives_up_after_max_resumes_without_building_evidence():
    always_partial = [{"state": "completed", "result": {"exit_status": "PARTIAL"}} for _ in range(_MAX_REPLAY_RESUMES + 1)]
    capture_manager = FakeCaptureManager(always_partial)
    orchestrator, fakes = _orchestrator(capture_manager=capture_manager)

    with pytest.raises(CampaignSessionError, match="OFFLINE_REPLAY_DID_NOT_REACH_FULLY_PROCESSED"):
        _run(orchestrator)

    assert not fakes["repository"].evidence_calls  # never built evidence from an incomplete decode
    assert fakes["arbiter"].released  # still released the device on failure


def test_run_session_raises_on_offline_replay_failure():
    capture_manager = FakeCaptureManager([{"state": "failed", "error": "decoder crashed"}])
    orchestrator, fakes = _orchestrator(capture_manager=capture_manager)

    with pytest.raises(CampaignSessionError, match="OFFLINE_REPLAY_FAILED"):
        _run(orchestrator)
    assert not fakes["repository"].evidence_calls


def test_run_session_raises_on_hybrid_session_failure_and_still_releases_device():
    hybrid_manager = FakeHybridManager(final_state="failed")
    orchestrator, fakes = _orchestrator(hybrid_manager=hybrid_manager)

    with pytest.raises(CampaignSessionError, match="HYBRID_SESSION_FAILED"):
        _run(orchestrator)
    assert fakes["arbiter"].released


def test_run_session_retries_automatically_on_transient_rf_overflow_and_succeeds():
    hybrid_manager = FlakyThenSucceedsHybridManager(failures_before_success=3)
    orchestrator, fakes = _orchestrator(hybrid_manager=hybrid_manager)

    result = _run(orchestrator)

    assert result["capture_id"] == "BLE-IQ-fake"
    assert hybrid_manager.start_calls == 4  # 3 real, measured RF overflows absorbed, 4th succeeded
    assert fakes["arbiter"].acquired  # only acquired ONCE, not once per attempt
    assert len(fakes["arbiter"].acquired) == 1
    assert fakes["arbiter"].released


def test_run_session_gives_up_after_max_capture_attempts_of_transient_rf_overflow():
    hybrid_manager = FlakyThenSucceedsHybridManager(failures_before_success=_MAX_CAPTURE_ATTEMPTS + 5)
    orchestrator, fakes = _orchestrator(hybrid_manager=hybrid_manager)

    with pytest.raises(CampaignSessionError, match="HYBRID_SESSION_FAILED"):
        _run(orchestrator)

    assert hybrid_manager.start_calls == _MAX_CAPTURE_ATTEMPTS  # never retries beyond the cap
    assert fakes["arbiter"].released
    assert not fakes["repository"].built_captures  # never fabricated a capture from a failed acquisition


def test_run_session_does_not_retry_a_non_overflow_hybrid_failure():
    hybrid_manager = FakeHybridManager(final_state="failed")  # error="boom", not CAPTURE_FAILED
    orchestrator, fakes = _orchestrator(hybrid_manager=hybrid_manager)

    with pytest.raises(CampaignSessionError, match="HYBRID_SESSION_FAILED"):
        _run(orchestrator)
    assert len(hybrid_manager.started_payloads) == 1  # not blindly retried -- a different, real problem


def test_run_session_raises_when_device_is_busy_and_never_calls_hybrid_manager():
    arbiter = FakeArbiter(granted=False)
    hybrid_manager = FakeHybridManager()
    orchestrator, fakes = _orchestrator(arbiter=arbiter, hybrid_manager=hybrid_manager)

    with pytest.raises(CampaignSessionError, match="B200_BUSY"):
        _run(orchestrator)
    assert not hybrid_manager.started_payloads
    assert not arbiter.released  # never acquired, so nothing to release


def test_every_session_uses_exploratory_target_search_regardless_of_declared_task():
    hybrid_manager = FakeHybridManager()
    orchestrator, _ = _orchestrator(hybrid_manager=hybrid_manager)
    _run(orchestrator)

    payload = hybrid_manager.started_payloads[0]
    assert payload["campaign_intent"] == "exploratory_target_search"
    assert payload["target"] == {"kind": "any"}


def test_isolation_declared_passes_the_physical_unit_id_through_to_build_capture():
    orchestrator, fakes = _orchestrator()
    _run(orchestrator, physical_unit_id="UNIT-01", isolation_declared=True)

    assert fakes["repository"].built_captures[0]["isolation_declared_physical_unit_id"] == "UNIT-01"


def test_isolation_declared_false_never_sets_isolation_on_the_capture():
    orchestrator, fakes = _orchestrator()
    _run(orchestrator, physical_unit_id="UNIT-01", isolation_declared=False)

    assert fakes["repository"].built_captures[0]["isolation_declared_physical_unit_id"] is None


def test_isolation_declared_without_a_physical_unit_id_is_rejected():
    # Isolation is only ever declared on a TARGET_DEVICE capture (see
    # test_background_environment_forces_isolation_off), which already
    # requires physical_unit_id -- so this is really the same guard as
    # test_target_device_without_a_physical_unit_id_is_rejected below.
    orchestrator, fakes = _orchestrator()
    with pytest.raises(CampaignSessionError, match="TARGET_DEVICE_REQUIRES_A_PHYSICAL_UNIT_ID"):
        _run(orchestrator, physical_unit_id=None, isolation_declared=True)
    assert not fakes["repository"].built_captures  # never even reached the capture stage
    assert not fakes["arbiter"].acquired  # fails fast, before touching the B200 at all


def test_target_device_without_a_physical_unit_id_is_rejected():
    orchestrator, fakes = _orchestrator()
    with pytest.raises(CampaignSessionError, match="TARGET_DEVICE_REQUIRES_A_PHYSICAL_UNIT_ID"):
        _run(orchestrator, physical_unit_id=None, capture_purpose="TARGET_DEVICE")
    assert not fakes["repository"].built_captures
    assert not fakes["arbiter"].acquired


def test_background_environment_without_operator_confirmation_is_rejected():
    orchestrator, fakes = _orchestrator()
    with pytest.raises(CampaignSessionError, match="BACKGROUND_ENVIRONMENT_REQUIRES_OPERATOR_CONFIRMATION"):
        _run(orchestrator, physical_unit_id=None, capture_purpose="BACKGROUND_ENVIRONMENT", operator_confirmed_target_absent=False)
    assert not fakes["repository"].built_captures
    assert not fakes["arbiter"].acquired


def test_unknown_capture_purpose_is_rejected():
    orchestrator, fakes = _orchestrator()
    with pytest.raises(CampaignSessionError, match="UNKNOWN_CAPTURE_PURPOSE"):
        _run(orchestrator, capture_purpose="SOMETHING_ELSE")
    assert not fakes["arbiter"].acquired


def test_target_device_capture_records_powered_on_target_state_and_positive_dataset_role():
    orchestrator, fakes = _orchestrator()
    _run(orchestrator, capture_purpose="TARGET_DEVICE")

    built = fakes["repository"].built_captures[0]
    assert built["capture_purpose"] == "TARGET_DEVICE"
    assert built["target_state"] == "POWERED_ON"
    assert built["dataset_role"] == "POSITIVE_CANDIDATE"
    assert built["target_reference_id"] == "UNIT-01"


def test_background_environment_capture_records_declared_absent_target_state_and_negative_dataset_role():
    orchestrator, fakes = _orchestrator()
    result = _run(
        orchestrator, physical_unit_id="UNIT-01", capture_purpose="BACKGROUND_ENVIRONMENT",
        operator_confirmed_target_absent=True,
    )

    built = fakes["repository"].built_captures[0]
    assert built["capture_purpose"] == "BACKGROUND_ENVIRONMENT"
    assert built["target_state"] == "OPERATOR_DECLARED_POWERED_OFF_OR_REMOVED"
    assert built["dataset_role"] == "NEGATIVE_CANDIDATE"
    assert built["target_reference_id"] == "UNIT-01"  # documentary only -- never a positive ground truth
    assert result["capture_purpose"] == "BACKGROUND_ENVIRONMENT"


def test_background_environment_capture_allows_no_target_reference_id():
    orchestrator, fakes = _orchestrator()
    _run(orchestrator, physical_unit_id=None, capture_purpose="BACKGROUND_ENVIRONMENT", operator_confirmed_target_absent=True)

    built = fakes["repository"].built_captures[0]
    assert built["target_reference_id"] is None
    assert built["isolation_declared_physical_unit_id"] is None


def test_background_environment_forces_isolation_off_even_if_caller_requests_it():
    orchestrator, fakes = _orchestrator()
    _run(
        orchestrator, physical_unit_id="UNIT-01", capture_purpose="BACKGROUND_ENVIRONMENT",
        operator_confirmed_target_absent=True, isolation_declared=True,
    )

    built = fakes["repository"].built_captures[0]
    assert built["isolation_declared_physical_unit_id"] is None
