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
    AssociationPolicy,
    DesignCompletenessResult,
    GitDirtyState,
    HoldoutAccessLogEntry,
    HoldoutChainVerificationResult,
    HoldoutGroupAssignment,
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
from ..engineering_reports import compute_channel_transport_report as _compute_channel_transport_report
from ..engineering_reports import compute_offline_nearlive_report as _compute_offline_nearlive_report
from ..paper_export import generate_paper_exports
from ..provenance import list_inference_runs as _list_inference_runs
from ..provenance import reconstruct_decision_provenance
from ..statistics.confirmatory_analysis_runner import confirmatory_statistical_plan_to_dict
from ..statistics.confirmatory_analysis_runner import run_confirmatory_statistical_plan as _run_confirmatory_statistical_plan

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

        # P0.4 correction (2026-08-08): this used to always be a hash of
        # evidence_stage.py's own SOURCE CODE -- identical whether the
        # association *threshold* changed or not, and identical whether any
        # calibration had ever succeeded. Now it identifies a real,
        # calibrated, frozen AssociationPolicy when one exists (see
        # find_frozen_association_policy); the NO_CALIBRATED_POLICY_YET:
        # prefix makes the absence of one self-evident from the hash string
        # itself, rather than silently indistinguishable from a real policy.
        frozen_policy = self.find_frozen_association_policy()
        association_policy_hash = (
            frozen_policy.policy_hash if frozen_policy is not None
            else f"NO_CALIBRATED_POLICY_YET:{self._policy_hash(Path(evidence_stage_module.__file__))}"
        )
        contract = AnalysisContract(
            protocol_id=protocol_id, protocol_version=next_version, creation_timestamp_utc=utc_now(),
            git_commit=git_commit, git_dirty_state=git_dirty, software_environment_digest=self._software_environment_digest(),
            hardware_profile_id=payload["hardware_profile_id"], receiver_profile_hash=payload["receiver_profile_hash"],
            device_population=payload.get("device_population", {}), device_ids=payload.get("device_ids", []),
            firmware_hashes=payload.get("firmware_hashes", {}), channels=payload.get("channels", []),
            campaign_schedule=payload.get("campaign_schedule", {}), intervention_schedule=payload.get("intervention_schedule", {}),
            content_variants=payload.get("content_variants", []),
            association_policy_hash=association_policy_hash,
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
            rq2_primary_branch=payload.get("rq2_primary_branch"), rq2_branch_selection_rule=payload.get("rq2_branch_selection_rule"),
            rq3_primary_analysis=payload.get("rq3_primary_analysis"), rq4_primary_analysis=payload.get("rq4_primary_analysis"),
            sensitivity_analyses=payload.get("sensitivity_analyses", []),
            rq3_reset_control_definition=payload.get("rq3_reset_control_definition"),
            rq4_representation_definitions=payload.get("rq4_representation_definitions", {}),
            decision_window_duration_s=payload.get("decision_window_duration_s"), minimum_eligible_bursts=payload.get("minimum_eligible_bursts"),
            score_aggregation_rule=payload.get("score_aggregation_rule"), threshold_selection_procedure=payload.get("threshold_selection_procedure"),
            non_inferiority_margin=payload.get("non_inferiority_margin"), non_inferiority_direction=payload.get("non_inferiority_direction"),
            alpha=payload.get("alpha"), confirmatory_hypotheses=payload.get("confirmatory_hypotheses", []),
            holm_family=payload.get("holm_family", []), decision_rule=payload.get("decision_rule"),
            future_test_access_policy_ref=payload.get("future_test_access_policy_ref"),
        )
        contract = contract.model_copy(update={"contract_sha256": contract.content_hash(exclude={"contract_sha256"})})
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
    # Protocol freeze (explicit, ceremonial operation -- 2026-08-09)
    # ------------------------------------------------------------------
    #
    # Deliberately separate from freeze_protocol() above: that method is the
    # flexible, repeatedly-called mechanism every intermediate protocol
    # snapshot already uses (association calibration, guided validation,
    # ...), and real, passing tests rely on calling it twice for the same
    # protocol_id with no extra ceremony (test_protocol_freeze.py). This is
    # the "confirmatory readiness" ceremony the user's protocol-freeze
    # close-out explicitly asked for: it does not build a new AnalysisContract,
    # it VALIDATES an already-frozen one is complete enough to gate FUTURE
    # TEST behind, and records that validation, append-only, in
    # protocol_freeze_ledger.jsonl -- a real, immutable, hash-linked artifact.

    _CONFIRMATORY_READINESS_FIELDS = (
        "rq2_primary_branch", "rq2_branch_selection_rule", "rq3_primary_analysis", "rq4_primary_analysis",
        "rq3_reset_control_definition", "decision_window_duration_s", "minimum_eligible_bursts",
        "score_aggregation_rule", "threshold_selection_procedure", "non_inferiority_margin",
        "non_inferiority_direction", "alpha", "decision_rule", "future_test_access_policy_ref",
    )

    def _protocol_freeze_ledger_path(self) -> Path:
        return self.root / "protocol_freeze_ledger.jsonl"

    def list_protocol_freezes(self) -> list[dict[str, Any]]:
        path = self._protocol_freeze_ledger_path()
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def missing_confirmatory_readiness_fields(self, contract: AnalysisContract) -> list[str]:
        """Field names still None/empty on `contract` that
        execute_protocol_freeze() requires before it will accept this as the
        definitive, FUTURE-TEST-gating protocol. Never invents a value --
        only reports what is missing."""
        missing = []
        for field_name in self._CONFIRMATORY_READINESS_FIELDS:
            value = getattr(contract, field_name)
            if value is None or value == "":
                missing.append(field_name)
        if not contract.rq4_representation_definitions:
            missing.append("rq4_representation_definitions")
        if not contract.confirmatory_hypotheses:
            missing.append("confirmatory_hypotheses")
        if not contract.holm_family:
            missing.append("holm_family")
        return missing

    def execute_protocol_freeze(
        self, protocol_id: str, *, version: int | None = None, new_version_reason: str | None = None,
    ) -> dict[str, Any]:
        """The explicit protocol-freeze operation: validates confirmatory
        readiness (raises PROTOCOL_FREEZE_MISSING_REQUIRED_FIELDS if
        anything in _CONFIRMATORY_READINESS_FIELDS is still unset -- never
        fabricates a value to pass this check) and appends one immutable
        ledger entry hash-linked to the contract's own contract_sha256.
        Refusing to freeze this protocol_id again without an explicit
        new_version_reason is the whole point: any substantive change after
        the first successful freeze must be a NEW protocol_version with a
        stated reason, never a silent overwrite of what this ledger already
        recorded."""
        contract = self.get_protocol(protocol_id, version)
        missing = self.missing_confirmatory_readiness_fields(contract)
        if missing:
            raise ValueError(f"PROTOCOL_FREEZE_MISSING_REQUIRED_FIELDS:{','.join(missing)}")

        previous = [entry for entry in self.list_protocol_freezes() if entry["protocol_id"] == protocol_id]
        if previous and not new_version_reason:
            raise ValueError(
                f"PROTOCOL_VERSION_CONFLICT:protocol_id={protocol_id} was already frozen "
                f"(version {previous[-1]['protocol_version']}) -- pass new_version_reason to freeze a new version explicitly."
            )

        entry = {
            "protocol_id": protocol_id, "protocol_version": contract.protocol_version,
            "contract_sha256": contract.contract_sha256, "frozen_at": utc_now(),
            "new_version_reason": new_version_reason, "is_new_version_of": previous[-1]["protocol_version"] if previous else None,
        }
        path = self._protocol_freeze_ledger_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
        self.logger.info("protocol freeze executed protocol_id=%s version=%s", protocol_id, contract.protocol_version)
        return entry

    # ------------------------------------------------------------------
    # Study status / paper readiness (2026-08-10) -- pure reporting, reads
    # only. Every field here is either a direct pass-through of an
    # already-real repository method, or a presence/absence check against a
    # real file on disk -- never a new scientific computation. This is what
    # the read-only paper-progress dashboard is built on.
    # ------------------------------------------------------------------

    def _list_all_protocol_ids(self) -> list[str]:
        protocols_dir = self.root / "_protocols"
        if not protocols_dir.is_dir():
            return []
        return sorted(p.name for p in protocols_dir.iterdir() if p.is_dir())

    def get_study_status(self, protocol_id: str | None = None) -> dict[str, Any]:
        """Aggregates real, already-implemented reads into one summary --
        never computes a new scientific value. `protocol_id` resolution:
        the caller's choice if given; otherwise the most-recently-modified
        protocol directory on disk if exactly one or more exist (documented
        heuristic, not a scientific selection), else None (no protocol
        frozen at all yet)."""
        git_sha, git_dirty = self._git_provenance()

        all_protocol_ids = self._list_all_protocol_ids()
        resolved_protocol_id = protocol_id
        if resolved_protocol_id is None and all_protocol_ids:
            protocols_dir = self.root / "_protocols"
            resolved_protocol_id = max(all_protocol_ids, key=lambda pid: (protocols_dir / pid).stat().st_mtime)

        contract: Any = None
        contract_status = "NO_DATA"
        missing_fields: list[str] = []
        if resolved_protocol_id is not None:
            try:
                contract = self.get_protocol(resolved_protocol_id)
            except FileNotFoundError:
                contract = None
        if contract is not None:
            missing_fields = self.missing_confirmatory_readiness_fields(contract)
            contract_status = "INCOMPLETE" if missing_fields else "COMPLETE"

        freezes = [e for e in self.list_protocol_freezes() if resolved_protocol_id is None or e["protocol_id"] == resolved_protocol_id]
        protocol_freeze_status = "COMPLETE" if freezes else "NOT_STARTED"
        if freezes:
            contract_status = "FROZEN"

        frozen_policy = self.find_frozen_association_policy()
        association_status = "FROZEN" if frozen_policy is not None else "NONE"

        future_test_accesses = [e for e in self.list_holdout_access_log() if "FUTURE_TEST" in (e.access_path or "")]
        holdout_status = "OPENED" if future_test_accesses else "UNTOUCHED"

        real_capture_count = len(list((self.ble_root / "captures").glob("*.json"))) if (self.ble_root / "captures").is_dir() else 0

        # Simple, documented phase label -- derived purely from which real
        # artifacts exist above, never a computed scientific milestone.
        if not freezes and contract_status in ("NO_DATA", "INCOMPLETE"):
            current_phase = "B. Real hardware qualification / early study (pre-AnalysisContract)"
        elif not freezes and contract_status == "COMPLETE":
            current_phase = "O. AnalysisContract complete, protocol freeze pending"
        elif freezes and holdout_status == "UNTOUCHED":
            current_phase = "Q-S. Protocol frozen, definitive/FUTURE acquisition pending"
        else:
            current_phase = "T+. FUTURE opened, confirmatory analysis phase"

        return {
            "git_sha": git_sha, "git_dirty_state": git_dirty,
            "protocol_id": resolved_protocol_id, "all_protocol_ids": all_protocol_ids,
            "protocol_version": contract.protocol_version if contract is not None else None,
            "contract_status": contract_status, "contract_sha256": contract.contract_sha256 if contract is not None and contract.contract_sha256 else None,
            "missing_confirmatory_readiness_fields": missing_fields,
            "association_policy_status": association_status,
            "protected_future_test_status": holdout_status,
            "protocol_freeze_status": protocol_freeze_status,
            "real_capture_count": real_capture_count,
            "current_phase": current_phase,
            "generated_at": utc_now(),
        }

    # One row per paper element -> which canonical artifact backs it, and
    # whether that artifact exists on disk today. Presence-only; this never
    # inspects the CONTENT of an artifact for a scientific verdict beyond
    # "does the file exist" (real numbers stay inside the artifact itself,
    # read separately by the dashboard's per-RQ tabs).
    _PAPER_READINESS_ELEMENTS: tuple[tuple[str, str], ...] = (
        ("Abstract", "paper_exports/study_status.json"),
        ("Methods", "_protocols"),
        ("Qualification", "campaign_qualification_preflight_report.json"),
        ("RQ1", "06_statistics/rq1_acquisition_dependence_report.json"),
        ("RQ2", "06_statistics/confirmatory_future_analysis_report.json"),
        ("RQ3", "06_statistics/confirmatory_future_analysis_report.json"),
        ("RQ4", "06_statistics/confirmatory_future_analysis_report.json"),
        ("Coverage", "06_statistics/confirmatory_future_analysis_report.json"),
        ("Engineering analyses", "paper_exports/channel_transport_results.csv"),
        ("Discussion", "paper_exports/study_status.json"),
        ("Validity boundaries", "paper_exports/study_status.json"),
        ("Conclusion", "paper_exports/study_status.json"),
        ("Artifact availability", "paper_exports/export_manifest.json"),
    )

    def get_paper_readiness(self) -> list[dict[str, Any]]:
        rows = []
        for element, relative_artifact_path in self._PAPER_READINESS_ELEMENTS:
            # "06_statistics/..." paths are per-paper-run -- checked against
            # every real run directory; "_protocols"/"paper_exports/..." are
            # repository-root-relative.
            if relative_artifact_path.startswith("06_statistics/"):
                available = any((run_dir / relative_artifact_path).is_file() for run_dir in self.root.iterdir() if run_dir.is_dir() and not run_dir.name.startswith("_"))
            else:
                available = (self.root / relative_artifact_path).exists()
            confirmatory = False
            if element in ("RQ1", "RQ2", "RQ3", "RQ4", "Coverage") and available:
                # Confirmatory only if a real protocol freeze also exists --
                # a VALIDATION_DRY_RUN artifact alone is never confirmatory.
                confirmatory = bool(self.list_protocol_freezes())
            status = "COMPLETE" if (available and (element not in ("RQ1", "RQ2", "RQ3", "RQ4", "Coverage") or confirmatory)) else ("DATA_PENDING" if not available else "PRELIMINARY")
            rows.append({
                "paper_element": element, "status": status, "required_artifact": relative_artifact_path,
                "available": available, "confirmatory": confirmatory,
                "table_ready": available and confirmatory if element in ("RQ1", "RQ2", "RQ3", "RQ4", "Coverage") else available,
                "figure_ready": available and confirmatory if element in ("RQ1", "RQ2", "RQ3", "RQ4", "Coverage") else False,
                "text_ready": status == "COMPLETE",
            })
        return rows

    # ------------------------------------------------------------------
    # Campaign qualification preflight (2026-08-09) -- distinct from
    # run_preflight() above, which checks an already-frozen dataset/split
    # against disk. This checks whether the PLATFORM MECHANISM is ready for
    # a live definitive campaign: association state, RQ3/RQ4 readiness,
    # holdout integrity, and (where the caller supplies real evidence)
    # hardware/quality signals -- never fabricates a check it has no real
    # signal for, and never opens FUTURE TEST.
    # ------------------------------------------------------------------

    # The 11 gates the user's protocol-freeze close-out (point 2, 2026-08-10)
    # explicitly requires. A REQUIRED gate that is NOT_CHECKED must NEVER
    # let overall_status become READY -- only PRELIMINARY (nothing has
    # actively failed, but not everything has been verified) or NOT_READY
    # (something actively failed). Informational-only items (the granular
    # crc/eligible-bursts/abstention numbers) are reported but never gate
    # overall_status on their own -- they roll up into the required
    # "capture_continuity_and_quality_summary" gate instead.
    _REQUIRED_QUALIFICATION_GATES = (
        "b200_detected", "receiver_identity", "qualified_acquisition_profile", "channel_frequency_consistency",
        "capture_continuity_and_quality_summary", "source_iq_digest", "holdout_untouched", "association_state",
        "eq6_7_smoke_test_on_real_iq", "rq3_readiness", "rq4_eligibility",
    )

    def run_campaign_qualification_preflight(
        self, *,
        b200_detected: bool | None = None, receiver_identity_confirmed: bool | None = None,
        qualified_receiver_profile: dict[str, Any] | None = None,
        channel_frequency_integrity_ok: bool | None = None,
        capture_continuity_ok: bool | None = None, quality_summary_reviewed: bool | None = None,
        crc_valid_packet_yield: float | None = None, eligible_bursts_per_decision_window: float | None = None,
        abstention_rate: float | None = None,
        iq_digest_verified: bool | None = None,
        real_pre_post_pairs: list[Any] | None = None,
        rq4_eligible_device_count: int | None = None, rq4_total_device_count: int | None = None,
        paper_eq6_7_smoke_test_passed: bool | None = None,
    ) -> dict[str, Any]:
        items: dict[str, dict[str, Any]] = {}

        def _bool_item(name: str, value: bool | None, *, true_reason: str, false_reason: str) -> None:
            if value is None:
                items[name] = {"status": "NOT_CHECKED", "detail": "not supplied"}
            else:
                items[name] = {"status": "READY" if value else "NOT_READY", "detail": true_reason if value else false_reason}

        _bool_item("b200_detected", b200_detected, true_reason="real device detected", false_reason="no B200 detected")
        _bool_item(
            "receiver_identity", receiver_identity_confirmed,
            true_reason="receiver_identity_id resolved from a real device-queried serial", false_reason="receiver identity could not be confirmed",
        )
        items["qualified_acquisition_profile"] = (
            {"status": "READY", "detail": qualified_receiver_profile} if qualified_receiver_profile
            else {"status": "NOT_CHECKED", "detail": "not supplied"}
        )
        _bool_item(
            "channel_frequency_consistency", channel_frequency_integrity_ok,
            true_reason="channel<->frequency mapping verified", false_reason="channel<->frequency mismatch found",
        )

        # Informational sub-metrics, never gate overall_status by themselves
        # -- they roll up into the one required
        # capture_continuity_and_quality_summary gate below.
        if crc_valid_packet_yield is not None:
            items["crc_valid_packet_yield"] = {"status": "INFO", "detail": crc_valid_packet_yield}
        if eligible_bursts_per_decision_window is not None:
            items["eligible_bursts_per_decision_window"] = {"status": "INFO", "detail": eligible_bursts_per_decision_window}
        if abstention_rate is not None:
            items["abstention_insufficient_evidence_rate"] = {"status": "INFO", "detail": abstention_rate}

        if quality_summary_reviewed is None or capture_continuity_ok is None:
            items["capture_continuity_and_quality_summary"] = {"status": "NOT_CHECKED", "detail": "not supplied"}
        elif not capture_continuity_ok:
            items["capture_continuity_and_quality_summary"] = {"status": "NOT_READY", "detail": "discontinuities found"}
        elif not quality_summary_reviewed:
            items["capture_continuity_and_quality_summary"] = {"status": "NOT_READY", "detail": "quality summary not reviewed/accepted"}
        else:
            items["capture_continuity_and_quality_summary"] = {"status": "READY", "detail": "no unexpected discontinuities; quality summary reviewed"}

        _bool_item("source_iq_digest", iq_digest_verified, true_reason="iq_sha256 verified against real bytes", false_reason="iq_sha256 mismatch")

        frozen_policy = self.find_frozen_association_policy()
        items["association_state"] = (
            {"status": "READY", "detail": frozen_policy.policy_hash} if frozen_policy is not None
            else {"status": "NOT_READY", "detail": "find_frozen_association_policy() returned None -- real, current, not a bug"}
        )

        # RQ3 readiness requires the caller to actually have run
        # build_pre_post_pairs() and supplied the real result -- previously
        # this defaulted to "MECHANISM_READY" unconditionally, which could
        # never be blocking; that was itself the bug this correction closes.
        if real_pre_post_pairs is None:
            items["rq3_readiness"] = {"status": "NOT_CHECKED", "detail": "not supplied -- caller must run build_pre_post_pairs() first"}
        else:
            valid_pairs = [p for p in real_pre_post_pairs if getattr(p, "valid", False)]
            items["rq3_readiness"] = {
                "status": "READY",
                "detail": f"build_pre_post_pairs() executed: {len(valid_pairs)}/{len(real_pre_post_pairs)} real pair(s) valid (0 valid pairs is still a real, checked result, not a blocker by itself)",
            }

        if rq4_total_device_count is None:
            items["rq4_eligibility"] = {"status": "NOT_CHECKED", "detail": "not supplied"}
        else:
            items["rq4_eligibility"] = {
                "status": "READY" if (rq4_eligible_device_count or 0) > 0 else "NOT_READY",
                "detail": f"{rq4_eligible_device_count or 0}/{rq4_total_device_count} device(s) marked RQ4 ELIGIBLE",
            }

        future_test_accesses = [e for e in self.list_holdout_access_log() if "FUTURE_TEST" in (e.access_path or "")]
        items["holdout_untouched"] = (
            {"status": "READY", "detail": "0 FUTURE_TEST accesses logged"} if not future_test_accesses
            else {"status": "NOT_READY", "detail": f"{len(future_test_accesses)} FUTURE_TEST access(es) already logged"}
        )

        _bool_item(
            "eq6_7_smoke_test_on_real_iq", paper_eq6_7_smoke_test_passed,
            true_reason="apply_base_preprocessing_with_provenance smoke test APPLIED on a real burst",
            false_reason="smoke test did not reach APPLIED",
        )

        required_statuses = {name: items[name]["status"] for name in self._REQUIRED_QUALIFICATION_GATES}
        if any(status == "NOT_READY" for status in required_statuses.values()):
            overall = "NOT_READY"
        elif any(status == "NOT_CHECKED" for status in required_statuses.values()):
            overall = "PRELIMINARY"
        else:
            overall = "READY"
        reasons = [f"{name}: {status}" for name, status in required_statuses.items() if status != "READY"]

        report = {
            "schema_version": "ble-scientific-results-campaign-qualification-preflight-v2",
            "generated_at": utc_now(), "overall_status": overall, "required_gates": list(self._REQUIRED_QUALIFICATION_GATES),
            "reasons": reasons, "items": items,
        }
        atomic_json(self.root / "campaign_qualification_preflight_report.json", report)
        self.logger.info("campaign qualification preflight overall_status=%s", overall)
        return report

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
    # Fase 1 closure item 10: real holdout groups -- mechanism only, no
    # real 20-day campaign data exists yet to populate FUTURE_TEST with.
    # ------------------------------------------------------------------

    def _holdout_groups_dir(self, dataset_id: str, dataset_version: str) -> Path:
        if any(part in dataset_id or part in dataset_version for part in ("/", "\\", "..")):
            raise ValueError("INVALID_DATASET_IDENTITY")
        return self.root / "_holdout_groups" / f"{dataset_id}__{dataset_version}"

    def freeze_holdout_groups(
        self, *, dataset_id: str, dataset_version: str, group: str,
        physical_unit_ids: list[str] | None = None, day_ids: list[str] | None = None, session_ids: list[str] | None = None,
    ) -> HoldoutGroupAssignment:
        frozen_at = utc_now()
        draft = HoldoutGroupAssignment(
            assignment_id=HoldoutGroupAssignment.make_assignment_id(dataset_id=dataset_id, dataset_version=dataset_version, group=group, frozen_at=frozen_at),
            dataset_id=dataset_id, dataset_version=dataset_version, group=group,
            physical_unit_ids=physical_unit_ids or [], day_ids=day_ids or [], session_ids=session_ids or [],
            frozen_at=frozen_at, group_manifest_sha256="",
        )
        assignment = draft.model_copy(update={"group_manifest_sha256": draft.content_hash(exclude={"group_manifest_sha256"})})
        directory = self._holdout_groups_dir(dataset_id, dataset_version)
        atomic_json(directory / f"{assignment.assignment_id}.json", assignment.model_dump(mode="json"))
        self.logger.info("holdout group frozen dataset=%s/%s group=%s assignment_id=%s", dataset_id, dataset_version, group, assignment.assignment_id)
        return assignment

    def list_holdout_groups(self, dataset_id: str, dataset_version: str) -> list[HoldoutGroupAssignment]:
        directory = self._holdout_groups_dir(dataset_id, dataset_version)
        if not directory.is_dir():
            return []
        assignments = [HoldoutGroupAssignment.model_validate(json.loads(path.read_text(encoding="utf-8"))) for path in sorted(directory.glob("*.json"))]
        return sorted(assignments, key=lambda a: a.frozen_at, reverse=True)

    def read_group(
        self, dataset_id: str, dataset_version: str, group: str, *, actor: str, process: str, reason: str, paper_run_id: str | None = None,
    ) -> HoldoutGroupAssignment | None:
        """FUTURE_TEST reads are ALWAYS logged through the same chained
        holdout access log Fase 1 already built -- no other read path for
        FUTURE_TEST exists in this repository. TRAIN/VALIDATION reads are
        not gated (they are exactly what preprocessing/model selection is
        allowed to see)."""
        assignments = [a for a in self.list_holdout_groups(dataset_id, dataset_version) if a.group == group]
        if group == "FUTURE_TEST":
            self.log_holdout_access(
                actor=actor, process=process, access_type="READ_GROUP", access_path=f"holdout_groups/{dataset_id}/{dataset_version}/FUTURE_TEST",
                resource_id=f"{dataset_id}__{dataset_version}__FUTURE_TEST", resource_hash=assignments[0].group_manifest_sha256 if assignments else None,
                reason=reason, paper_run_id=paper_run_id, analysis_contract_hash=None,
            )
        return assignments[0] if assignments else None

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

    def run_confirmatory_statistical_plan(self, paper_run_id: str, **kwargs: Any) -> dict[str, Any]:
        """Real production caller for statistics/confirmatory_analysis_runner.py
        (2026-08-09 -- connects hierarchical_cluster_bootstrap, coverage,
        the RQ3 permutation test, the RQ4 paired comparison, non-inferiority,
        Holm, and leave-one-device-out to a real, reachable path, instead of
        only a unit test). `**kwargs` are the same VALIDATION-only,
        already-scored inputs run_confirmatory_statistical_plan() itself
        accepts -- this method never assembles TEST/FUTURE_TEST data and
        never opens a holdout group. Persisted to
        06_statistics/confirmatory_statistical_plan_report.json; every
        method not given real data is honestly SKIPPED_NO_DATA, never a
        fabricated number."""
        report = _run_confirmatory_statistical_plan(**kwargs)
        as_dict = confirmatory_statistical_plan_to_dict(report)
        atomic_json(self._run_dir(paper_run_id) / "06_statistics" / "confirmatory_statistical_plan_report.json", as_dict)
        self.logger.info("confirmatory_statistical_plan paper_run_id=%s", paper_run_id)
        return as_dict

    def get_confirmatory_statistical_plan_report(self, paper_run_id: str) -> dict[str, Any] | None:
        path = self._run_dir(paper_run_id) / "06_statistics" / "confirmatory_statistical_plan_report.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    class ProtocolFreezeGateError(Exception):
        pass

    def run_confirmatory_future_analysis(
        self, *, paper_run_id: str, protocol_id: str, dataset_id: str, dataset_version: str,
        bundle_confirmatory_eligible: bool, declared_contract_sha256: str | None = None, **stats_kwargs: Any,
    ) -> dict[str, Any]:
        """Protocol-freeze close-out, point 3 (2026-08-10): the
        CONFIRMATORY_FUTURE role. run_confirmatory_statistical_plan() /
        ScientificResultsRepository.run_confirmatory_statistical_plan() above
        is the OTHER role -- VALIDATION_DRY_RUN -- and never touches
        FUTURE_TEST. This method is the only path allowed to run the SAME
        11-method statistical engine over FUTURE-scoped data, and it does so
        ONLY after every one of these real, non-bypassable gates passes (in
        order, first failure wins):
          1. a real protocol freeze exists for `protocol_id`
             (execute_protocol_freeze() must have been called for real --
             checked via list_protocol_freezes(), never freeze_protocol()
             alone, which has no confirmatory-readiness gate);
          2. the frozen AnalysisContract carries a real contract_sha256;
          3. the dataset has a real FUTURE_TEST holdout role assigned
             (list_holdout_groups());
          4. the bundle this analysis would score is confirmatory_eligible;
          5. the caller-declared contract_sha256 (if supplied) and the
             protocol_id/protocol_version match the real frozen ledger entry
             exactly -- never a stale or substituted contract.
        Only once all five pass does this call
        self.read_group(..., "FUTURE_TEST", ...) -- the ONLY real read path
        for FUTURE_TEST data anywhere in this repository -- which itself
        logs the access through the existing hash-chained holdout log."""
        freezes = [e for e in self.list_protocol_freezes() if e["protocol_id"] == protocol_id]
        if not freezes:
            raise self.ProtocolFreezeGateError(f"NO_REAL_PROTOCOL_FREEZE_EXECUTED:protocol_id={protocol_id}")
        latest_freeze = freezes[-1]

        contract = self.get_protocol(protocol_id, latest_freeze["protocol_version"])
        if not contract.contract_sha256:
            raise self.ProtocolFreezeGateError(f"MISSING_CONTRACT_SHA256:protocol_id={protocol_id}")

        holdout_groups = self.list_holdout_groups(dataset_id, dataset_version)
        if not any(g.group == "FUTURE_TEST" for g in holdout_groups):
            raise self.ProtocolFreezeGateError(f"DATASET_HAS_NO_FUTURE_TEST_HOLDOUT_ROLE:{dataset_id}__{dataset_version}")

        if not bundle_confirmatory_eligible:
            raise self.ProtocolFreezeGateError("BUNDLE_NOT_CONFIRMATORY_ELIGIBLE")

        if declared_contract_sha256 is not None and declared_contract_sha256 != contract.contract_sha256:
            raise self.ProtocolFreezeGateError(
                f"CONTRACT_HASH_MISMATCH:declared={declared_contract_sha256} frozen={contract.contract_sha256}"
            )
        if latest_freeze["protocol_version"] != contract.protocol_version:
            raise self.ProtocolFreezeGateError(
                f"PROTOCOL_VERSION_MISMATCH:freeze_ledger={latest_freeze['protocol_version']} loaded_contract={contract.protocol_version}"
            )

        # All five gates passed -- the ONLY real FUTURE_TEST read path,
        # already hash-chain-logged by read_group() itself.
        self.read_group(
            dataset_id, dataset_version, "FUTURE_TEST", actor="run_confirmatory_future_analysis",
            process="ScientificResultsRepository", reason="confirmatory future analysis", paper_run_id=paper_run_id,
        )
        report = _run_confirmatory_statistical_plan(**stats_kwargs)
        as_dict = confirmatory_statistical_plan_to_dict(report)
        atomic_json(self._run_dir(paper_run_id) / "06_statistics" / "confirmatory_future_analysis_report.json", as_dict)
        self.logger.info("confirmatory FUTURE analysis executed paper_run_id=%s protocol_id=%s", paper_run_id, protocol_id)
        return as_dict

    def get_confirmatory_future_analysis_report(self, paper_run_id: str) -> dict[str, Any] | None:
        path = self._run_dir(paper_run_id) / "06_statistics" / "confirmatory_future_analysis_report.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def persist_rq1_acquisition_dependence_report(
        self, *, paper_run_id: str, protocol_id: str, protocol_version: int, contract_sha256: str,
        rq1_report: Any, model_bundle_id: str, model_bundle_sha256: str,
        confirmatory_split_manifest_id: str, confirmatory_split_manifest_sha256: str,
        diagnostic_split_manifest_id: str, diagnostic_split_manifest_sha256: str,
        source_evaluation_domains: dict[str, Any], uncertainty_ci: dict[str, Any] | None = None,
        coverage: float | None = None,
        confusion_matrix_capture: dict[str, dict[str, int]] | None = None,
        confusion_matrix_future: dict[str, dict[str, int]] | None = None,
        per_unit_recall: dict[str, dict[str, float]] | None = None,
    ) -> dict[str, Any]:
        """Protocol-freeze close-out, point 4 (2026-08-10): the canonical,
        persisted RQ1 artifact -- evaluate_rq1_acquisition_dependence()
        (ble_rffi_studio/evaluation/rq1_acquisition_dependence.py) computes
        BA_window/BA_capture/BA_future/delta_dependence/delta_future in
        memory only; this is the ONLY place that writes them to disk, and
        only ever with real, caller-supplied linking metadata -- there is no
        default that lets this method run with placeholder ids/hashes, and
        it computes no number of its own (uncertainty_ci/coverage/confusion
        matrices/per_unit_recall are all pass-through, never invented here
        -- confusion_matrix_* mirrors SplitEvaluationReport.confusion_matrix's
        own dict-of-dicts shape exactly, added 2026-08-11 so the paper
        export's confusion-matrix figures have a real source)."""
        git_sha, _ = self._git_provenance()
        artifact = {
            "schema_version": "ble-scientific-results-rq1-acquisition-dependence-v1",
            "protocol_id": protocol_id, "protocol_version": protocol_version, "contract_sha256": contract_sha256, "git_sha": git_sha,
            "model_bundle_id": model_bundle_id, "model_bundle_sha256": model_bundle_sha256,
            "confirmatory_split_manifest_id": confirmatory_split_manifest_id, "confirmatory_split_manifest_sha256": confirmatory_split_manifest_sha256,
            "diagnostic_split_manifest_id": diagnostic_split_manifest_id, "diagnostic_split_manifest_sha256": diagnostic_split_manifest_sha256,
            "source_evaluation_domains": source_evaluation_domains,
            "ba_window": rq1_report.ba_window, "ba_window_n_comparable": rq1_report.ba_window_n_comparable,
            "ba_capture": rq1_report.ba_capture, "ba_capture_n_comparable": rq1_report.ba_capture_n_comparable,
            "ba_future": rq1_report.ba_future, "ba_future_status": rq1_report.ba_future_status, "ba_future_n_comparable": rq1_report.ba_future_n_comparable,
            "delta_dependence": rq1_report.delta_dependence, "delta_future": rq1_report.delta_future,
            "uncertainty_ci": uncertainty_ci, "coverage": coverage,
            "confusion_matrix_capture": confusion_matrix_capture, "confusion_matrix_future": confusion_matrix_future,
            "per_unit_recall": per_unit_recall,
            "generated_at": utc_now(),
        }
        atomic_json(self._run_dir(paper_run_id) / "06_statistics" / "rq1_acquisition_dependence_report.json", artifact)
        self.logger.info("rq1 acquisition-dependence report persisted paper_run_id=%s protocol_id=%s", paper_run_id, protocol_id)
        return artifact

    def get_rq1_acquisition_dependence_report(self, paper_run_id: str) -> dict[str, Any] | None:
        path = self._run_dir(paper_run_id) / "06_statistics" / "rq1_acquisition_dependence_report.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def run_paper_export(self) -> dict[str, Any]:
        """Real production caller for paper_export.py -- writes
        `paper_exports/` for real (study_status.json/paper_readiness.json)
        and records every other planned export as SKIPPED_NO_DATA until a
        real campaign produces source data for it. Never mutates the
        protocol, never opens FUTURE_TEST."""
        manifest = generate_paper_exports(self)
        self.logger.info("paper export generated: %s produced, %s skipped_no_data", manifest["generated_count"], manifest["skipped_count"])
        return manifest

    def get_paper_export_manifest(self) -> dict[str, Any] | None:
        path = self.root / "paper_exports" / "export_manifest.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Provenance reconstruction (2026-08-11) -- strictly read-only.
    # ------------------------------------------------------------------

    def list_inference_runs(self) -> list[dict[str, Any]]:
        return _list_inference_runs(self)

    def get_decision_provenance(self, *, inference_run_id: str, example_id: str) -> dict[str, Any]:
        return reconstruct_decision_provenance(self, inference_run_id=inference_run_id, example_id=example_id)

    # ------------------------------------------------------------------
    # Engineering reports: S1 channel transport, S2 offline/near-live
    # (2026-08-11) -- pure aggregation over caller-supplied, already-scored
    # predictions; never retrains, never a new statistical test. NO_DATA
    # persisted-report reads mirror the RQ1/confirmatory-future pattern.
    # ------------------------------------------------------------------

    def compute_channel_transport_report(self, **kwargs: Any) -> dict[str, Any]:
        from dataclasses import asdict
        return asdict(_compute_channel_transport_report(**kwargs))

    def persist_channel_transport_report(self, paper_run_id: str, report: dict[str, Any]) -> dict[str, Any]:
        atomic_json(self._run_dir(paper_run_id) / "06_statistics" / "channel_transport_report.json", report)
        return report

    def get_channel_transport_report(self, paper_run_id: str) -> dict[str, Any] | None:
        path = self._run_dir(paper_run_id) / "06_statistics" / "channel_transport_report.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def compute_offline_nearlive_report(self, **kwargs: Any) -> dict[str, Any]:
        from dataclasses import asdict
        return asdict(_compute_offline_nearlive_report(**kwargs))

    def persist_offline_nearlive_report(self, paper_run_id: str, report: dict[str, Any]) -> dict[str, Any]:
        atomic_json(self._run_dir(paper_run_id) / "06_statistics" / "offline_nearlive_report.json", report)
        return report

    def get_offline_nearlive_report(self, paper_run_id: str) -> dict[str, Any] | None:
        path = self._run_dir(paper_run_id) / "06_statistics" / "offline_nearlive_report.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    # ------------------------------------------------------------------
    # Fase 2: canonical records (Section B)
    # ------------------------------------------------------------------

    def _canonical_records_dir(self, paper_run_id: str) -> Path:
        return self._run_dir(paper_run_id) / "01_inputs" / "canonical_records"

    def find_frozen_association_policy(self) -> AssociationPolicy | None:
        """P0.4 correction (2026-08-08): scans every real calibration
        attempt's persisted result (written by Guided Validation's
        association-policy calibration -- see
        guided_validation/service.py::_attempt_policy) for the most
        recently frozen, real AssociationPolicy, so build_records() picks
        one up automatically the moment a real calibration campaign ever
        succeeds, with zero further code changes. Returns None when no
        calibration has ever succeeded -- the honest, current state of
        every real calibration attempt on disk as of 2026-08, all of which
        report NO_THRESHOLD_SATISFIES_CRITERIA. Deliberately does not
        consider FROZEN_STRATIFIED (per-device-family) policies here --
        build_records() applies one policy project-wide; stratified policy
        selection per device family is a documented future extension, not
        silently approximated by picking one family's policy for everyone."""
        candidates: list[AssociationPolicy] = []
        guided_validation_root = self.root / "guided_validation"
        if guided_validation_root.is_dir():
            for policy_path in guided_validation_root.glob("*/association_policy.json"):
                try:
                    data = json.loads(policy_path.read_text(encoding="utf-8-sig"))
                except (json.JSONDecodeError, OSError):
                    continue
                if data.get("status") == "FROZEN" and isinstance(data.get("policy"), dict):
                    try:
                        candidates.append(AssociationPolicy.model_validate(data["policy"]))
                    except Exception:
                        continue
        if not candidates:
            return None
        return max(candidates, key=lambda policy: policy.frozen_at)

    def build_records(self, paper_run_id: str, *, schedule_id: str | None = None, association_policy: AssociationPolicy | None = None, progress=None) -> RecordBuildResult:
        """`schedule_id`, when the campaign this run covers was executed
        through PaperCampaignRunner, pulls in that schedule's persisted
        pre-capture rejections (see records/build_records.py) as canonical
        PROTOCOL_DEVIATION rows -- optional because most runs today still
        predate the runner and have no schedule to check.

        `association_policy`: without a real, frozen policy (produced by a
        real calibration campaign -- see calibration/association_calibration.py),
        every burst's TARGET_ASSOCIATED_PACKET classification is disabled
        (STRONG_ASSOCIATION_DISABLED_UNTIL_POLICY_FROZEN) regardless of what
        the underlying ledger contains -- there is no default threshold.
        Callers normally leave this None and let it auto-resolve via
        find_frozen_association_policy() -- pass one explicitly only to
        pin a specific historical policy version."""
        if association_policy is None:
            association_policy = self.find_frozen_association_policy()
        run = self.get_run(paper_run_id)
        contract = self.get_protocol(run.protocol_id, run.protocol_version)
        dataset = self._load_dataset(run.dataset_id, run.dataset_version)
        split = self._load_split(run.dataset_id, run.dataset_version, run.scientific_task)
        return _build_records(
            paper_run_id=paper_run_id, protocol_id=run.protocol_id, campaign_id=run.campaign_id,
            association_policy_hash=contract.association_policy_hash, dataset=dataset, split=split,
            run_dir=self._run_dir(paper_run_id), ble_root=self.ble_root, legacy_capture_root=self.legacy_capture_root,
            load_capture=self._load_capture, load_examples=self._load_examples, schedule_id=schedule_id,
            association_policy=association_policy, progress=progress,
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
            # split_purpose/non_confirmatory (2026-08-09) are excluded here
            # too -- must match split_builder.py's own _HASH_EXCLUDED_FIELDS
            # exactly, or every real historical split would report a false
            # hash mismatch purely from an additive metadata tag that
            # predates their existence.
            recomputed_split_hash = split.content_hash(exclude={"split_manifest_sha256", "split_purpose", "non_confirmatory"})
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
    ) -> PaperCampaignCompletenessResult:  # noqa: C901 -- see per-dimension comments; splitting further would scatter the shared checked/findings state
        holdout_groups = self.list_holdout_groups(dataset.dataset_id, dataset.dataset_version)
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

        # Content variants: NOT_DOCUMENTED -- packet_condition field exists
        # (contracts/capture.py) but is never populated on any real capture.
        findings.append("content_variants: NOT_DOCUMENTED -- packet_condition field exists in ble_rffi_studio's real capture schema but is never populated on any real capture; content-variant coverage cannot be verified from current artifacts.")

        # Independent blocks: real, checkable (reuses the same session check
        # as above plus an explicit non-empty requirement).
        if not contract.minimum_independent_blocks:
            findings.append("independent_blocks: protocol declares no minimum_independent_blocks for this paper campaign.")

        # Groups / holdouts: now checkable for real once freeze_holdout_groups()
        # has actually been called for this dataset (Fase 1 closure item 10).
        groups_present = {a.group for a in holdout_groups}
        required_groups = {"TRAIN", "VALIDATION", "FUTURE_TEST"}
        missing_groups = required_groups - groups_present
        if missing_groups:
            findings.append(f"groups_and_holdouts: no real HoldoutGroupAssignment exists yet for group(s) {sorted(missing_groups)} on this dataset -- call freeze_holdout_groups() before this can pass.")

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
