"""REST surface for BLE Scientific Results Studio -- Fase 1 only (protocol
freeze, holdout access log, run creation, preflight). Thin by design, same
convention as ble_rffi_studio's studio_routes.py: every route calls straight
into ScientificResultsRepository/ScientificResultsJobManager and maps
exceptions to status codes.

The remaining endpoints from the full specification (power-simulation,
rq1-4, channel-transport, online-equivalence, forensic-calibration, export,
artifacts) are registered in later phases once the analysis code behind them
exists -- they are intentionally absent here rather than stubbed, so the
route surface never implies a capability that does not exist yet.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException


def build_ble_scientific_results_router(repository, job_manager) -> APIRouter:
    router = APIRouter(prefix="/ble-scientific-results", tags=["ble-scientific-results"])

    def call(fn):
        try:
            return fn()
        except FileNotFoundError as error:
            raise HTTPException(404, str(error) or "NOT_FOUND") from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        except RuntimeError as error:
            raise HTTPException(409, str(error)) from error

    def dump(obj):
        return obj.model_dump(mode="json") if hasattr(obj, "model_dump") else obj

    def dump_list(objs):
        return [dump(o) for o in objs]

    # ------------------------------------------------------------------
    # Protocol
    # ------------------------------------------------------------------

    @router.post("/protocols", status_code=201)
    def freeze_protocol(body: dict):
        return call(lambda: dump(repository.freeze_protocol(body)))

    @router.get("/protocols/{protocol_id}")
    def get_protocol(protocol_id: str, version: int | None = None):
        return call(lambda: dump(repository.get_protocol(protocol_id, version)))

    @router.get("/protocols/{protocol_id}/versions")
    def list_protocol_versions(protocol_id: str):
        return call(lambda: dump_list(repository.list_protocol_versions(protocol_id)))

    # ------------------------------------------------------------------
    # Holdout access log
    # ------------------------------------------------------------------

    @router.get("/holdout-access-log")
    def holdout_access_log():
        return call(lambda: dump_list(repository.list_holdout_access_log()))

    @router.post("/holdout-access-log", status_code=201)
    def log_holdout_access(body: dict):
        return call(lambda: dump(repository.log_holdout_access(
            actor=body["actor"], process=body["process"], access_type=body["access_type"], access_path=body["access_path"],
            resource_id=body["resource_id"], resource_hash=body.get("resource_hash"), reason=body["reason"],
            paper_run_id=body.get("paper_run_id"), analysis_contract_hash=body.get("analysis_contract_hash"),
        )))

    @router.get("/holdout-access-log/verify")
    def verify_holdout_access_chain():
        return call(lambda: dump(repository.verify_holdout_access_chain()))

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    @router.post("/runs", status_code=201)
    def create_run(body: dict):
        return call(lambda: dump(repository.create_run(
            protocol_id=body["protocol_id"], protocol_version=body.get("protocol_version"), campaign_id=body["campaign_id"],
            dataset_id=body["dataset_id"], dataset_version=body["dataset_version"], scientific_task=body["scientific_task"],
        )))

    @router.get("/runs")
    def list_runs():
        return call(lambda: dump_list(repository.list_runs()))

    @router.get("/runs/{paper_run_id}")
    def get_run(paper_run_id: str):
        return call(lambda: dump(repository.get_run(paper_run_id)))

    # ------------------------------------------------------------------
    # Preflight / readiness
    # ------------------------------------------------------------------

    @router.post("/preflight", status_code=202)
    def start_preflight(body: dict):
        return call(lambda: job_manager.start_preflight_job(paper_run_id=body["paper_run_id"]))

    @router.get("/jobs/{job_id}")
    def get_job(job_id: str):
        return call(lambda: job_manager.get_job(job_id))

    @router.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        return call(lambda: job_manager.cancel_job(job_id))

    @router.get("/runs/{paper_run_id}/readiness")
    def readiness(paper_run_id: str):
        def resolve():
            report = repository.get_preflight_report(paper_run_id)
            if report is None:
                return {"paper_run_id": paper_run_id, "overall_status": None, "message": "Preflight has not run yet for this paper_run_id."}
            return dump(report)
        return call(resolve)

    # ------------------------------------------------------------------
    # Fase 2: canonical records, campaign accounting, quality, figures
    # ------------------------------------------------------------------

    @router.post("/runs/{paper_run_id}/build-records", status_code=202)
    def start_build_records(paper_run_id: str):
        return call(lambda: job_manager.start_build_records_job(paper_run_id=paper_run_id))

    @router.get("/runs/{paper_run_id}/records/status")
    def records_status(paper_run_id: str):
        def resolve():
            status = repository.get_records_status(paper_run_id)
            if status is None:
                return {"paper_run_id": paper_run_id, "built": False}
            return {"paper_run_id": paper_run_id, "built": True, **dump(status)}
        return call(resolve)

    @router.get("/runs/{paper_run_id}/campaign-accounting")
    def campaign_accounting(paper_run_id: str):
        def resolve():
            result = repository.get_campaign_accounting(paper_run_id)
            if result is None:
                raise FileNotFoundError(f"CAMPAIGN_ACCOUNTING_NOT_BUILT:{paper_run_id}")
            return result
        return call(resolve)

    @router.get("/runs/{paper_run_id}/deviations")
    def deviations(paper_run_id: str, limit: int = 200, offset: int = 0):
        return call(lambda: repository.list_deviation_records(paper_run_id, limit=limit, offset=offset))

    @router.get("/runs/{paper_run_id}/quality-summary")
    def quality_summary(paper_run_id: str):
        def resolve():
            result = repository.get_quality_summary(paper_run_id)
            if result is None:
                raise FileNotFoundError(f"QUALITY_SUMMARY_NOT_BUILT:{paper_run_id}")
            return result
        return call(resolve)

    @router.get("/runs/{paper_run_id}/captures")
    def captures(paper_run_id: str, limit: int = 100, offset: int = 0):
        return call(lambda: repository.list_capture_records(paper_run_id, limit=limit, offset=offset))

    @router.get("/runs/{paper_run_id}/captures/{capture_id}")
    def capture_detail(paper_run_id: str, capture_id: str):
        def resolve():
            record = repository.get_capture_record(paper_run_id, capture_id)
            if record is None:
                raise FileNotFoundError(f"CAPTURE_RECORD_NOT_FOUND:{paper_run_id}:{capture_id}")
            return record
        return call(resolve)

    @router.get("/runs/{paper_run_id}/bursts")
    def bursts(paper_run_id: str, limit: int = 100, offset: int = 0, capture_id: str | None = None):
        return call(lambda: repository.list_burst_records(paper_run_id, limit=limit, offset=offset, capture_id=capture_id))

    @router.get("/runs/{paper_run_id}/windows")
    def windows(paper_run_id: str, limit: int = 100, offset: int = 0, capture_id: str | None = None):
        return call(lambda: repository.list_window_records(paper_run_id, limit=limit, offset=offset, capture_id=capture_id))

    @router.get("/runs/{paper_run_id}/artifacts")
    def artifacts(paper_run_id: str):
        return call(lambda: {"paper_run_id": paper_run_id, "files": repository.list_run_artifacts(paper_run_id)})

    # ------------------------------------------------------------------
    # Guided BLE Scientific Validation -- one orchestrator job spanning
    # every enrolled device's existing dataset. See guided_validation/
    # service.py: it only invokes repository.freeze_protocol/create_run/
    # build_records and calibration.select_association_policy, never a
    # second decoder or records builder.
    # ------------------------------------------------------------------

    @router.post("/guided-validation", status_code=202)
    def start_guided_validation():
        return call(lambda: job_manager.start_guided_validation_job())

    @router.get("/guided-validation/{job_id}")
    def get_guided_validation(job_id: str):
        return call(lambda: job_manager.get_job(job_id))

    # ------------------------------------------------------------------
    # Guided Validation hardware actions -- real, short, supervised
    # captures. See guided_validation/service.py: only CampaignOrchestrator.
    # run_session() ever touches the SDR/native scanner/arbiter.
    # ------------------------------------------------------------------

    @router.post("/guided-validation/{run_id}/timing-diagnostic", status_code=202)
    def start_timing_diagnostic(run_id: str, body: dict):
        return call(lambda: job_manager.start_timing_diagnostic_job(
            run_id=run_id, physical_unit_id=body["physical_unit_id"], capture_duration_s=float(body.get("capture_duration_s", 180.0)),
            channel=int(body.get("channel", 37)), receiver_profile=body.get("receiver_profile"), operator_id=body.get("operator_id"),
        ))

    @router.post("/guided-validation/{run_id}/target-absence-control", status_code=202)
    def start_target_absence_control(run_id: str, body: dict):
        return call(lambda: job_manager.start_target_absence_control_job(
            run_id=run_id, confirmed_devices_off=body["confirmed_devices_off"], capture_duration_s=float(body.get("capture_duration_s", 180.0)),
            channel=int(body.get("channel", 37)), operator_id=body.get("operator_id"),
        ))

    @router.get("/guided-validation/{run_id}/actions/{action_job_id}")
    def get_guided_validation_action(run_id: str, action_job_id: str):
        return call(lambda: job_manager.get_job(action_job_id))

    return router
