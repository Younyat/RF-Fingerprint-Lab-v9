"""REST surface for the BLE-RFFI End-to-End Studio. Thin by design: every
route calls straight into StudioRepository/StudioJobManager, which already
carry all the real logic and persistence -- this file only translates
HTTP <-> Python calls and maps exceptions to status codes, same convention
as ble_packet_analysis_routes.py.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..contracts import TrainingRun


def build_ble_rffi_studio_router(repository, job_manager) -> APIRouter:
    router = APIRouter(prefix="/ble-rffi-studio", tags=["ble-rffi-studio"])

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
    # Legacy captures (read-only, reused from Phase 2)
    # ------------------------------------------------------------------

    @router.get("/legacy-captures")
    def legacy_captures():
        return call(repository.list_legacy_captures)

    # ------------------------------------------------------------------
    # Physical Device Registry
    # ------------------------------------------------------------------

    @router.get("/physical-units")
    def physical_units():
        return call(lambda: dump_list(repository.list_physical_units()))

    @router.post("/physical-units", status_code=201)
    def create_physical_unit(body: dict):
        return call(lambda: dump(repository.register_physical_unit(
            physical_unit_id=body["physical_unit_id"], project_id=body["project_id"], device_family=body["device_family"],
            manufacturer=body.get("manufacturer"), model=body.get("model"), operator_declaration_id=body["operator_declaration_id"],
        )))

    @router.get("/address-bindings")
    def address_bindings():
        return call(lambda: dump_list(repository.list_bindings()))

    @router.post("/address-bindings", status_code=201)
    def create_binding(body: dict):
        return call(lambda: dump(repository.declare_binding(
            project_id=body["project_id"], address=body["address"], address_type=body.get("address_type", "public"),
            physical_unit_id=body["physical_unit_id"], reason=body.get("reason", "Operator declaration"),
            decision_artifact_id=body.get("decision_artifact_id", "manual-declaration"),
        )))

    # ------------------------------------------------------------------
    # Synthetic demo (no SDR hardware required)
    # ------------------------------------------------------------------

    @router.post("/synthetic-demo/seed", status_code=201)
    def seed_synthetic_demo():
        return call(repository.seed_synthetic_demo)

    # ------------------------------------------------------------------
    # Real capture campaign (B200 + native scan)
    # ------------------------------------------------------------------

    @router.get("/campaign/device-status")
    def campaign_device_status():
        return call(repository.campaign_device_status)

    @router.post("/campaign/sessions", status_code=202)
    def start_campaign_session(body: dict):
        return call(lambda: job_manager.start_campaign_session_job(
            ble_channel=body.get("ble_channel", 37), duration_seconds=body.get("duration_seconds", 10.0),
            gain_db=body.get("gain_db", 20.0), condition_label=body["condition_label"],
            physical_unit_id=body.get("physical_unit_id"), project_id=body["project_id"], campaign_id=body["campaign_id"],
            session_index=body.get("session_index", 1), device_id=body.get("device_id"),
            isolation_declared=bool(body.get("isolation_declared", False)),
            capture_purpose=body.get("capture_purpose", "TARGET_DEVICE"),
            operator_confirmed_target_absent=bool(body.get("operator_confirmed_target_absent", False)),
        ))

    # ------------------------------------------------------------------
    # Capture Stage
    # ------------------------------------------------------------------

    @router.get("/captures")
    def captures():
        return call(lambda: dump_list(repository.list_captures()))

    @router.post("/captures", status_code=201)
    def create_capture(body: dict):
        return call(lambda: dump(repository.build_capture(
            capture_id=body["capture_id"], project_id=body["project_id"], campaign_id=body["campaign_id"],
            execution_id=body.get("execution_id"), session_id=body.get("session_id"),
            isolation_declared_physical_unit_id=body.get("isolation_declared_physical_unit_id"),
            capture_purpose=body.get("capture_purpose"), target_state=body.get("target_state"),
            target_reference_id=body.get("target_reference_id"), dataset_role=body.get("dataset_role"),
        )))

    @router.get("/captures/{capture_id}")
    def get_capture(capture_id: str):
        def fn():
            capture = repository.get_capture(capture_id)
            if capture is None:
                raise FileNotFoundError(f"CAPTURE_NOT_BUILT_YET:{capture_id}")
            return dump(capture)
        return call(fn)

    # ------------------------------------------------------------------
    # Evidence Stage (background job -- can process hundreds of packets)
    # ------------------------------------------------------------------

    @router.post("/captures/{capture_id}/evidence-jobs", status_code=202)
    def start_evidence_job(capture_id: str, body: dict):
        return call(lambda: job_manager.start_evidence_job(
            capture_id=capture_id, project_id=body["project_id"], ble_channel=body["ble_channel"], replay_run_id=body.get("replay_run_id"),
        ))

    @router.get("/captures/{capture_id}/examples")
    def list_examples(capture_id: str):
        return call(lambda: dump_list(repository.list_examples(capture_id)))

    @router.get("/captures/{capture_id}/annotations")
    def list_annotations(capture_id: str):
        return call(lambda: dump_list(repository.list_annotations(capture_id)))

    @router.get("/jobs/{job_id}")
    def get_job(job_id: str):
        return call(lambda: job_manager.get_job(job_id))

    # ------------------------------------------------------------------
    # Dataset Builder + Dataset Analyzer
    # ------------------------------------------------------------------

    @router.get("/datasets")
    def datasets():
        return call(lambda: dump_list(repository.list_datasets()))

    @router.post("/datasets", status_code=201)
    def create_dataset(body: dict):
        def fn():
            result = repository.build_dataset(
                dataset_id=body["dataset_id"], dataset_version=body["dataset_version"], project_id=body["project_id"],
                campaign_id=body["campaign_id"], capture_ids=body["capture_ids"], derived_from=body.get("derived_from"),
            )
            return {"dataset": dump(result["dataset"]), "n_selected": result["n_selected"], "n_excluded": result["n_excluded"], "excluded_reasons": result["excluded_reasons"]}
        return call(fn)

    @router.get("/datasets/{dataset_id}/{dataset_version}")
    def get_dataset(dataset_id: str, dataset_version: str):
        def fn():
            dataset = repository.get_dataset(dataset_id, dataset_version)
            if dataset is None:
                raise FileNotFoundError("DATASET_NOT_FOUND")
            return dump(dataset)
        return call(fn)

    @router.post("/datasets/{dataset_id}/{dataset_version}/quality-report")
    def build_quality_report(dataset_id: str, dataset_version: str, body: dict | None = None):
        run_near_duplicates = bool((body or {}).get("run_near_duplicates", False))
        return call(lambda: dump(repository.build_quality_report(dataset_id=dataset_id, dataset_version=dataset_version, run_near_duplicates=run_near_duplicates)))

    @router.get("/datasets/{dataset_id}/{dataset_version}/quality-report")
    def get_quality_report(dataset_id: str, dataset_version: str):
        def fn():
            report = repository.get_quality_report(dataset_id, dataset_version)
            if report is None:
                raise FileNotFoundError("QUALITY_REPORT_NOT_BUILT_YET")
            return dump(report)
        return call(fn)

    # ------------------------------------------------------------------
    # Split Builder
    # ------------------------------------------------------------------

    @router.post("/datasets/{dataset_id}/{dataset_version}/splits/{scientific_task}")
    def build_split(dataset_id: str, dataset_version: str, scientific_task: str):
        return call(lambda: dump(repository.build_split(dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=scientific_task)))

    @router.get("/datasets/{dataset_id}/{dataset_version}/splits/{scientific_task}")
    def get_split(dataset_id: str, dataset_version: str, scientific_task: str):
        def fn():
            split = repository.get_split(dataset_id, dataset_version, scientific_task)
            if split is None:
                raise FileNotFoundError("SPLIT_NOT_BUILT_YET")
            return dump(split)
        return call(fn)

    # ------------------------------------------------------------------
    # Guided mode helpers
    # ------------------------------------------------------------------

    @router.get("/scientific-tasks")
    def scientific_tasks():
        return call(repository.scientific_task_display_names)

    @router.get("/datasets/{dataset_id}/{dataset_version}/feasibility")
    def feasibility(dataset_id: str, dataset_version: str, scientific_task: str):
        def fn():
            dataset = repository.get_dataset(dataset_id, dataset_version)
            if dataset is None:
                raise FileNotFoundError("DATASET_NOT_FOUND")
            examples = repository._dataset_examples(dataset)  # noqa: SLF001 -- read-only helper, no separate public API needed yet
            from ..quality import explain_feasibility
            return explain_feasibility(examples, scientific_task)
        return call(fn)

    @router.get("/datasets/{dataset_id}/{dataset_version}/task-recommendation")
    def task_recommendation(dataset_id: str, dataset_version: str):
        def fn():
            dataset = repository.get_dataset(dataset_id, dataset_version)
            if dataset is None:
                raise FileNotFoundError("DATASET_NOT_FOUND")
            examples = repository._dataset_examples(dataset)  # noqa: SLF001 -- read-only helper, no separate public API needed yet
            from ..quality import recommend_scientific_task
            return recommend_scientific_task(examples)
        return call(fn)

    @router.post("/prepare-and-train", status_code=202)
    def prepare_and_train(body: dict):
        return call(lambda: job_manager.start_prepare_and_train_job(
            capture_ids=body["capture_ids"], project_id=body["project_id"], campaign_id=body["campaign_id"],
            scientific_task=body["scientific_task"], ble_channel=body.get("ble_channel", 37),
            dataset_id=body.get("dataset_id"), dataset_version=body.get("dataset_version", "1.0.0"),
            speed_profile=body.get("speed_profile", "normal"),
        ))

    # ------------------------------------------------------------------
    # Training (background job)
    # ------------------------------------------------------------------

    @router.post("/training-runs", status_code=202)
    def start_training(body: dict):
        def fn():
            dataset = repository.get_dataset(body["dataset_id"], body["dataset_version"])
            if dataset is None:
                raise FileNotFoundError(f"DATASET_NOT_FOUND:{body['dataset_id']}:{body['dataset_version']}")
            training_run = TrainingRun(
                training_run_id=body["training_run_id"], project_id=body["project_id"], campaign_id=body["campaign_id"],
                dataset_id=body["dataset_id"], dataset_version=body["dataset_version"], dataset_manifest_sha256=body["dataset_manifest_sha256"],
                split_manifest_sha256=body["split_manifest_sha256"], scientific_task=body["scientific_task"], model_type=body["model_type"],
                data_origin=dataset.data_origin, operational_use="FORBIDDEN" if dataset.data_origin == "SYNTHETIC_TEST_ONLY" else "ALLOWED",
                base_preprocessing_profile_id=body.get("base_preprocessing_profile_id", "base-v1"),
                representation_profile_id=body["representation_profile_id"], hyperparameters=body.get("hyperparameters", {}),
                random_seed=body.get("random_seed", 42),
            )
            return job_manager.start_training_job(training_run=training_run)
        return call(fn)

    @router.get("/training-runs")
    def training_runs():
        return call(repository.list_training_runs)

    @router.get("/training-runs/{training_run_id}")
    def get_training_run(training_run_id: str):
        def fn():
            run = repository.get_training_run(training_run_id)
            if run is None:
                raise FileNotFoundError("TRAINING_RUN_NOT_FOUND")
            return run
        return call(fn)

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    @router.post("/training-runs/{training_run_id}/evaluation")
    def evaluate(training_run_id: str, body: dict | None = None):
        min_precision = (body or {}).get("min_identified_precision", 0.9)
        # Advanced mode's manual per-stage button: TEST is only included when
        # the operator explicitly asks for it (e.g. the single model already
        # chosen), never by default -- comparing several candidates this way
        # must stay VALIDATION-only, same as the automatic orchestration.
        include_test = bool((body or {}).get("include_test", False))
        return call(lambda: repository.evaluate_training_run(training_run_id, min_identified_precision=min_precision, include_test=include_test))

    @router.get("/training-runs/{training_run_id}/evaluation")
    def get_evaluation(training_run_id: str):
        def fn():
            evaluation = repository.get_evaluation(training_run_id)
            if evaluation is None:
                raise FileNotFoundError("EVALUATION_NOT_RUN_YET")
            return evaluation
        return call(fn)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    @router.post("/training-runs/{training_run_id}/export", status_code=201)
    def export_bundle(training_run_id: str, body: dict):
        def fn():
            manifest, reasons = repository.export_bundle(
                training_run_id=training_run_id, bundle_id=body["bundle_id"], acceptance_criteria=body.get("acceptance_criteria", {}),
                model_card_text=body.get("model_card_text", f"# Model bundle {body['bundle_id']}\n"),
            )
            return {"bundle": dump(manifest), "gate_reasons": reasons}
        return call(fn)

    @router.get("/bundles")
    def bundles():
        return call(lambda: dump_list(repository.list_bundles()))

    @router.get("/bundles/{bundle_id}")
    def get_bundle(bundle_id: str):
        def fn():
            bundle = repository.get_bundle(bundle_id)
            if bundle is None:
                raise FileNotFoundError("BUNDLE_NOT_FOUND")
            return dump(bundle)
        return call(fn)

    @router.post("/bundles/{bundle_id}/approve")
    def approve_bundle(bundle_id: str):
        return call(lambda: dump(repository.approve_bundle(bundle_id)))

    # ------------------------------------------------------------------
    # Offline inference
    # ------------------------------------------------------------------

    @router.post("/bundles/{bundle_id}/inference")
    def run_inference(bundle_id: str, body: dict):
        return call(lambda: repository.run_inference(bundle_id=bundle_id, capture_id=body["capture_id"]))

    return router
