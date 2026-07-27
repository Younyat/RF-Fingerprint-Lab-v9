"""Ties every Fase 0-5 service together behind persistent storage so stateless
HTTP requests can drive the pipeline. The stage/service classes themselves
stay pure (as already unit-tested) -- this repository owns ONLY the
disk-persistence and cross-stage lookups the API layer needs.
"""
from __future__ import annotations

import dataclasses
import uuid
from pathlib import Path
from typing import Any

import joblib
import torch

from app.infrastructure.ble.capture.ble_offline_replay import read_json, read_jsonl, sha256_file, utc_now, write_json, write_jsonl
from app.infrastructure.ble.packet_analysis.ble_capture_locator import BleCaptureLocator

from ..acquisition.capture_stage import CaptureStage
from ..contracts import (
    CapturePurpose,
    CaptureRecord,
    DatasetManifest,
    DatasetQualityReport,
    DatasetRole,
    ExampleAnnotation,
    ExampleRecord,
    LabelEvidenceItem,
    ModelBundleManifest,
    PhysicalUnitRecord,
    SplitManifest,
    TargetState,
    TrainingRun,
)
from ..evaluation import Evaluator
from ..evidence.evidence_stage import EvidenceStage
from ..export import BundleBuilder
from ..dataset import DatasetBuilder
from ..demo import SyntheticDemoSeeder
from ..inference import OfflineInferenceService
from ..preprocessing import BasePreprocessingProfile
from ..quality import DatasetAnalyzer, SplitBuilder, TASK_DISPLAY_NAMES, explain_feasibility
from ..registry import PhysicalDeviceRegistry
from ..training import TrainingArtifacts, TrainingService, cnn_feasibility, model_file_size_bytes, score_model

# Candidate model types tried by the "prepare dataset and train" auto
# orchestration, in the order the guided UI reports progress for them.
_QUICK_PILOT_MODEL_TYPES = ("logistic_regression", "svm_rbf", "random_forest")
_NORMAL_MODEL_TYPES = ("logistic_regression", "svm_rbf", "random_forest", "cnn1d", "cnn2d")

_TORCH_MODEL_TYPES = {"cnn1d", "cnn2d"}

# Minimum VALIDATION-only bar a candidate must clear to be selectable at all.
# Deliberately conservative (better than a coin flip on macro-averaged
# per-class metrics) rather than tuned to any specific dataset; if no
# candidate clears it, prepare_and_train reports NO_MODEL_ACCEPTED instead of
# recommending the least-bad option. Operational parameter, not a universal
# scientific threshold -- revisit once real campaigns provide more evidence.
ACCEPTANCE_MIN_MACRO_F1 = 0.5
ACCEPTANCE_MIN_BALANCED_ACCURACY = 0.5


