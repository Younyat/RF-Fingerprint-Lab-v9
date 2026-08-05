"""Fase 1: frozen protocol, holdout access log, scientific preflight.

Strictly read-only over ble_rffi_studio's storage root. Every method here
either writes under this module's own `storage/scientific_reports/ble/`
root or appends to its own audit log -- nothing under
`storage/ble_rffi_studio/` is ever opened for writing, only for reading
already-frozen manifests (captures, evidence, datasets, splits, quality
reports) that ble_rffi_studio itself produced and owns.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.infrastructure.ble.capture.ble_capture_metadata import atomic_json
from app.modules.ble_rffi_studio.contracts import CaptureRecord, DatasetManifest, DatasetQualityReport, ExampleRecord, SplitManifest

from ..contracts import (
    AnalysisContract,
    DesignCompletenessResult,
    GitDirtyState,
    HoldoutAccessLogEntry,
    HoldoutChainVerificationResult,
    InputArtifactIndex,
    InputSnapshotEntry,
    IntegrityCheckResult,
    LeakageCheckResult,
    PaperCampaignCompletenessResult,
    PaperRunRecord,
    PopulationSeparationResult,
    QualityCheckResult,
    RecordBuildResult,
    ScientificPreflightReport,
)
from ..campaign import build_campaign_accounting as _build_campaign_accounting
from ..figures import build_campaign_figures as _build_campaign_figures
from ..module_logging import build_module_logger
from ..quality import build_quality_summary as _build_quality_summary
from ..records import build_records as _build_records
from ..records import resolve_iq_path

RUN_SUBDIRS = [
    "00_contract", "01_inputs", "02_integrity", "03_campaign_accounting", "04_quality",
    "05_predictions", "06_statistics", "07_figures", "08_tables", "09_latex",
    "10_forensic_reporting", "11_reproducibility", "12_logs",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ScientificResultsRepository:
    def __init__(self, root: Path, ble_rffi_studio_root: Path, *, legacy_capture_root: Path | None = None) -> None:
        self.root = root
        self.ble_root = ble_rffi_studio_root
        # Same resolution rule as StudioRepository.resolve_iq_path():
        # CaptureRecord.iq_path is a bare filename (e.g.
        # "BLE-IQ-...sigmf-data"), not an absolute path -- the real
        # directory is legacy_capture_root/<capture_id>/<iq_path>. Defaults
        # to the same location ble_rffi_studio's own module.py wires up, so
        # a caller that only has the ble_rffi_studio storage root doesn't
        # need to know this detail.
        self.legacy_capture_root = legacy_capture_root or (ble_rffi_studio_root.parent / "ble" / "iq_captures")
        self.root.mkdir(parents=True, exist_ok=True)
        self.logger = build_module_logger(self.root)

    def _resolve_iq_path(self, capture: CaptureRecord) -> Path:
        return resolve_iq_path(self.legacy_capture_root, capture)

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    def _protocol_dir(self, protocol_id: str) -> Path:
        if any(part in protocol_id for part in ("/", "\\", "..")):
            raise ValueError("INVALID_PROTOCOL_ID")
        return self.root / "_protocols" / protocol_id

    def _protocol_path(self, protocol_id: str, version: int) -> Path:
        return self._protocol_dir(protocol_id) / f"{version}.json"

    def _run_dir(self, paper_run_id: str) -> Path:
        if any(part in paper_run_id for part in ("/", "\\", "..")):
            raise ValueError("INVALID_PAPER_RUN_ID")
        return self.root / paper_run_id

    def _holdout_log_path(self) -> Path:
        return self.root / "holdout_access_log.jsonl"

    # ------------------------------------------------------------------
    # Protocol freeze
    # ------------------------------------------------------------------

    def _existing_protocol_versions(self, protocol_id: str) -> list[int]:
        directory = self._protocol_dir(protocol_id)
        if not directory.is_dir():
            return []
        versions = []
        for path in directory.glob("*.json"):
            try:
                versions.append(int(path.stem))
            except ValueError:
                continue
        return versions

    def _git_provenance(self) -> tuple[str, GitDirtyState]:
        cwd = Path(__file__).resolve().parent
        try:
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True, text=True, timeout=10, check=True,
            ).stdout.strip()
            status = subprocess.run(
                ["git", "status", "--porcelain"], cwd=cwd, capture_output=True, text=True, timeout=10, check=True,
            ).stdout
            dirty: GitDirtyState = "DIRTY" if status.strip() else "CLEAN"
            return commit, dirty
        except Exception:
            # Fail closed: an environment where git provenance cannot be
            # determined is never reported as CLEAN.
            return "UNKNOWN", "DIRTY"

    def _software_environment_digest(self) -> str:
        packages = sorted(
            f"{dist.metadata['Name']}=={dist.version}" for dist in importlib.metadata.distributions() if dist.metadata.get("Name")
        )
        payload = "\n".join([f"python=={sys.version}"] + packages)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _policy_hash(self, module_path: Path) -> str:
        return hashlib.sha256(module_path.read_bytes()).hexdigest()

    def freeze_protocol(self, payload: dict[str, Any]) -> AnalysisContract:
        import app.modules.ble_rffi_studio.evidence.evidence_stage as evidence_stage_module
        import app.modules.ble_rffi_studio.quality.dataset_analyzer as dataset_analyzer_module
        import app.modules.ble_rffi_studio.dataset.dataset_builder as dataset_builder_module

        protocol_id = payload.get("protocol_id") or AnalysisContract.make_protocol_id(
            project_id=payload.get("project_id", "BLE-SCIENTIFIC-RESULTS"),
            seed_material=payload.get("protocol_name") or uuid.uuid4().hex,
        )
        existing_versions = self._existing_protocol_versions(protocol_id)
        next_version = (max(existing_versions) + 1) if existing_versions else 1

        git_commit, git_dirty = self._git_provenance()

        required = ["hardware_profile_id", "receiver_profile_hash", "interpretation_matrix_hash"]
        missing = [field for field in required if not payload.get(field)]
        if missing:
            raise ValueError(f"ANALYSIS_CONTRACT_MISSING_REQUIRED_FIELDS:{','.join(missing)}")

        contract = AnalysisContract(
            protocol_id=protocol_id, protocol_version=next_version, creation_timestamp_utc=utc_now(),
            git_commit=git_commit, git_dirty_state=git_dirty, software_environment_digest=self._software_environment_digest(),
            hardware_profile_id=payload["hardware_profile_id"], receiver_profile_hash=payload["receiver_profile_hash"],
            device_population=payload.get("device_population", {}), device_ids=payload.get("device_ids", []),
            firmware_hashes=payload.get("firmware_hashes", {}), channels=payload.get("channels", []),
            campaign_schedule=payload.get("campaign_schedule", {}), intervention_schedule=payload.get("intervention_schedule", {}),
            content_variants=payload.get("content_variants", []),
            association_policy_hash=self._policy_hash(Path(evidence_stage_module.__file__)),
            quality_policy_hash=self._policy_hash(Path(dataset_analyzer_module.__file__)),
            dataset_policy_hash=self._policy_hash(Path(dataset_builder_module.__file__)),
            # Empty unless the caller already commits this protocol to one
            # specific, already-frozen split -- otherwise the protocol fixes
            # the *policy*, and a concrete split is attached per paper_run_id
            # at create_run() time, verified against this field in
            # run_preflight() when it is non-empty.
            split_manifest_hash=payload.get("split_manifest_hash", ""),
            model_branch_definitions=payload.get("model_branch_definitions", []),
            feature_policy=payload.get("feature_policy", {}), signal_region_policy=payload.get("signal_region_policy", {}),
            phase_compensation_policy=payload.get("phase_compensation_policy", {}),
            hyperparameter_search_space=payload.get("hyperparameter_search_space", {}),
            model_selection_rule=payload.get("model_selection_rule", ""), random_seeds=payload.get("random_seeds", []),
            number_of_restarts=payload.get("number_of_restarts", 0),
            threshold_selection_rule=payload.get("threshold_selection_rule", ""), abstention_rule=payload.get("abstention_rule", ""),
            calibration_rule=payload.get("calibration_rule", ""), multiplicity_family=payload.get("multiplicity_family", {}),
            statistical_tests=payload.get("statistical_tests", []), effect_thresholds=payload.get("effect_thresholds", {}),
            non_inferiority_margins=payload.get("non_inferiority_margins", {}),
            minimum_independent_blocks=payload.get("minimum_independent_blocks", {}),
            interpretation_matrix_hash=payload["interpretation_matrix_hash"],
        )
        atomic_json(self._protocol_path(protocol_id, next_version), contract.model_dump(mode="json"))
        self.logger.info("protocol frozen protocol_id=%s version=%s", protocol_id, next_version)
        return contract

    def get_protocol(self, protocol_id: str, version: int | None = None) -> AnalysisContract:
        target_version = version or max(self._existing_protocol_versions(protocol_id), default=None)
        if target_version is None:
            raise FileNotFoundError(f"PROTOCOL_NOT_FOUND:{protocol_id}")
        path = self._protocol_path(protocol_id, target_version)
        if not path.is_file():
            raise FileNotFoundError(f"PROTOCOL_VERSION_NOT_FOUND:{protocol_id}:{target_version}")
        return AnalysisContract.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def list_protocol_versions(self, protocol_id: str) -> list[AnalysisContract]:
        return [self.get_protocol(protocol_id, version) for version in sorted(self._existing_protocol_versions(protocol_id))]

    # ------------------------------------------------------------------
    # Holdout access log -- append-only, hash-chained, project-wide
    # ------------------------------------------------------------------

    def log_holdout_access(
        self, *, actor: str, process: str, access_type: str, access_path: str, resource_id: str,
        resource_hash: str | None, reason: str, paper_run_id: str | None, analysis_contract_hash: str | None,
    ) -> HoldoutAccessLogEntry:
        existing = self.list_holdout_access_log()
        previous_entry_hash = existing[-1].entry_hash if existing else None
        sequence_number = (existing[-1].sequence_number + 1) if existing else 1

        draft = HoldoutAccessLogEntry(
            sequence_number=sequence_number, previous_entry_hash=previous_entry_hash,
            entry_hash="", analysis_contract_hash=analysis_contract_hash, paper_run_id=paper_run_id,
            actor=actor, process=process, access_type=access_type, access_path=access_path,
            resource_id=resource_id, resource_hash=resource_hash, timestamp_utc=utc_now(), reason=reason,
        )
        entry = draft.model_copy(update={"entry_hash": draft.content_hash(exclude={"entry_hash"})})

        path = self._holdout_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry.model_dump(mode="json"), sort_keys=True) + "\n")
        self.logger.info("holdout access logged seq=%s resource_id=%s actor=%s reason=%s", sequence_number, resource_id, actor, reason)
        return entry

    def list_holdout_access_log(self) -> list[HoldoutAccessLogEntry]:
        path = self._holdout_log_path()
        if not path.is_file():
            return []
        entries = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entries.append(HoldoutAccessLogEntry.model_validate(json.loads(line)))
        return entries

    def verify_holdout_access_chain(self) -> HoldoutChainVerificationResult:
        """Recomputes every entry_hash and re-checks every
        previous_entry_hash link against the entry that actually precedes
        it. Detects: deletion (a gap in sequence_number), modification (a
        stored entry_hash that no longer matches its own recomputed hash),
        and reordering/insertion (a previous_entry_hash that does not equal
        the real prior entry's entry_hash). See this module's docstring for
        the exact scope of what this chain does and does not prove."""
        entries = self.list_holdout_access_log()
        if not entries:
            return HoldoutChainVerificationResult(status="EMPTY", entry_count=0)

        findings: list[str] = []
        broken_at: int | None = None
        expected_sequence = 1
        expected_previous_hash: str | None = None
        for entry in entries:
            if entry.sequence_number != expected_sequence:
                findings.append(f"Expected sequence_number={expected_sequence}, found {entry.sequence_number} -- entry deleted, reordered, or inserted.")
                broken_at = broken_at or entry.sequence_number
            if entry.previous_entry_hash != expected_previous_hash:
                findings.append(f"sequence_number={entry.sequence_number}: previous_entry_hash={entry.previous_entry_hash!r} does not match the actual prior entry's hash {expected_previous_hash!r}.")
                broken_at = broken_at or entry.sequence_number
            recomputed = entry.content_hash(exclude={"entry_hash"})
            if entry.entry_hash != recomputed:
                findings.append(f"sequence_number={entry.sequence_number}: stored entry_hash does not match recomputed hash -- entry was modified after being written.")
                broken_at = broken_at or entry.sequence_number
            expected_sequence = entry.sequence_number + 1
            expected_previous_hash = entry.entry_hash

        status = "BROKEN" if findings else "VALID"
        return HoldoutChainVerificationResult(status=status, entry_count=len(entries), broken_at_sequence=broken_at, findings=findings)

    # ------------------------------------------------------------------
    # Paper runs
    # ------------------------------------------------------------------

    def create_run(self, *, protocol_id: str, protocol_version: int | None, campaign_id: str, dataset_id: str, dataset_version: str, scientific_task: str) -> PaperRunRecord:
        contract = self.get_protocol(protocol_id, protocol_version)  # raises if not frozen

        created_at = utc_now()
        paper_run_id = PaperRunRecord.make_paper_run_id(protocol_id=contract.protocol_id, created_at=created_at)
        run_dir = self._run_dir(paper_run_id)
        for subdir in RUN_SUBDIRS:
            (run_dir / subdir).mkdir(parents=True, exist_ok=True)

        # A read-only copy of the exact frozen contract this run is bound
        # to, so the run directory is self-contained and legible without
        # cross-referencing the _protocols/ index.
        atomic_json(run_dir / "00_contract" / "analysis_contract.json", contract.model_dump(mode="json"))

        dataset = self._load_dataset(dataset_id, dataset_version)
        split = self._load_split(dataset_id, dataset_version, scientific_task)
        quality_report = self._load_quality_report(dataset_id, dataset_version)

        git_commit, _ = self._git_provenance()
        run = PaperRunRecord(
            paper_run_id=paper_run_id, campaign_id=campaign_id, protocol_id=contract.protocol_id, protocol_version=contract.protocol_version,
            dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=scientific_task,
            dataset_fingerprint=dataset.dataset_manifest_sha256, split_fingerprint=split.split_manifest_sha256,
            analysis_code_commit=git_commit, analysis_environment_hash=self._software_environment_digest(),
            storage_path=str(run_dir), created_at=created_at,
        )
        atomic_json(run_dir / "run.json", run.model_dump(mode="json"))
        atomic_json(run_dir / "artifact_index.json", {"schema_version": "ble-scientific-results-artifact-index-v1", "paper_run_id": paper_run_id, "artifacts": {}})
        atomic_json(run_dir / "result_summary.json", {"schema_version": "ble-scientific-results-summary-v1", "paper_run_id": paper_run_id})
        self._snapshot_run_inputs(run_dir, paper_run_id=paper_run_id, dataset=dataset, split=split, quality_report=quality_report)
        self.logger.info("run created paper_run_id=%s protocol_id=%s dataset=%s/%s", paper_run_id, protocol_id, dataset_id, dataset_version)
        return run

    def _snapshot_run_inputs(
        self, run_dir: Path, *, paper_run_id: str, dataset: DatasetManifest, split: SplitManifest, quality_report: DatasetQualityReport | None,
    ) -> InputArtifactIndex:
        """Copies every small manifest this run's dataset/split reference
        into 01_inputs/input_snapshot/ (never a symlink, never a bare path
        reference) and references real I/Q by resolved path + size + sha256
        (never copied -- can be gigabytes). See contracts/input_snapshot.py
        for the rationale."""
        snapshot_dir = run_dir / "01_inputs" / "input_snapshot"
        entries: list[InputSnapshotEntry] = []

        def snapshot_json(source_path: Path, relative_dest: str, artifact_type: str, artifact_id: str, version: str | None) -> None:
            if not source_path.is_file():
                return
            payload = source_path.read_bytes()
            dest = snapshot_dir / relative_dest
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(payload)
            entries.append(InputSnapshotEntry(
                source_path=str(source_path), artifact_type=artifact_type, artifact_id=artifact_id, version=version,
                size_bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest(), snapshot_path=str(dest),
            ))

        snapshot_json(
            self.ble_root / "datasets" / f"{dataset.dataset_id}__{dataset.dataset_version}.json",
            "dataset_manifest.json", "dataset_manifest", dataset.dataset_id, dataset.dataset_version,
        )
        snapshot_json(
            self.ble_root / "splits" / f"{split.dataset_id}__{split.dataset_version}__{split.scientific_task}.json",
            "split_manifest.json", "split_manifest", f"{split.dataset_id}__{split.scientific_task}", split.dataset_version,
        )
        if quality_report is not None:
            snapshot_json(
                self.ble_root / "quality_reports" / f"{quality_report.dataset_id}__{quality_report.dataset_version}.json",
                "quality_manifest.json", "quality_manifest", quality_report.dataset_id, quality_report.dataset_version,
            )

        for capture_id in dataset.captures:
            snapshot_json(self.ble_root / "captures" / f"{capture_id}.json", f"captures/{capture_id}.json", "capture_manifest", capture_id, None)
            snapshot_json(self.ble_root / "evidence" / capture_id / "examples.jsonl", f"evidence/{capture_id}/examples.jsonl", "evidence_manifest", capture_id, None)
            snapshot_json(self.ble_root / "evidence" / capture_id / "annotations.jsonl", f"evidence/{capture_id}/annotations.jsonl", "evidence_manifest", capture_id, None)

            capture = self._load_capture(capture_id)
            if capture is not None:
                iq_path = self._resolve_iq_path(capture)
                entries.append(InputSnapshotEntry(
                    source_path=str(iq_path), artifact_type="iq_reference", artifact_id=capture_id, version=None,
                    size_bytes=capture.iq_size_bytes, sha256=capture.iq_sha256, snapshot_path=None,
                ))

        index = InputArtifactIndex(paper_run_id=paper_run_id, generated_at=utc_now(), entries=entries)
        atomic_json(snapshot_dir / "input_artifact_index.json", index.model_dump(mode="json"))
        return index

    def get_run(self, paper_run_id: str) -> PaperRunRecord:
        path = self._run_dir(paper_run_id) / "run.json"
        if not path.is_file():
            raise FileNotFoundError(f"PAPER_RUN_NOT_FOUND:{paper_run_id}")
        return PaperRunRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def list_runs(self) -> list[PaperRunRecord]:
        runs = []
        for path in sorted(self.root.glob("*/run.json")):
            runs.append(PaperRunRecord.model_validate(json.loads(path.read_text(encoding="utf-8"))))
        return runs

    # ------------------------------------------------------------------
    # ble_rffi_studio artifact loaders -- read-only
    # ------------------------------------------------------------------

    def _load_dataset(self, dataset_id: str, dataset_version: str) -> DatasetManifest:
        path = self.ble_root / "datasets" / f"{dataset_id}__{dataset_version}.json"
        if not path.is_file():
            raise FileNotFoundError(f"DATASET_NOT_FOUND:{dataset_id}:{dataset_version}")
        return DatasetManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def _load_split(self, dataset_id: str, dataset_version: str, scientific_task: str) -> SplitManifest:
        path = self.ble_root / "splits" / f"{dataset_id}__{dataset_version}__{scientific_task}.json"
        if not path.is_file():
            raise FileNotFoundError(f"SPLIT_NOT_FOUND:{dataset_id}:{dataset_version}:{scientific_task}")
        return SplitManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def _load_quality_report(self, dataset_id: str, dataset_version: str) -> DatasetQualityReport | None:
        path = self.ble_root / "quality_reports" / f"{dataset_id}__{dataset_version}.json"
        if not path.is_file():
            return None
        return DatasetQualityReport.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def _load_capture(self, capture_id: str) -> CaptureRecord | None:
        path = self.ble_root / "captures" / f"{capture_id}.json"
        if not path.is_file():
            return None
        return CaptureRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def _load_examples(self, capture_id: str) -> list[ExampleRecord]:
        path = self.ble_root / "evidence" / capture_id / "examples.jsonl"
        if not path.is_file():
            return []
        examples = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                examples.append(ExampleRecord.model_validate(json.loads(line)))
        return examples

    # ------------------------------------------------------------------
    # Scientific preflight
    # ------------------------------------------------------------------

    def run_preflight(self, paper_run_id: str, *, progress=None) -> ScientificPreflightReport:
        run = self.get_run(paper_run_id)
        contract = self.get_protocol(run.protocol_id, run.protocol_version)
        dataset = self._load_dataset(run.dataset_id, run.dataset_version)
        split = self._load_split(run.dataset_id, run.dataset_version, run.scientific_task)
        quality_report = self._load_quality_report(run.dataset_id, run.dataset_version)

        if progress:
            progress("integrity", 0.1, "Checking manifest hashes and capture files")
        integrity = self._check_integrity(dataset, split, contract)

        if progress:
            progress("leakage", 0.3, "Checking split leakage status")
        leakage = self._check_leakage(split)

        examples_by_capture = {capture_id: self._load_examples(capture_id) for capture_id in dataset.captures}
        all_examples = [example for examples in examples_by_capture.values() for example in examples]

        if progress:
            progress("population_separation", 0.55, "Separating declared populations")
        population = self._check_population_separation(dataset, all_examples, contract)

        if progress:
            progress("quality", 0.75, "Checking dataset quality gate")
        quality = self._check_quality(quality_report)

        if progress:
            progress("design_completeness", 0.85, "Comparing declared design against observed campaign")
        design = self._check_design_completeness(dataset, all_examples, contract)

        if progress:
            progress("paper_campaign_completeness", 0.95, "Checking whole-paper campaign requirements declared by the protocol")
        campaign_completeness = self._check_paper_campaign_completeness(dataset, all_examples, contract, population)

        structural_categories = [integrity, leakage, population, quality, design]
        overall = ScientificPreflightReport.compute_overall_status(structural_categories, campaign_completeness)
        report = ScientificPreflightReport(
            paper_run_id=paper_run_id, protocol_id=run.protocol_id, protocol_version=run.protocol_version, generated_at=utc_now(),
            integrity=integrity, leakage=leakage, population_separation=population, quality=quality, design_completeness=design,
            paper_campaign_completeness=campaign_completeness, overall_status=overall,
        )
        atomic_json(self._run_dir(paper_run_id) / "02_integrity" / "scientific_preflight_report.json", report.model_dump(mode="json"))
        if progress:
            progress("done", 1.0, overall)
        self.logger.info("preflight paper_run_id=%s overall_status=%s", paper_run_id, overall)
        return report

    def get_preflight_report(self, paper_run_id: str) -> ScientificPreflightReport | None:
        path = self._run_dir(paper_run_id) / "02_integrity" / "scientific_preflight_report.json"
        if not path.is_file():
            return None
        return ScientificPreflightReport.model_validate(json.loads(path.read_text(encoding="utf-8")))

    # ------------------------------------------------------------------
    # Fase 2: canonical records (Section B)
    # ------------------------------------------------------------------

    def _canonical_records_dir(self, paper_run_id: str) -> Path:
        return self._run_dir(paper_run_id) / "01_inputs" / "canonical_records"

    def build_records(self, paper_run_id: str, *, progress=None) -> RecordBuildResult:
        run = self.get_run(paper_run_id)
        contract = self.get_protocol(run.protocol_id, run.protocol_version)
        dataset = self._load_dataset(run.dataset_id, run.dataset_version)
        split = self._load_split(run.dataset_id, run.dataset_version, run.scientific_task)
        return _build_records(
            paper_run_id=paper_run_id, protocol_id=run.protocol_id, campaign_id=run.campaign_id,
            association_policy_hash=contract.association_policy_hash, dataset=dataset, split=split,
            run_dir=self._run_dir(paper_run_id), ble_root=self.ble_root, legacy_capture_root=self.legacy_capture_root,
            load_capture=self._load_capture, load_examples=self._load_examples, progress=progress,
        )

    def get_records_status(self, paper_run_id: str) -> RecordBuildResult | None:
        path = self._canonical_records_dir(paper_run_id) / "build_result.json"
        if not path.is_file():
            return None
        return RecordBuildResult.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def _load_record_table(self, paper_run_id: str, table_name: str) -> list[dict[str, Any]]:
        path = self._canonical_records_dir(paper_run_id) / f"{table_name}.json"
        if not path.is_file():
            return []
        return json.loads(path.read_text(encoding="utf-8"))

    def list_capture_records(self, paper_run_id: str, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._load_record_table(paper_run_id, "capture_records")[offset: offset + limit]

    def get_capture_record(self, paper_run_id: str, capture_id: str) -> dict[str, Any] | None:
        for row in self._load_record_table(paper_run_id, "capture_records"):
            if row.get("capture_id") == capture_id:
                return row
        return None

    def list_burst_records(self, paper_run_id: str, *, limit: int = 100, offset: int = 0, capture_id: str | None = None) -> list[dict[str, Any]]:
        rows = self._load_record_table(paper_run_id, "burst_records")
        if capture_id:
            rows = [row for row in rows if row.get("capture_id") == capture_id]
        return rows[offset: offset + limit]

    def list_window_records(self, paper_run_id: str, *, limit: int = 100, offset: int = 0, capture_id: str | None = None) -> list[dict[str, Any]]:
        rows = self._load_record_table(paper_run_id, "decision_window_records")
        if capture_id:
            rows = [row for row in rows if row.get("capture_id") == capture_id]
        return rows[offset: offset + limit]

    def list_deviation_records(self, paper_run_id: str, *, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
        return self._load_record_table(paper_run_id, "campaign_deviations")[offset: offset + limit]

    # ------------------------------------------------------------------
    # Fase 2: campaign accounting (Sections C+D)
    # ------------------------------------------------------------------

    def build_campaign_accounting(self, paper_run_id: str) -> dict[str, Any]:
        run = self.get_run(paper_run_id)
        contract = self.get_protocol(run.protocol_id, run.protocol_version)
        return _build_campaign_accounting(run_dir=self._run_dir(paper_run_id), contract=contract)

    def get_campaign_accounting(self, paper_run_id: str) -> dict[str, Any] | None:
        path = self._run_dir(paper_run_id) / "03_campaign_accounting" / "campaign_accounting.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Fase 2: descriptive quality summary (Section E)
    # ------------------------------------------------------------------

    def build_quality_summary(self, paper_run_id: str) -> dict[str, Any]:
        return _build_quality_summary(run_dir=self._run_dir(paper_run_id))

    def get_quality_summary(self, paper_run_id: str) -> dict[str, Any] | None:
        path = self._run_dir(paper_run_id) / "04_quality" / "quality_summary.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Fase 2: descriptive figures (Section F)
    # ------------------------------------------------------------------

    def build_campaign_figures(self, paper_run_id: str) -> list[str]:
        return _build_campaign_figures(run_dir=self._run_dir(paper_run_id))

    def list_run_artifacts(self, paper_run_id: str) -> list[str]:
        run_dir = self._run_dir(paper_run_id)
        if not run_dir.is_dir():
            raise FileNotFoundError(f"PAPER_RUN_NOT_FOUND:{paper_run_id}")
        return sorted(str(path.relative_to(run_dir)).replace("\\", "/") for path in run_dir.rglob("*") if path.is_file())

    # -- integrity -------------------------------------------------------

    def _check_integrity(self, dataset: DatasetManifest, split: SplitManifest, contract: AnalysisContract) -> IntegrityCheckResult:
        findings: list[str] = []

        recomputed_dataset_hash = dataset.content_hash(exclude={"frozen", "dataset_manifest_sha256"})
        if not dataset.frozen:
            findings.append(f"Dataset {dataset.dataset_id}/{dataset.dataset_version} is not frozen.")
        if dataset.dataset_manifest_sha256 != recomputed_dataset_hash:
            findings.append(
                f"Dataset manifest hash mismatch: stored={dataset.dataset_manifest_sha256} recomputed={recomputed_dataset_hash} "
                "(the on-disk file no longer matches its own recorded hash)."
            )

        if split.split_status == "READY":
            recomputed_split_hash = split.content_hash(exclude={"split_manifest_sha256"})
            if split.split_manifest_sha256 != recomputed_split_hash:
                findings.append(
                    f"Split manifest hash mismatch: stored={split.split_manifest_sha256} recomputed={recomputed_split_hash}."
                )

        if contract.split_manifest_hash and split.split_manifest_sha256 and contract.split_manifest_hash != split.split_manifest_sha256:
            findings.append(
                f"Frozen protocol commits to split_manifest_hash={contract.split_manifest_hash}, "
                f"but this run's split is {split.split_manifest_sha256}."
            )

        example_ids = dataset.example_ids
        if len(example_ids) != len(set(example_ids)):
            duplicates = sorted({example_id for example_id in example_ids if example_ids.count(example_id) > 1})
            findings.append(f"Duplicate example_id values in dataset.example_ids: {duplicates[:10]}")

        checked_captures = 0
        for capture_id in dataset.captures:
            capture = self._load_capture(capture_id)
            if capture is None:
                findings.append(f"Capture {capture_id} referenced by dataset but has no CaptureRecord on disk.")
                continue
            checked_captures += 1
            iq_path = self._resolve_iq_path(capture)
            if not iq_path.is_file():
                findings.append(f"Capture {capture_id}: resolved iq_path does not exist on disk ({iq_path}).")
            if not capture.iq_sha256:
                findings.append(f"Capture {capture_id}: missing iq_sha256.")
            for example in self._load_examples(capture_id):
                if not (0 <= example.iq_start_sample < example.iq_end_sample <= capture.sample_count):
                    findings.append(
                        f"Example {example.example_id}: sample range [{example.iq_start_sample},{example.iq_end_sample}) "
                        f"outside capture {capture_id}'s sample_count={capture.sample_count}."
                    )

        status = "BLOCKED" if findings else "PASSED"
        return IntegrityCheckResult(status=status, findings=findings, checked_capture_count=checked_captures)

    # -- leakage -----------------------------------------------------------

    def _check_leakage(self, split: SplitManifest) -> LeakageCheckResult:
        findings: list[str] = []
        if split.split_status != "READY":
            findings.append(f"Split status is {split.split_status} ({split.infeasibility_reason or 'no reason recorded'}); no leakage-safe partition exists to analyze on.")
        elif split.leakage_check.status != "PASSED":
            findings.append(
                f"Split leakage_check.status={split.leakage_check.status}; overlapping_keys={split.leakage_check.overlapping_keys}."
            )
        status = "BLOCKED" if findings else "PASSED"
        return LeakageCheckResult(status=status, findings=findings, checked_split_ids=[f"{split.dataset_id}__{split.dataset_version}__{split.scientific_task}"])

    # -- population separation ---------------------------------------------

    def _check_population_separation(self, dataset: DatasetManifest, examples: list[ExampleRecord], contract: AnalysisContract) -> PopulationSeparationResult:
        counts = {"same_model_enrolled": 0, "cross_model_ble": 0, "ambient_ble": 0, "target_absent_control": 0}
        for example in examples:
            if example.capture_purpose == "BACKGROUND_TARGET_OFF":
                counts["target_absent_control"] += 1
            elif example.physical_unit_id is not None and example.physical_unit_id in dataset.physical_units:
                counts["same_model_enrolled"] += 1
            elif example.physical_unit_id is not None:
                counts["cross_model_ble"] += 1
            else:
                counts["ambient_ble"] += 1

        findings: list[str] = []
        declared_population = contract.device_population or {}
        for population_name, declared in declared_population.items():
            if population_name in counts and declared and counts[population_name] == 0:
                findings.append(f"Protocol declares a non-empty '{population_name}' population, but 0 examples were observed for it in this dataset.")

        status = "BLOCKED" if findings else "PASSED"
        return PopulationSeparationResult(status=status, findings=findings, population_counts=counts)

    # -- quality -------------------------------------------------------------

    def _check_quality(self, quality_report: DatasetQualityReport | None) -> QualityCheckResult:
        findings: list[str] = []
        checked = []
        if quality_report is None:
            findings.append("No DatasetQualityReport found on disk for this dataset -- the quality gate was never run.")
        else:
            checked.append(f"{quality_report.dataset_id}__{quality_report.dataset_version}")
            if quality_report.gate_decision != "ACCEPTED_FOR_TRAINING":
                findings.append(f"gate_decision={quality_report.gate_decision}; gate_reasons={quality_report.gate_reasons}")
            if quality_report.exact_duplicates.status != "PASSED":
                findings.append(f"exact_duplicates.status={quality_report.exact_duplicates.status}")
            if quality_report.sample_overlap.status != "PASSED":
                findings.append(f"sample_overlap.status={quality_report.sample_overlap.status}")
        status = "BLOCKED" if findings else "PASSED"
        return QualityCheckResult(status=status, findings=findings, checked_dataset_ids=checked)

    # -- design completeness --------------------------------------------------

    def _check_design_completeness(self, dataset: DatasetManifest, examples: list[ExampleRecord], contract: AnalysisContract) -> DesignCompletenessResult:
        findings: list[str] = []

        declared_devices = set(contract.device_ids or [])
        observed_devices = set(dataset.physical_units)
        missing_devices = declared_devices - observed_devices
        if missing_devices:
            findings.append(f"Protocol declares device_ids not present in this dataset's physical_units: {sorted(missing_devices)}")

        declared_channels = set(contract.channels or [])
        observed_channels = {example.channel for example in examples}
        missing_channels = declared_channels - observed_channels
        if missing_channels:
            findings.append(f"Protocol declares channels with no observed examples in this dataset: {sorted(missing_channels)}")

        # Informational only, never blocking on its own in Fase 1: full
        # structured protocol_deviations.jsonl accounting arrives with
        # campaign accounting in a later phase.
        status = "BLOCKED" if findings else "PASSED"
        return DesignCompletenessResult(status=status, findings=findings)

    # -- paper campaign completeness (tier 2) --------------------------------

    def _check_paper_campaign_completeness(
        self, dataset: DatasetManifest, examples: list[ExampleRecord], contract: AnalysisContract, population: PopulationSeparationResult,
    ) -> PaperCampaignCompletenessResult:
        """Whole-PAPER requirements, distinct from (and layered on top of)
        the dataset-structural checks above. Unlike design_completeness
        (tier 1, dataset-scoped), every dimension the user's specification
        lists for paper-campaign completeness is checked UNCONDITIONALLY --
        population, days, sessions, pre/post, reset/control, channels,
        content variants, independent blocks, groups/holdouts, receiver
        profile, negative controls -- never only "if the protocol happens
        to declare it". A protocol that declares nothing extra must not be
        able to trivially reach PAPER_CAMPAIGN_PREFLIGHT_PASSED by omission.

        Several of these dimensions have NO field anywhere in
        ble_rffi_studio's real capture/example schema today (verified
        directly against contracts/capture.py and contracts/example.py, not
        assumed): day identity, pre/post, intervention arm, content
        variant, and independent holdout groups. For those, this check
        always reports BLOCKED with an explicit NOT_DOCUMENTED finding --
        this is the expected, correct outcome against every real dataset in
        this repository today (see docs/ble/SCIENTIFIC_STATUS.md), not a
        bug: no capture campaign here has ever recorded a randomized
        intervention or content-variant design.
        """
        findings: list[str] = []
        checked = [
            "population", "days", "sessions", "pre_post", "reset_control", "channels",
            "content_variants", "independent_blocks", "groups_and_holdouts", "receiver_profile", "negative_controls",
        ]

        # Population.
        if not dataset.physical_units:
            findings.append("population: dataset declares 0 physical_units.")
        if contract.device_population:
            zero_populations = [name for name, declared in contract.device_population.items() if declared and population.population_counts.get(name, 0) == 0]
            if zero_populations:
                findings.append(f"population: protocol declares non-empty population(s) with 0 observed examples: {sorted(zero_populations)}.")

        # Days: NOT_DOCUMENTED -- no day_id field anywhere in ble_rffi_studio.
        findings.append("days: NOT_DOCUMENTED -- no day_id field exists anywhere in ble_rffi_studio's real capture/example schema; day-level independence cannot be verified from current artifacts.")

        # Sessions: real, checkable field (dataset.sessions).
        required_sessions = (contract.minimum_independent_blocks or {}).get("sessions")
        if required_sessions is not None and len(dataset.sessions) < required_sessions:
            findings.append(f"sessions: minimum_independent_blocks.sessions={required_sessions} declared, dataset has only {len(dataset.sessions)}.")
        elif not dataset.sessions:
            findings.append("sessions: dataset has 0 sessions.")

        # Pre/post and reset/control: NOT_DOCUMENTED -- no pre_or_post /
        # intervention_arm field anywhere.
        findings.append("pre_post: NOT_DOCUMENTED -- no pre_or_post field exists anywhere in ble_rffi_studio's real capture schema; pre/post pairing cannot be verified from current artifacts.")
        findings.append("reset_control: NOT_DOCUMENTED -- no intervention_arm field exists anywhere in ble_rffi_studio's real capture schema; reset/control balance cannot be verified from current artifacts.")

        # Channels: real, checkable field.
        declared_channels = set(contract.channels or [])
        if declared_channels:
            observed_channels = {example.channel for example in examples}
            missing = declared_channels - observed_channels
            if missing:
                findings.append(f"channels: protocol requires {sorted(declared_channels)}, but {sorted(missing)} have 0 observed examples.")
        else:
            findings.append("channels: protocol declares no channels for this paper campaign.")

        # Content variants: NOT_DOCUMENTED -- no packet_variant field.
        findings.append("content_variants: NOT_DOCUMENTED -- no packet_variant field exists anywhere in ble_rffi_studio's real capture/example schema; content-variant coverage cannot be verified from current artifacts.")

        # Independent blocks: real, checkable (reuses the same session check
        # as above plus an explicit non-empty requirement).
        if not contract.minimum_independent_blocks:
            findings.append("independent_blocks: protocol declares no minimum_independent_blocks for this paper campaign.")

        # Groups / holdouts: no future-holdout group concept is bound to a
        # dataset anywhere yet (Fase 1's holdout_access_log is a project-
        # wide audit trail, not a per-dataset holdout-group assignment).
        findings.append("groups_and_holdouts: NOT_DOCUMENTED -- no per-dataset holdout-group assignment exists anywhere yet.")

        # Receiver profile: real, checkable field.
        receiver_ids = set()
        for capture_id in dataset.captures:
            capture = self._load_capture(capture_id)
            if capture is not None:
                receiver_ids.add(capture.receiver_device_id)
        if len(receiver_ids) > 1:
            findings.append(f"receiver_profile: receiver_profile_hash={contract.receiver_profile_hash!r} is a single declared profile, but captures span {len(receiver_ids)} distinct receiver_device_id values: {sorted(receiver_ids)}.")
        elif not receiver_ids:
            findings.append("receiver_profile: no captures with a resolvable receiver_device_id were found.")

        # Negative controls: real, checkable field.
        if population.population_counts.get("target_absent_control", 0) == 0 and population.population_counts.get("ambient_ble", 0) == 0:
            findings.append("negative_controls: 0 target_absent_control and 0 ambient_ble examples observed in this dataset.")

        status = "BLOCKED" if findings else "PASSED"
        return PaperCampaignCompletenessResult(status=status, findings=findings, checked_requirements=checked)
