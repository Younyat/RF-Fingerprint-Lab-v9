"""Background jobs for BLE Scientific Results Studio. Same job.json /
background-thread pattern as ble_rffi_studio's StudioJobManager (stage,
progress, elapsed time via started_at/updated_at, cancel state), reused here
independently since this module runs its own, unrelated jobs (preflight
scans tens of thousands of ExampleRecords -- slow enough to need progress
reporting, but it never touches the B200 or any other exclusive hardware
resource ble_rffi_studio's own jobs serialize on).

Cancellation never deletes partial artifacts: run_preflight() writes its
report only once fully computed, so a cancelled job simply leaves no
02_integrity/scientific_preflight_report.json behind, never a half-written
one.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.infrastructure.ble.capture.ble_capture_metadata import atomic_json

from ..module_logging import build_module_logger
from .scientific_results_repository import ScientificResultsRepository

TERMINAL = {"completed", "failed", "cancelled"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ScientificResultsJobManager:
    def __init__(self, repository: ScientificResultsRepository, jobs_root: Path) -> None:
        self.repository = repository
        self.jobs_root = jobs_root
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        self.logger = build_module_logger(jobs_root.parent)
        self._cancel_flags: dict[str, threading.Event] = {}

    def _job_dir(self, job_id: str) -> Path:
        if not job_id.startswith("BLE-SCI-RESULTS-JOB-") or any(part in job_id for part in ("/", "\\", "..")):
            raise ValueError("INVALID_JOB_ID")
        return self.jobs_root / job_id

    def _new_job_id(self) -> str:
        return "BLE-SCI-RESULTS-JOB-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]

    def _write(self, job_dir: Path, state: str, **fields: Any) -> None:
        path = job_dir / "job.json"
        previous = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        merged = {**previous, **fields, "state": state, "updated_at": utc_now()}
        atomic_json(path, merged)
        job_id = merged.get("job_id") or job_dir.name
        job_type = merged.get("job_type", "UNKNOWN")
        if state == "failed":
            self.logger.error("[%s] job=%s state=%s error=%s", job_type, job_id, state, merged.get("error"))
        else:
            self.logger.info("[%s] job=%s state=%s stage=%s progress=%s message=%s", job_type, job_id, state, merged.get("stage"), merged.get("overall_progress"), merged.get("message"))

    def get_job(self, job_id: str) -> dict[str, Any]:
        path = self._job_dir(job_id) / "job.json"
        if not path.is_file():
            raise FileNotFoundError("SCIENTIFIC_RESULTS_JOB_NOT_FOUND")
        return json.loads(path.read_text(encoding="utf-8"))

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job.get("state") not in TERMINAL:
            self._cancel_flags.setdefault(job_id, threading.Event()).set()
        return self.get_job(job_id)

    # ------------------------------------------------------------------
    # Preflight
    # ------------------------------------------------------------------

    def start_preflight_job(self, *, paper_run_id: str) -> dict[str, Any]:
        job_id = self._new_job_id()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        cancel_event = threading.Event()
        self._cancel_flags[job_id] = cancel_event
        atomic_json(job_dir / "job.json", {
            "schema_version": "ble-scientific-results-job-v1", "job_id": job_id, "job_type": "PREFLIGHT",
            "paper_run_id": paper_run_id, "state": "queued", "stage": None, "overall_progress": 0.0,
            "message": None, "warnings": [], "started_at": utc_now(), "updated_at": utc_now(),
        })
        threading.Thread(target=self._run_preflight_job, args=(job_id, paper_run_id, cancel_event), daemon=True).start()
        return self.get_job(job_id)

    def _run_preflight_job(self, job_id: str, paper_run_id: str, cancel_event: threading.Event) -> None:
        job_dir = self._job_dir(job_id)
        self._write(job_dir, "running", job_type="PREFLIGHT", paper_run_id=paper_run_id, stage="starting", overall_progress=0.0, message="Starting scientific preflight")
        try:
            def progress(stage: str, fraction: float, message: str) -> None:
                if cancel_event.is_set():
                    raise RuntimeError("PREFLIGHT_CANCELLED")
                self._write(job_dir, "running", job_type="PREFLIGHT", paper_run_id=paper_run_id, stage=stage, overall_progress=fraction, message=str(message))

            report = self.repository.run_preflight(paper_run_id, progress=progress)
            self._write(job_dir, "completed", job_type="PREFLIGHT", paper_run_id=paper_run_id, stage="done", overall_progress=1.0, message=report.overall_status, overall_status=report.overall_status)
        except RuntimeError as error:
            if str(error) == "PREFLIGHT_CANCELLED":
                self._write(job_dir, "cancelled", job_type="PREFLIGHT", paper_run_id=paper_run_id, message="Cancelled by operator")
            else:
                self._write(job_dir, "failed", job_type="PREFLIGHT", paper_run_id=paper_run_id, error=str(error))
        except Exception as error:  # noqa: BLE001 -- job failure must always be recorded, never silently swallowed
            self._write(job_dir, "failed", job_type="PREFLIGHT", paper_run_id=paper_run_id, error=str(error))
        finally:
            self._cancel_flags.pop(job_id, None)

    # ------------------------------------------------------------------
    # Fase 2: build-records (canonical records + campaign accounting +
    # quality summary + figures, in that order -- the one async job the
    # Fase 2 endpoint surface (Section H) exposes; every downstream GET
    # endpoint just reads what this job already wrote to disk)
    # ------------------------------------------------------------------

    def start_build_records_job(self, *, paper_run_id: str) -> dict[str, Any]:
        job_id = self._new_job_id()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        cancel_event = threading.Event()
        self._cancel_flags[job_id] = cancel_event
        atomic_json(job_dir / "job.json", {
            "schema_version": "ble-scientific-results-job-v1", "job_id": job_id, "job_type": "BUILD_RECORDS",
            "paper_run_id": paper_run_id, "state": "queued", "stage": None, "overall_progress": 0.0,
            "message": None, "warnings": [], "started_at": utc_now(), "updated_at": utc_now(),
        })
        threading.Thread(target=self._run_build_records_job, args=(job_id, paper_run_id, cancel_event), daemon=True).start()
        return self.get_job(job_id)

    def _run_build_records_job(self, job_id: str, paper_run_id: str, cancel_event: threading.Event) -> None:
        job_dir = self._job_dir(job_id)
        self._write(job_dir, "running", job_type="BUILD_RECORDS", paper_run_id=paper_run_id, stage="records", overall_progress=0.0, message="Building canonical records")
        try:
            def progress(stage: str, fraction: float, message: str) -> None:
                if cancel_event.is_set():
                    raise RuntimeError("BUILD_RECORDS_CANCELLED")
                # Records is stage 1 of 4 (0.0-0.6), accounting/quality/figures share the rest.
                overall = 0.6 * fraction
                self._write(job_dir, "running", job_type="BUILD_RECORDS", paper_run_id=paper_run_id, stage=f"records:{stage}", overall_progress=overall, message=str(message))

            result = self.repository.build_records(paper_run_id, progress=progress)

            if cancel_event.is_set():
                raise RuntimeError("BUILD_RECORDS_CANCELLED")
            self._write(job_dir, "running", job_type="BUILD_RECORDS", paper_run_id=paper_run_id, stage="campaign_accounting", overall_progress=0.7, message="Building campaign accounting")
            self.repository.build_campaign_accounting(paper_run_id)

            if cancel_event.is_set():
                raise RuntimeError("BUILD_RECORDS_CANCELLED")
            self._write(job_dir, "running", job_type="BUILD_RECORDS", paper_run_id=paper_run_id, stage="quality_summary", overall_progress=0.85, message="Building descriptive quality summary")
            self.repository.build_quality_summary(paper_run_id)

            if cancel_event.is_set():
                raise RuntimeError("BUILD_RECORDS_CANCELLED")
            self._write(job_dir, "running", job_type="BUILD_RECORDS", paper_run_id=paper_run_id, stage="figures", overall_progress=0.95, message="Generating descriptive figures")
            self.repository.build_campaign_figures(paper_run_id)

            self._write(
                job_dir, "completed", job_type="BUILD_RECORDS", paper_run_id=paper_run_id, stage="done", overall_progress=1.0,
                message="Canonical records, campaign accounting, quality summary, and figures built",
                capture_record_count=result.capture_record_count, burst_record_count=result.burst_record_count,
                decision_window_record_count=result.decision_window_record_count, campaign_deviation_count=result.campaign_deviation_count,
            )
        except RuntimeError as error:
            if str(error) == "BUILD_RECORDS_CANCELLED":
                self._write(job_dir, "cancelled", job_type="BUILD_RECORDS", paper_run_id=paper_run_id, message="Cancelled by operator")
            else:
                self._write(job_dir, "failed", job_type="BUILD_RECORDS", paper_run_id=paper_run_id, error=str(error))
        except Exception as error:  # noqa: BLE001
            self._write(job_dir, "failed", job_type="BUILD_RECORDS", paper_run_id=paper_run_id, error=str(error))
        finally:
            self._cancel_flags.pop(job_id, None)