class StudioRepository:
    def __init__(self, root: Path, legacy_capture_root: Path, legacy_session_root: Path, campaign_orchestrator: Any | None = None) -> None:
        self.root = root
        self.legacy_capture_root = legacy_capture_root
        self.legacy_session_root = legacy_session_root
        # None when ble_lab's hybrid/capture managers weren't available at
        # startup (e.g. isolated tests) -- real-campaign endpoints raise a
        # clear error rather than silently no-op in that case.
        self.campaign_orchestrator = campaign_orchestrator

        self.registry = PhysicalDeviceRegistry(root / "registry")
        self.capture_stage = CaptureStage(legacy_capture_root)
        self.dataset_builder = DatasetBuilder(root / "datasets")
        self.analyzer = DatasetAnalyzer()
        self.split_builder = SplitBuilder()
        self.evaluator = Evaluator()
        self.bundle_builder = BundleBuilder(root / "bundles")
        self.synthetic_demo_seeder = SyntheticDemoSeeder(self)

        self.captures_dir = root / "captures"
        self.evidence_dir = root / "evidence"
        self.quality_dir = root / "quality_reports"
        self.splits_dir = root / "splits"
        self.training_dir = root / "training_runs"
        for directory in (self.captures_dir, self.evidence_dir, self.quality_dir, self.splits_dir, self.training_dir):
            directory.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Legacy capture listing (read-only, reuses the Phase 2 locator)
    # ------------------------------------------------------------------

    def list_legacy_captures(self) -> dict[str, Any]:
        locator = BleCaptureLocator(self.legacy_capture_root, self.legacy_session_root)
        rows = locator.list_captures()
        classification = locator.classify(rows)
        for row in rows:
            row.pop("_mtime", None)
            device_label, device_source = self._device_label_for_capture(row["capture_id"])
            row["device_label"] = device_label
            row["device_source"] = device_source
            capture_type_label, capture_decision = self._capture_type_and_decision(row["capture_id"])
            row["capture_type_label"] = capture_type_label
            row["capture_decision"] = capture_decision
        return {"captures": rows, "classification": classification}

    def _device_label_for_capture(self, capture_id: str) -> tuple[str, str]:
        """One glance answer to "whose recording is this" for the capture
        picker -- never leave an operator guessing between a real device's
        session and a pure-noise/no-match one from an opaque capture_id."""
        capture = self.get_capture(capture_id)
        if capture and capture.isolation_declared_physical_unit_id:
            return f"{capture.isolation_declared_physical_unit_id} (aislamiento fisico declarado)", "ISOLATION_DECLARED"
        if not self.has_evidence(capture_id):
            return "Sin analizar aun (construye evidencia para identificarla)", "NOT_ANALYZED"
        unit_ids = {example.physical_unit_id for example in self.list_examples(capture_id) if example.physical_unit_id}
        if len(unit_ids) == 1:
            return f"{unit_ids.pop()} (direccion confirmada)", "ADDRESS_MATCH"
        if len(unit_ids) > 1:
            return f"Multiples dispositivos: {', '.join(sorted(unit_ids))}", "MULTIPLE_ADDRESS_MATCHES"
        return "Entorno / ruido ambiental (ningun dispositivo registrado coincidio)", "ENVIRONMENT_NO_MATCH"

    def _capture_type_and_decision(self, capture_id: str) -> tuple[str, str]:
        """Human-facing "Tipo de captura" + eligibility verdict for the
        Guided UI's captures list -- separate from _device_label_for_capture,
        which answers WHICH device, not what the operator meant to capture
        or whether the evidence actually backs that intent up."""
        capture = self.get_capture(capture_id)
        if capture is None:
            return "Sin clasificar", "NOT_ANALYZED_YET"
        if capture.data_origin == "SYNTHETIC_TEST_ONLY":
            return "Sintetica de pruebas", self._capture_decision(capture)
        if capture.capture_purpose == "TARGET_DEVICE":
            return "Dispositivo encendido", self._capture_decision(capture)
        if capture.capture_purpose == "BACKGROUND_ENVIRONMENT":
            label = "Entorno -- dispositivo apagado" if capture.target_reference_id else "Entorno general"
            return label, self._capture_decision(capture)
        return "Sin clasificar", self._capture_decision(capture)

    def _capture_decision(self, capture: CaptureRecord) -> str:
        """ELIGIBLE_AS_POSITIVE / ELIGIBLE_AS_BACKGROUND / QUARANTINED /
        REJECTED / NOT_ANALYZED_YET -- computed fresh from the examples
        Evidence Stage produced, never stored/duplicated on the capture
        itself (examples are the source of truth, and can be rebuilt).

        Evidence Stage never itself promotes an example all the way to
        dataset_eligibility=ELIGIBLE (that's the Fase 2 Dataset
        Builder/Analyzer gate's call, made per-dataset, not per-capture) --
        so "eligible so far" here means the same includable set
        DatasetBuilder.select_examples() itself uses: quality PASSED and
        dataset_eligibility in {PENDING_REVIEW, ELIGIBLE}, i.e. not already
        excluded outright.
        """
        if not self.has_evidence(capture.capture_id):
            return "NOT_ANALYZED_YET"
        examples = self.list_examples(capture.capture_id)
        eligible = [
            example for example in examples
            if example.quality_status == "PASSED" and example.dataset_eligibility in ("PENDING_REVIEW", "ELIGIBLE")
        ]
        quarantined_or_conflict = [
            example for example in examples
            if example.dataset_eligibility == "QUARANTINED" or example.association_status == "CONFLICT"
        ]
        if capture.capture_purpose == "TARGET_DEVICE":
            if any(example.physical_unit_id for example in eligible):
                return "ELIGIBLE_AS_POSITIVE"
            return "QUARANTINED" if quarantined_or_conflict else "REJECTED"
        if capture.capture_purpose == "BACKGROUND_ENVIRONMENT":
            if any(not example.physical_unit_id for example in eligible):
                return "ELIGIBLE_AS_BACKGROUND"
            return "QUARANTINED" if quarantined_or_conflict else "REJECTED"
        # Legacy/unclassified capture (predates capture_purpose) -- best
        # generic verdict from the evidence alone, never a fabricated intent.
        if any(example.physical_unit_id for example in eligible):
            return "ELIGIBLE_AS_POSITIVE"
        if any(not example.physical_unit_id for example in eligible):
            return "ELIGIBLE_AS_BACKGROUND"
        return "QUARANTINED" if quarantined_or_conflict else "REJECTED"

    # ------------------------------------------------------------------
    # Physical Device Registry
    # ------------------------------------------------------------------

    def register_physical_unit(self, *, physical_unit_id: str, project_id: str, device_family: str, operator_declaration_id: str, manufacturer: str | None = None, model: str | None = None) -> PhysicalUnitRecord:
        return self.registry.register_physical_unit(
            physical_unit_id=physical_unit_id, project_id=project_id, device_family=device_family,
            manufacturer=manufacturer, model=model, operator_declaration_id=operator_declaration_id, first_registered_at=utc_now(),
        )

    def list_physical_units(self) -> list[PhysicalUnitRecord]:
        return self.registry.list_physical_units()

    def declare_binding(self, *, project_id: str, address: str, address_type: str, physical_unit_id: str, reason: str, decision_artifact_id: str):
        evidence = LabelEvidenceItem(source_type="OPERATOR_DECLARATION", artifact_id=decision_artifact_id, timestamp=utc_now(), strength="DOCUMENTARY", description=reason)
        return self.registry.declare_binding(project_id=project_id, address=address, address_type=address_type, physical_unit_id=physical_unit_id, evidence=evidence, decided_at=utc_now(), reason=reason)

    def list_bindings(self) -> list[Any]:
        return self.registry.list_bindings()

    # ------------------------------------------------------------------
    # Synthetic demo (no SDR hardware required)
    # ------------------------------------------------------------------

    def seed_synthetic_demo(self) -> dict[str, Any]:
        return self.synthetic_demo_seeder.seed()

    # ------------------------------------------------------------------
    # Capture Stage
    # ------------------------------------------------------------------

    def build_capture(
        self, *, capture_id: str, project_id: str, campaign_id: str, execution_id: str | None = None,
        session_id: str | None = None, isolation_declared_physical_unit_id: str | None = None,
        capture_purpose: CapturePurpose | None = None, target_state: TargetState | None = None,
        target_reference_id: str | None = None, dataset_role: DatasetRole | None = None,
    ) -> CaptureRecord:
        capture = self.capture_stage.build_capture_record(
            capture_id=capture_id, project_id=project_id, campaign_id=campaign_id, execution_id=execution_id,
            session_id=session_id, isolation_declared_physical_unit_id=isolation_declared_physical_unit_id,
            capture_purpose=capture_purpose, target_state=target_state,
            target_reference_id=target_reference_id, dataset_role=dataset_role,
        )
        write_json(self.captures_dir / f"{capture_id}.json", capture.model_dump(mode="json"))
        return capture

    def list_captures(self) -> list[CaptureRecord]:
        return [CaptureRecord.model_validate(read_json(p)) for p in sorted(self.captures_dir.glob("*.json"))]

    def get_capture(self, capture_id: str) -> CaptureRecord | None:
        path = self.captures_dir / f"{capture_id}.json"
        return CaptureRecord.model_validate(read_json(path)) if path.is_file() else None

    def resolve_iq_path(self, capture: CaptureRecord) -> Path:
        return self.legacy_capture_root / capture.capture_id / capture.iq_path

    # ------------------------------------------------------------------
    # Real capture campaign (B200 + native scan, wrapping the existing
    # BleHybridCampaignManager mechanism -- see campaign_orchestrator.py)
    # ------------------------------------------------------------------

    def run_campaign_session(self, *, progress=None, **kwargs: Any) -> dict[str, Any]:
        if self.campaign_orchestrator is None:
            raise RuntimeError(
                "REAL_CAMPAIGN_NOT_AVAILABLE: ble_lab's capture/hybrid managers were not available when this "
                "module started (BLE_IQ_CAPTURE_EXPERIMENTAL_ENABLED or hardware probing may be disabled)."
            )
        return self.campaign_orchestrator.run_session(progress=progress, **kwargs)

    def campaign_device_status(self) -> dict[str, Any]:
        if self.campaign_orchestrator is None:
            raise RuntimeError("REAL_CAMPAIGN_NOT_AVAILABLE")
        device_id = self.campaign_orchestrator.resolve_device_id(None)
        return {"device_id": device_id, **self.campaign_orchestrator.arbiter.get_status(device_id)}

    # ------------------------------------------------------------------
    # Evidence Stage
    # ------------------------------------------------------------------

    def build_evidence(self, *, capture: CaptureRecord, project_id: str, ble_channel: int, replay_run_id: str | None = None, progress=None) -> dict[str, Any]:
        stage = EvidenceStage(self.legacy_capture_root, self.legacy_session_root, self.root / "packet_analysis_cache", self.registry)
        if progress:
            progress("BUILD_EXAMPLES", 0.0, "Construyendo ExampleRecord + ExampleAnnotation desde el replay validado")
        pairs = stage.build_examples(capture=capture, project_id=project_id, ble_channel=ble_channel, replay_run_id=replay_run_id)
        capture_evidence_dir = self.evidence_dir / capture.capture_id
        capture_evidence_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(capture_evidence_dir / "examples.jsonl", [example.model_dump(mode="json") for example, _ in pairs])
        write_jsonl(capture_evidence_dir / "annotations.jsonl", [annotation.model_dump(mode="json") for _, annotation in pairs])
        if progress:
            progress("BUILD_EXAMPLES", 1.0, f"{len(pairs)} ejemplos construidos")
        counts: dict[str, int] = {}
        for example, _ in pairs:
            counts[example.association_status] = counts.get(example.association_status, 0) + 1
        return {"capture_id": capture.capture_id, "n_examples": len(pairs), "association_status_counts": counts}

    def list_examples(self, capture_id: str) -> list[ExampleRecord]:
        path = self.evidence_dir / capture_id / "examples.jsonl"
        return [ExampleRecord.model_validate(row) for row in read_jsonl(path)]

    def list_annotations(self, capture_id: str) -> list[ExampleAnnotation]:
        path = self.evidence_dir / capture_id / "annotations.jsonl"
        return [ExampleAnnotation.model_validate(row) for row in read_jsonl(path)]

    def has_evidence(self, capture_id: str) -> bool:
        return (self.evidence_dir / capture_id / "examples.jsonl").is_file()

    # ------------------------------------------------------------------
    # Dataset Builder
    # ------------------------------------------------------------------

    def build_dataset(self, *, dataset_id: str, dataset_version: str, project_id: str, campaign_id: str, capture_ids: list[str], derived_from: str | None = None) -> dict[str, Any]:
        data_origin = self._require_homogeneous_data_origin(capture_ids)
        all_examples: list[ExampleRecord] = []
        for capture_id in capture_ids:
            all_examples.extend(self.list_examples(capture_id))
        selected, excluded = self.dataset_builder.select_examples(all_examples)
        draft = self.dataset_builder.build_draft(
            dataset_id=dataset_id, dataset_version=dataset_version, project_id=project_id, campaign_id=campaign_id,
            examples=selected, data_origin=data_origin, creation_policy={"source_captures": capture_ids}, created_at=utc_now(), derived_from=derived_from,
        )
        frozen = self.dataset_builder.freeze(draft)
        return {"dataset": frozen, "n_selected": len(selected), "n_excluded": len(excluded), "excluded_reasons": excluded}

    def _require_homogeneous_data_origin(self, capture_ids: list[str]) -> str:
        origins = set()
        for capture_id in capture_ids:
            capture = self.get_capture(capture_id)
            if capture is None:
                raise FileNotFoundError(f"CAPTURE_NOT_BUILT_YET:{capture_id}")
            origins.add(capture.data_origin)
        if len(origins) > 1:
            raise ValueError(f"CANNOT_MIX_DATA_ORIGINS_IN_ONE_DATASET:{sorted(origins)}. A dataset must be entirely REAL_B200 or entirely SYNTHETIC_TEST_ONLY, never a mix.")
        if not origins:
            raise ValueError("NO_CAPTURES_SUPPLIED")
        return origins.pop()

    def list_datasets(self) -> list[DatasetManifest]:
        return [DatasetManifest.model_validate(read_json(p)) for p in sorted(self.dataset_builder.root.glob("*.json"))]

    def get_dataset(self, dataset_id: str, dataset_version: str) -> DatasetManifest | None:
        return self.dataset_builder.load(dataset_id, dataset_version)

    def _dataset_examples(self, dataset: DatasetManifest) -> list[ExampleRecord]:
        by_id: dict[str, ExampleRecord] = {}
        for capture_id in dataset.captures:
            for example in self.list_examples(capture_id):
                by_id[example.example_id] = example
        return [by_id[eid] for eid in dataset.example_ids if eid in by_id]

    def capture_iq_paths_for(self, capture_ids: list[str]) -> dict[str, Path]:
        paths: dict[str, Path] = {}
        for capture_id in capture_ids:
            capture = self.get_capture(capture_id)
            if capture is not None:
                paths[capture_id] = self.resolve_iq_path(capture)
        return paths

    # ------------------------------------------------------------------
    # Dataset Analyzer (quality gate)
    # ------------------------------------------------------------------

    def build_quality_report(self, *, dataset_id: str, dataset_version: str, run_near_duplicates: bool = False) -> DatasetQualityReport:
        dataset = self._require_dataset(dataset_id, dataset_version)
        examples = self._dataset_examples(dataset)
        exact = self.analyzer.check_exact_duplicates(examples)
        overlap = self.analyzer.check_sample_overlap(examples)
        if run_near_duplicates:
            iq_paths = self.capture_iq_paths_for(dataset.captures)
            near = self.analyzer.check_near_duplicates(examples, capture_iq_paths=iq_paths)
        else:
            near = self.analyzer.check_near_duplicates(examples)
        report = self.analyzer.build_gate(dataset, exact, overlap, near, created_at=utc_now())
        write_json(self.quality_dir / f"{dataset_id}__{dataset_version}.json", report.model_dump(mode="json"))
        return report

    def get_quality_report(self, dataset_id: str, dataset_version: str) -> DatasetQualityReport | None:
        path = self.quality_dir / f"{dataset_id}__{dataset_version}.json"
        return DatasetQualityReport.model_validate(read_json(path)) if path.is_file() else None

    # ------------------------------------------------------------------
    # Split Builder
    # ------------------------------------------------------------------

    def build_split(self, *, dataset_id: str, dataset_version: str, scientific_task: str) -> SplitManifest:
        dataset = self._require_dataset(dataset_id, dataset_version)
        examples = self._dataset_examples(dataset)
        split = self.split_builder.build(dataset=dataset, examples=examples, scientific_task=scientific_task, created_at=utc_now())
        write_json(self._split_path(dataset_id, dataset_version, scientific_task), split.model_dump(mode="json"))
        return split

    def get_split(self, dataset_id: str, dataset_version: str, scientific_task: str) -> SplitManifest | None:
        path = self._split_path(dataset_id, dataset_version, scientific_task)
        return SplitManifest.model_validate(read_json(path)) if path.is_file() else None

    def _split_path(self, dataset_id: str, dataset_version: str, scientific_task: str) -> Path:
        return self.splits_dir / f"{dataset_id}__{dataset_version}__{scientific_task}.json"

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def run_training(self, *, training_run: TrainingRun, progress=None) -> TrainingRun:
        dataset = self._require_dataset(training_run.dataset_id, training_run.dataset_version)
        if training_run.data_origin != dataset.data_origin:
            raise ValueError(
                f"TRAINING_RUN_DATA_ORIGIN_MISMATCH:declared={training_run.data_origin}:dataset={dataset.data_origin}. "
                "A TrainingRun's data_origin must always match the dataset it trains on -- never declared independently."
            )

        run_dir = self.training_dir / training_run.training_run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        write_json(run_dir / "training_run.json", training_run.model_dump(mode="json"))

        split = self.get_split(training_run.dataset_id, training_run.dataset_version, training_run.scientific_task)
        if split is None:
            raise FileNotFoundError(f"SPLIT_NOT_BUILT_YET:{training_run.dataset_id}:{training_run.dataset_version}:{training_run.scientific_task}")
        examples_by_id = {e.example_id: e for e in self._dataset_examples(dataset)}
        iq_paths = self.capture_iq_paths_for(dataset.captures)

        if progress:
            progress("TRAIN", 0.1, f"Entrenando {training_run.model_type}")
        service = TrainingService(iq_paths, BasePreprocessingProfile(profile_id=training_run.base_preprocessing_profile_id))
        try:
            if training_run.model_type in _TORCH_MODEL_TYPES:
                artifacts = service.run_cnn(training_run=training_run, split=split, examples_by_id=examples_by_id)
            else:
                artifacts = service.run_baseline(training_run=training_run, split=split, examples_by_id=examples_by_id)
        except Exception as error:
            failed = training_run.model_copy(update={"status": "FAILED"})
            write_json(run_dir / "training_run.json", failed.model_dump(mode="json"))
            write_json(run_dir / "error.json", {"error": f"{type(error).__name__}: {error}"})
            raise

        if progress:
            progress("TRAIN", 0.9, "Persistiendo artefactos del modelo")
        self._persist_training_artifacts(run_dir, artifacts)
        if progress:
            progress("TRAIN", 1.0, "Entrenamiento completado")
        return artifacts.training_run

    def _persist_training_artifacts(self, run_dir: Path, artifacts: TrainingArtifacts) -> None:
        write_json(run_dir / "training_run.json", artifacts.training_run.model_dump(mode="json"))
        if artifacts.training_run.model_type in _TORCH_MODEL_TYPES:
            torch.save(artifacts.model, run_dir / "model.pt")
        else:
            joblib.dump(artifacts.model, run_dir / "model.joblib")
        if artifacts.scaler is not None:
            joblib.dump(artifacts.scaler, run_dir / "scaler.joblib")
        write_json(run_dir / "label_classes.json", {"classes": artifacts.label_classes})
        write_json(run_dir / "feature_names.json", {"names": artifacts.feature_names})
        write_json(run_dir / "metrics.json", artifacts.metrics)
        write_json(run_dir / "predictions.json", artifacts.predictions)
        write_json(run_dir / "latency.json", {"validation_latency_ms": artifacts.validation_latency_ms})

    def list_training_runs(self) -> list[dict[str, Any]]:
        runs = []
        for path in sorted(self.training_dir.glob("*/training_run.json")):
            run = read_json(path)
            metrics_path = path.parent / "metrics.json"
            runs.append({**run, "metrics": read_json(metrics_path) if metrics_path.is_file() else None})
        return runs

    def get_training_run(self, training_run_id: str) -> dict[str, Any] | None:
        run_dir = self.training_dir / training_run_id
        path = run_dir / "training_run.json"
        if not path.is_file():
            return None
        run = read_json(path)
        metrics_path = run_dir / "metrics.json"
        label_classes_path = run_dir / "label_classes.json"
        error_path = run_dir / "error.json"
        return {
            **run,
            "metrics": read_json(metrics_path) if metrics_path.is_file() else None,
            "label_classes": read_json(label_classes_path)["classes"] if label_classes_path.is_file() else None,
            "error": read_json(error_path) if error_path.is_file() else None,
        }

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate_training_run(self, training_run_id: str, min_identified_precision: float = 0.9, include_test: bool = False) -> dict[str, Any]:
        """Model-selection comparisons must never touch TEST (see
        prepare_and_train): include_test defaults to False so evaluating N
        candidates during selection reports TRAIN/VALIDATION only. TEST is
        evaluated by passing include_test=True, and that must happen exactly
        once, for the single model already chosen via VALIDATION.
        """
        run_dir = self.training_dir / training_run_id
        predictions_path = run_dir / "predictions.json"
        label_classes_path = run_dir / "label_classes.json"
        if not predictions_path.is_file():
            raise FileNotFoundError(f"TRAINING_RUN_HAS_NO_PREDICTIONS_YET:{training_run_id}")
        predictions = read_json(predictions_path)
        label_classes = read_json(label_classes_path)["classes"]

        splits_to_evaluate = predictions if include_test else {name: preds for name, preds in predictions.items() if name != "TEST"}
        reports = {name: self.evaluator.evaluate_split(name, preds, label_classes) for name, preds in splits_to_evaluate.items()}
        threshold = None
        if "VALIDATION" in predictions:
            threshold = self.evaluator.calibrate_unknown_threshold(predictions["VALIDATION"], label_classes, min_identified_precision=min_identified_precision)
        calibration = {"acceptance_threshold": threshold, "calibrated_on": "VALIDATION", "min_identified_precision": min_identified_precision}

        report_dict = {name: dataclasses.asdict(report) for name, report in reports.items()}
        write_json(run_dir / "evaluation_report.json", report_dict)
        write_json(run_dir / "calibration.json", calibration)
        return {"evaluation_report": report_dict, "calibration": calibration}

    def get_evaluation(self, training_run_id: str) -> dict[str, Any] | None:
        run_dir = self.training_dir / training_run_id
        eval_path = run_dir / "evaluation_report.json"
        calibration_path = run_dir / "calibration.json"
        if not eval_path.is_file():
            return None
        return {"evaluation_report": read_json(eval_path), "calibration": read_json(calibration_path) if calibration_path.is_file() else None}

    # ------------------------------------------------------------------
    # Guided orchestration: "Prepare dataset and train"
    #
    # Chains evidence -> dataset -> quality gate -> split -> every feasible
    # candidate model -> evaluation -> comparison, stopping cleanly (with a
    # human explanation) the moment a real gate fails, instead of pushing an
    # operator through nine manual button presses. Nothing here bypasses any
    # gate; it only calls the same stage methods above in sequence.
    # ------------------------------------------------------------------

    PHASE_LABELS = [
        "Analizando capturas",
        "Construyendo ejemplos de evidencia",
        "Revisando el dataset",
        "Creando particiones",
        "Entrenando modelos candidatos",
        "Validando modelos",
        "Calibrando deteccion de desconocidos",
        "Comparando modelos",
        "Preparando resumen para exportacion",
    ]

    def prepare_and_train(
        self,
        *,
        capture_ids: list[str],
        project_id: str,
        campaign_id: str,
        scientific_task: str,
        ble_channel: int = 37,
        dataset_id: str | None = None,
        dataset_version: str = "1.0.0",
        speed_profile: str = "normal",
        progress=None,
    ) -> dict[str, Any]:
        total = len(self.PHASE_LABELS)

        def report(index: int, detail: str = "") -> None:
            if progress:
                message = f"{index}/{total} {self.PHASE_LABELS[index - 1]}" + (f": {detail}" if detail else "")
                progress(f"PHASE_{index}", (index - 1) / total, message)

        dataset_id = dataset_id or f"{project_id}-AUTO-DS"

        report(1, f"{len(capture_ids)} captura(s)")
        captures = []
        for capture_id in capture_ids:
            capture = self.get_capture(capture_id)
            if capture is None:
                raise FileNotFoundError(f"CAPTURE_NOT_BUILT_YET:{capture_id}")
            captures.append(capture)

        report(2)
        for capture in captures:
            if not self.has_evidence(capture.capture_id):
                self.build_evidence(capture=capture, project_id=project_id, ble_channel=ble_channel)

        report(3)
        build_result = self.build_dataset(dataset_id=dataset_id, dataset_version=dataset_version, project_id=project_id, campaign_id=campaign_id, capture_ids=capture_ids)
        dataset = build_result["dataset"]
        quality = self.build_quality_report(dataset_id=dataset_id, dataset_version=dataset_version)
        if quality.gate_decision == "NOT_ACCEPTED_FOR_TRAINING":
            return {
                "stopped_at": "quality_gate",
                "stopped_reason": "El dataset no supero el control de calidad: " + "; ".join(quality.gate_reasons),
                "dataset": dataset, "quality_report": quality, "split": None, "feasibility": None,
                "trained_models": [], "skipped_models": [], "recommended_training_run_id": None, "recommended_reason": None,
            }

        report(4)
        examples = self._dataset_examples(dataset)
        feasibility = explain_feasibility(examples, scientific_task)
        split = self.build_split(dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=scientific_task)
        if split.split_status != "READY":
            return {
                "stopped_at": "split", "stopped_reason": feasibility["human_summary"],
                "dataset": dataset, "quality_report": quality, "split": split, "feasibility": feasibility,
                "trained_models": [], "skipped_models": [], "recommended_training_run_id": None, "recommended_reason": None,
            }

        candidate_types = list(_QUICK_PILOT_MODEL_TYPES if speed_profile == "quick_pilot" else _NORMAL_MODEL_TYPES)
        cnn_ok, cnn_reason = cnn_feasibility([a.model_dump(mode="json") for a in split.assignments])
        skipped_models: list[dict[str, str]] = []
        if not cnn_ok:
            for cnn_type in ("cnn1d", "cnn2d"):
                if cnn_type in candidate_types:
                    candidate_types.remove(cnn_type)
                    skipped_models.append({"model_type": cnn_type, "reason": cnn_reason})

        representation_by_model = {
            "logistic_regression": "feature_vector-v1", "svm_rbf": "feature_vector-v1", "random_forest": "feature_vector-v1",
            "cnn1d": "raw_iq-v1", "cnn2d": "spectrogram-v1",
        }

        report(5, f"{len(candidate_types)} candidato(s): {', '.join(candidate_types)}")
        trained_run_ids = []
        for model_type in candidate_types:
            training_run_id = f"AUTO-{model_type}-{uuid.uuid4().hex[:10]}"
            training_run = TrainingRun(
                training_run_id=training_run_id, project_id=project_id, campaign_id=campaign_id,
                dataset_id=dataset_id, dataset_version=dataset_version, dataset_manifest_sha256=dataset.dataset_manifest_sha256 or "",
                split_manifest_sha256=split.split_manifest_sha256 or "", scientific_task=scientific_task, model_type=model_type,
                data_origin=dataset.data_origin, operational_use="FORBIDDEN" if dataset.data_origin == "SYNTHETIC_TEST_ONLY" else "ALLOWED",
                base_preprocessing_profile_id="base-v1", representation_profile_id=representation_by_model[model_type], random_seed=42,
            )
            try:
                completed = self.run_training(training_run=training_run)
                trained_run_ids.append(completed.training_run_id)
            except Exception as error:
                skipped_models.append({"model_type": model_type, "reason": f"{type(error).__name__}: {error}"})

        report(6, f"{len(trained_run_ids)} modelo(s) entrenado(s)")
        report(7)
        # VALIDATION only -- include_test=False means TEST is not even read
        # here, let alone used to score or compare candidates.
        scored = []
        for training_run_id in trained_run_ids:
            evaluation = self.evaluate_training_run(training_run_id, min_identified_precision=0.9, include_test=False)
            run_dir = self.training_dir / training_run_id
            latency_path = run_dir / "latency.json"
            latency_ms = read_json(latency_path).get("validation_latency_ms") if latency_path.is_file() else None
            run_info = read_json(run_dir / "training_run.json")
            size_bytes = model_file_size_bytes(run_dir, run_info["model_type"])
            score = score_model(evaluation["evaluation_report"], evaluation["calibration"], latency_ms or 0.0, size_bytes)
            scored.append({"training_run_id": training_run_id, "model_type": run_info["model_type"], "evaluation": evaluation, "score": score})

        report(8)
        accepted = [s for s in scored if self._meets_acceptance_criteria(s["score"])]
        if not accepted:
            report(9)
            return {
                "stopped_at": "model_selection",
                "stopped_reason": (
                    "NO_MODEL_ACCEPTED: ninguno de los "
                    f"{len(scored)} modelo(s) candidato(s) alcanzo el criterio minimo de aceptacion en VALIDATION "
                    f"(macro_f1 >= {ACCEPTANCE_MIN_MACRO_F1}, balanced_accuracy >= {ACCEPTANCE_MIN_BALANCED_ACCURACY}). "
                    "No se exporta automaticamente el modelo menos malo."
                ) if scored else "Ningun modelo completo el entrenamiento.",
                "dataset": dataset, "quality_report": quality, "split": split, "feasibility": feasibility,
                "trained_models": scored, "skipped_models": skipped_models,
                "recommended_training_run_id": None, "recommended_reason": None, "final_test_evaluation": None,
            }

        # Selection is frozen the moment we pick `recommended`: model type,
        # hyperparameters, preprocessing and (via its calibration.json)
        # UNKNOWN threshold are all already on disk for this training_run_id.
        # TEST is evaluated exactly once, only now, only for this one model.
        recommended = max(accepted, key=lambda s: s["score"]["composite_score"])
        final_evaluation = self.evaluate_training_run(recommended["training_run_id"], min_identified_precision=0.9, include_test=True)
        recommended["evaluation"] = final_evaluation

        report(9)
        return {
            "stopped_at": None, "dataset": dataset, "quality_report": quality, "split": split, "feasibility": feasibility,
            "trained_models": scored, "skipped_models": skipped_models,
            "recommended_training_run_id": recommended["training_run_id"],
            "recommended_reason": self._recommendation_reason(recommended, scored),
            "final_test_evaluation": final_evaluation["evaluation_report"].get("TEST"),
        }

    def _meets_acceptance_criteria(self, score: dict[str, Any]) -> bool:
        return score["macro_f1"] >= ACCEPTANCE_MIN_MACRO_F1 and score["balanced_accuracy_proxy"] >= ACCEPTANCE_MIN_BALANCED_ACCURACY

    def _recommendation_reason(self, recommended: dict[str, Any], scored: list[dict[str, Any]]) -> str:
        others = [s for s in scored if s is not recommended]
        parts = [f"mejor puntuacion compuesta en VALIDATION ({recommended['score']['composite_score']:.3f})"]
        if others and all(recommended["score"]["unknown_capability_penalty"] <= o["score"]["unknown_capability_penalty"] for o in others):
            parts.append("mejor o igual capacidad de deteccion de desconocidos")
        parts.append(f"latencia {recommended['score']['latency_ms']:.2f} ms por ejemplo")
        return "; ".join(parts)

    def scientific_task_display_names(self) -> dict[str, str]:
        return dict(TASK_DISPLAY_NAMES)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_bundle(self, *, training_run_id: str, bundle_id: str, acceptance_criteria: dict[str, Any], model_card_text: str) -> tuple[ModelBundleManifest, list[str]]:
        run_dir = self.training_dir / training_run_id
        run_path = run_dir / "training_run.json"
        if not run_path.is_file():
            raise FileNotFoundError(f"TRAINING_RUN_NOT_FOUND:{training_run_id}")
        evaluation = self.get_evaluation(training_run_id)
        if evaluation is None:
            raise FileNotFoundError(f"TRAINING_RUN_NOT_EVALUATED_YET:{training_run_id}")

        training_run = TrainingRun.model_validate(read_json(run_path))
        dataset = self._require_dataset(training_run.dataset_id, training_run.dataset_version)
        split = self.get_split(training_run.dataset_id, training_run.dataset_version, training_run.scientific_task)
        if split is None:
            raise FileNotFoundError("SPLIT_NOT_FOUND_FOR_THIS_TRAINING_RUN")

        model = torch.load(run_dir / "model.pt", weights_only=False) if training_run.model_type in _TORCH_MODEL_TYPES else joblib.load(run_dir / "model.joblib")
        scaler_path = run_dir / "scaler.joblib"
        scaler = joblib.load(scaler_path) if scaler_path.is_file() else None
        label_classes = read_json(run_dir / "label_classes.json")["classes"]
        feature_names = read_json(run_dir / "feature_names.json")["names"]

        from ..evaluation import SplitEvaluationReport
        evaluation_reports = {name: SplitEvaluationReport(**data) for name, data in evaluation["evaluation_report"].items()}

        manifest, reasons = self.bundle_builder.build(
            bundle_id=bundle_id, training_run=training_run, model=model, label_classes=label_classes,
            feature_names=feature_names, scaler=scaler, dataset=dataset, split=split,
            evaluation_reports=evaluation_reports, calibration=evaluation["calibration"], acceptance_criteria=acceptance_criteria,
            model_card_text=model_card_text, code_reference={"module": "app.modules.ble_rffi_studio", "training_run_id": training_run_id},
            created_at=utc_now(),
        )
        return manifest, reasons

    def list_bundles(self) -> list[ModelBundleManifest]:
        return [ModelBundleManifest.model_validate(read_json(p)) for p in sorted(self.bundle_builder.root.glob("*/bundle_manifest.json"))]

    def get_bundle(self, bundle_id: str) -> ModelBundleManifest | None:
        return self.bundle_builder.load_manifest(bundle_id)

    def approve_bundle(self, bundle_id: str) -> ModelBundleManifest:
        manifest = self.bundle_builder.load_manifest(bundle_id)
        if manifest is None:
            raise FileNotFoundError(f"BUNDLE_NOT_FOUND:{bundle_id}")
        return self.bundle_builder.approve_for_live_pilot(manifest)

    # ------------------------------------------------------------------
    # Offline inference
    # ------------------------------------------------------------------

    def run_inference(self, *, bundle_id: str, capture_id: str) -> list[dict[str, Any]]:
        examples = self.list_examples(capture_id)
        if not examples:
            raise FileNotFoundError(f"NO_EVIDENCE_BUILT_YET_FOR_CAPTURE:{capture_id}")
        iq_paths = self.capture_iq_paths_for([capture_id])
        service = OfflineInferenceService(self.bundle_builder.root, iq_paths)
        return service.run(bundle_id=bundle_id, examples=examples)

    # ------------------------------------------------------------------

    def _require_dataset(self, dataset_id: str, dataset_version: str) -> DatasetManifest:
        dataset = self.get_dataset(dataset_id, dataset_version)
        if dataset is None:
            raise FileNotFoundError(f"DATASET_NOT_FOUND:{dataset_id}:{dataset_version}")
        return dataset
