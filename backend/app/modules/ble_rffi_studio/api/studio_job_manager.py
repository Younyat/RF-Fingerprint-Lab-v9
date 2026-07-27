"""Background jobs for the two Studio operations slow enough to need
progress reporting: Evidence Stage build (hundreds of packets) and model
training. Same job.json/background-thread pattern as BleCaptureJobManager
and BlePacketAnalysisJobManager, so the frontend's existing operationTelemetry
integration works unchanged.

Unlike BLE capture jobs, these never touch the B200 or any other exclusive
hardware resource (the IQ is already captured), so -- unlike those managers --
multiple Studio jobs are allowed to run concurrently; there is no shared
resource here to serialize.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.infrastructure.ble.capture.ble_capture_metadata import atomic_json

from ..contracts import TrainingRun
from .studio_repository import StudioRepository

TERMINAL = {"completed", "failed", "cancelled"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class StudioJobManager:
    def __init__(self, repository: StudioRepository, jobs_root: Path) -> None:
        self.repository = repository
        self.jobs_root = jobs_root
        self.jobs_root.mkdir(parents=True, exist_ok=True)

    def _job_dir(self, job_id: str) -> Path:
        if not job_id.startswith("BLE-RFFI-STUDIO-JOB-") or any(part in job_id for part in ("/", "\\", "..")):
            raise ValueError("INVALID_JOB_ID")
        return self.jobs_root / job_id

    def _new_job_id(self) -> str:
        return "BLE-RFFI-STUDIO-JOB-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]

    def _write(self, job_dir: Path, state: str, **fields: Any) -> None:
        path = job_dir / "job.json"
        previous = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        atomic_json(path, {**previous, **fields, "state": state, "updated_at": utc_now()})

    def get_job(self, job_id: str) -> dict[str, Any]:
        path = self._job_dir(job_id) / "job.json"
        if not path.is_file():
            raise FileNotFoundError("STUDIO_JOB_NOT_FOUND")
        return json.loads(path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Evidence Build
    # ------------------------------------------------------------------

    def start_evidence_job(self, *, capture_id: str, project_id: str, ble_channel: int, replay_run_id: str | None = None) -> dict[str, Any]:
        job_id = self._new_job_id()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        atomic_json(job_dir / "job.json", {
            "schema_version": "ble-rffi-studio-job-v1", "job_id": job_id, "job_type": "EVIDENCE_BUILD",
            "capture_id": capture_id, "state": "queued", "phase": None, "phase_progress": 0.0,
            "overall_progress": 0.0, "message": None, "started_at": utc_now(), "updated_at": utc_now(),
        })
        threading.Thread(target=self._run_evidence_job, args=(job_id, capture_id, project_id, ble_channel, replay_run_id), daemon=True).start()
        return self.get_job(job_id)

    def _run_evidence_job(self, job_id: str, capture_id: str, project_id: str, ble_channel: int, replay_run_id: str | None) -> None:
        job_dir = self._job_dir(job_id)

        def progress(phase: str, phase_progress: float, message: str) -> None:
            self._write(job_dir, "running", phase=phase, phase_progress=phase_progress, overall_progress=round(phase_progress, 4), message=message)

        try:
            capture = self.repository.get_capture(capture_id)
            if capture is None:
                raise FileNotFoundError(f"CAPTURE_NOT_BUILT_YET:{capture_id}")
            summary = self.repository.build_evidence(capture=capture, project_id=project_id, ble_channel=ble_channel, replay_run_id=replay_run_id, progress=progress)
            self._write(job_dir, "completed", overall_progress=1.0, phase="COMPLETED", result_summary=summary)
        except Exception as error:
            self._write(job_dir, "failed", error=f"{type(error).__name__}: {error}")

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def start_training_job(self, *, training_run: TrainingRun) -> dict[str, Any]:
        job_id = self._new_job_id()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        atomic_json(job_dir / "job.json", {
            "schema_version": "ble-rffi-studio-job-v1", "job_id": job_id, "job_type": "TRAINING_RUN",
            "training_run_id": training_run.training_run_id, "state": "queued", "phase": None, "phase_progress": 0.0,
            "overall_progress": 0.0, "message": None, "started_at": utc_now(), "updated_at": utc_now(),
        })
        threading.Thread(target=self._run_training_job, args=(job_id, training_run), daemon=True).start()
        return self.get_job(job_id)

    def _run_training_job(self, job_id: str, training_run: TrainingRun) -> None:
        job_dir = self._job_dir(job_id)

        def progress(phase: str, phase_progress: float, message: str) -> None:
            self._write(job_dir, "running", phase=phase, phase_progress=phase_progress, overall_progress=round(phase_progress, 4), message=message)

        try:
            completed_run = self.repository.run_training(training_run=training_run, progress=progress)
            self._write(job_dir, "completed", overall_progress=1.0, phase="COMPLETED", training_run_id=completed_run.training_run_id)
        except Exception as error:
            self._write(job_dir, "failed", error=f"{type(error).__name__}: {error}")

    # ------------------------------------------------------------------
    # Guided orchestration: "Prepare dataset and train"
    # ------------------------------------------------------------------

    def start_prepare_and_train_job(self, **kwargs: Any) -> dict[str, Any]:
        job_id = self._new_job_id()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        atomic_json(job_dir / "job.json", {
            "schema_version": "ble-rffi-studio-job-v1", "job_id": job_id, "job_type": "PREPARE_AND_TRAIN",
            "state": "queued", "phase": None, "phase_progress": 0.0, "overall_progress": 0.0,
            "message": None, "started_at": utc_now(), "updated_at": utc_now(),
        })
        threading.Thread(target=self._run_prepare_and_train_job, args=(job_id,), kwargs=kwargs, daemon=True).start()
        return self.get_job(job_id)

    def _run_prepare_and_train_job(self, job_id: str, **kwargs: Any) -> None:
        job_dir = self._job_dir(job_id)

        def progress(phase: str, phase_progress: float, message: str) -> None:
            self._write(job_dir, "running", phase=phase, phase_progress=phase_progress, overall_progress=round(phase_progress, 4), message=message)

        try:
            result = self.repository.prepare_and_train(progress=progress, **kwargs)
            self._write(job_dir, "completed", overall_progress=1.0, phase="COMPLETED", result_summary=self._summarize_result(result))
        except Exception as error:
            self._write(job_dir, "failed", error=f"{type(error).__name__}: {error}")

    # ------------------------------------------------------------------
    # Real capture campaign session (B200 + native scan)
    # ------------------------------------------------------------------

    def start_campaign_session_job(self, **kwargs: Any) -> dict[str, Any]:
        job_id = self._new_job_id()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        atomic_json(job_dir / "job.json", {
            "schema_version": "ble-rffi-studio-job-v1", "job_id": job_id, "job_type": "CAMPAIGN_SESSION",
            "state": "queued", "phase": None, "phase_progress": 0.0, "overall_progress": 0.0,
            "message": None, "started_at": utc_now(), "updated_at": utc_now(),
        })
        threading.Thread(target=self._run_campaign_session_job, args=(job_id,), kwargs=kwargs, daemon=True).start()
        return self.get_job(job_id)

    def _run_campaign_session_job(self, job_id: str, **kwargs: Any) -> None:
        job_dir = self._job_dir(job_id)

        def progress(phase: str, phase_progress: float, message: str) -> None:
            self._write(job_dir, "running", phase=phase, phase_progress=phase_progress, overall_progress=round(phase_progress, 4), message=message)

        try:
            result = self.repository.run_campaign_session(progress=progress, **kwargs)
            self._write(job_dir, "completed", overall_progress=1.0, phase="COMPLETED", result_summary=result)
        except Exception as error:
            self._write(job_dir, "failed", error=f"{type(error).__name__}: {error}")

    def _summarize_result(self, result: dict[str, Any]) -> dict[str, Any]:
        dataset = result.get("dataset")
        split = result.get("split")
        return {
            "stopped_at": result.get("stopped_at"),
            "stopped_reason": result.get("stopped_reason"),
            "dataset_id": getattr(dataset, "dataset_id", None),
            "dataset_version": getattr(dataset, "dataset_version", None),
            "data_origin": getattr(dataset, "data_origin", None),
            "split_status": getattr(split, "split_status", None),
            "feasibility": result.get("feasibility"),
            "trained_models": [{"training_run_id": m["training_run_id"], "model_type": m["model_type"], "composite_score": m["score"]["composite_score"]} for m in result.get("trained_models", [])],
            "skipped_models": result.get("skipped_models", []),
            "recommended_training_run_id": result.get("recommended_training_run_id"),
            "recommended_reason": result.get("recommended_reason"),
            "final_test_evaluation": result.get("final_test_evaluation"),
        }
