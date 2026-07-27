"""Builds TRAIN/VALIDATION/TEST splits by whole session, never by window
within a session, and never assumes 3 splits are always possible -- each
scientific_task has its own minimum-evidence rule (design correction #7).
When a task's requirement isn't met, split_status=NOT_FEASIBLE with an exact
reason, never an artificial split.

physical_unit_id repeating across splits is correct here (needed to evaluate
that class); what must never repeat is capture_id/execution_id/session_id/
candidate_id/packet_id/sample-range -- computed and checked for real via
_compute_leakage, never assumed from the construction method alone.
"""
from __future__ import annotations

from ..contracts import DatasetManifest, ExampleRecord, LeakageCheckResult, SplitAssignment, SplitManifest

_SPLIT_NAMES = ("TRAIN", "VALIDATION", "TEST")
_LEAKAGE_FIELDS = ["capture_id", "execution_id", "session_id", "candidate_id", "packet_id", "sample_range"]
_MIN_SESSIONS_PER_UNIT = 3
_MIN_TARGET_SESSIONS = 3
_MIN_BACKGROUND_SESSIONS = 1
_MIN_UNKNOWN_SESSIONS = 2


class SplitBuilder:
    def build(self, *, dataset: DatasetManifest, examples: list[ExampleRecord], scientific_task: str, created_at: str) -> SplitManifest:
        by_id = {e.example_id: e for e in examples}
        selected = [by_id[eid] for eid in dataset.example_ids if eid in by_id]

        if scientific_task in ("SAME_MODEL_UNIT_IDENTIFICATION", "MULTI_DEVICE_CLASSIFICATION"):
            return self._closed_set_classification(dataset, selected, scientific_task, created_at)
        if scientific_task == "TARGET_VS_BACKGROUND":
            return self._target_vs_background(dataset, selected, created_at)
        if scientific_task == "UNKNOWN_DEVICE_REJECTION":
            return self._unknown_device_rejection(dataset, selected, created_at)
        raise ValueError(f"UNKNOWN_SCIENTIFIC_TASK:{scientific_task}")

    # ------------------------------------------------------------------

    def _sessions_by_unit(self, examples: list[ExampleRecord]) -> dict[str, dict[str, list[ExampleRecord]]]:
        result: dict[str, dict[str, list[ExampleRecord]]] = {}
        for example in examples:
            if not example.physical_unit_id:
                continue
            result.setdefault(example.physical_unit_id, {}).setdefault(example.session_id, []).append(example)
        return result

    def _closed_set_classification(self, dataset: DatasetManifest, examples: list[ExampleRecord], scientific_task: str, created_at: str) -> SplitManifest:
        policy = "session_disjoint_per_unit"
        sessions_by_unit = self._sessions_by_unit(examples)
        ready_units = {unit: sessions for unit, sessions in sessions_by_unit.items() if len(sessions) >= _MIN_SESSIONS_PER_UNIT}
        if len(sessions_by_unit) < 2 or len(ready_units) < 2:
            reason = (
                f"{scientific_task} requires >=2 physical units, each with >={_MIN_SESSIONS_PER_UNIT} independent "
                f"sessions (one per split); found {len(sessions_by_unit)} unit(s) total, {len(ready_units)} with enough sessions."
            )
            return self._not_feasible(dataset, scientific_task, policy, reason, created_at)

        assignments: list[SplitAssignment] = []
        for unit, sessions in ready_units.items():
            for idx, session_id in enumerate(sorted(sessions.keys())):
                split = _SPLIT_NAMES[idx] if idx < 3 else "TRAIN"
                for example in sessions[session_id]:
                    assignments.append(SplitAssignment(example_id=example.example_id, physical_unit_id=unit, capture_id=example.capture_id, session_id=session_id, split=split, split_reason=policy))

        leakage = self._compute_leakage(assignments, {e.example_id: e for e in examples})
        return self._finalize(dataset, scientific_task, policy, assignments, leakage, created_at)

    def _target_vs_background(self, dataset: DatasetManifest, examples: list[ExampleRecord], created_at: str) -> SplitManifest:
        scientific_task, policy = "TARGET_VS_BACKGROUND", "target_background_session_disjoint"
        target_examples = [e for e in examples if e.physical_unit_id]
        background_examples = [e for e in examples if not e.physical_unit_id]
        target_sessions = sorted({e.session_id for e in target_examples})
        background_sessions = sorted({e.session_id for e in background_examples})

        if len(target_sessions) < _MIN_TARGET_SESSIONS:
            reason = f"{scientific_task} requires >={_MIN_TARGET_SESSIONS} independent target sessions (one per split); found {len(target_sessions)}."
            return self._not_feasible(dataset, scientific_task, policy, reason, created_at)
        if len(background_sessions) < _MIN_BACKGROUND_SESSIONS:
            reason = f"{scientific_task} requires >={_MIN_BACKGROUND_SESSIONS} background/environmental session reserved outside TRAIN; found {len(background_sessions)}."
            return self._not_feasible(dataset, scientific_task, policy, reason, created_at)

        assignments: list[SplitAssignment] = []
        for idx, session_id in enumerate(target_sessions):
            split = _SPLIT_NAMES[idx] if idx < 3 else "TRAIN"
            for example in target_examples:
                if example.session_id == session_id:
                    assignments.append(SplitAssignment(example_id=example.example_id, physical_unit_id=example.physical_unit_id, capture_id=example.capture_id, session_id=session_id, split=split, split_reason=policy))

        # Negatives are never used in TRAIN -- split only across VALIDATION/TEST.
        non_train = ("TEST", "VALIDATION")
        for idx, session_id in enumerate(background_sessions):
            split = non_train[idx % 2]
            for example in background_examples:
                if example.session_id == session_id:
                    assignments.append(SplitAssignment(example_id=example.example_id, physical_unit_id=None, capture_id=example.capture_id, session_id=session_id, split=split, split_reason=f"{policy}:negatives_never_in_train"))

        leakage = self._compute_leakage(assignments, {e.example_id: e for e in examples})
        return self._finalize(dataset, scientific_task, policy, assignments, leakage, created_at)

    def _unknown_device_rejection(self, dataset: DatasetManifest, examples: list[ExampleRecord], created_at: str) -> SplitManifest:
        scientific_task, policy = "UNKNOWN_DEVICE_REJECTION", "known_vs_unknown_session_disjoint"
        known_examples = [e for e in examples if e.physical_unit_id]
        unknown_examples = [e for e in examples if not e.physical_unit_id]
        sessions_by_unit = self._sessions_by_unit(known_examples)
        ready_units = {unit: sessions for unit, sessions in sessions_by_unit.items() if len(sessions) >= _MIN_SESSIONS_PER_UNIT}
        unknown_sessions = sorted({e.session_id for e in unknown_examples})

        if not ready_units:
            reason = f"{scientific_task} requires >=1 known physical unit with >={_MIN_SESSIONS_PER_UNIT} independent sessions; none found."
            return self._not_feasible(dataset, scientific_task, policy, reason, created_at)
        if len(unknown_sessions) < _MIN_UNKNOWN_SESSIONS:
            reason = f"{scientific_task} requires >={_MIN_UNKNOWN_SESSIONS} independent 'unknown device' sessions (split across VALIDATION/TEST only, never TRAIN); found {len(unknown_sessions)}."
            return self._not_feasible(dataset, scientific_task, policy, reason, created_at)

        assignments: list[SplitAssignment] = []
        for unit, sessions in ready_units.items():
            for idx, session_id in enumerate(sorted(sessions.keys())):
                split = _SPLIT_NAMES[idx] if idx < 3 else "TRAIN"
                for example in sessions[session_id]:
                    assignments.append(SplitAssignment(example_id=example.example_id, physical_unit_id=unit, capture_id=example.capture_id, session_id=session_id, split=split, split_reason=policy))

        non_train = ("VALIDATION", "TEST")
        for idx, session_id in enumerate(unknown_sessions):
            split = non_train[idx % 2]
            for example in unknown_examples:
                if example.session_id == session_id:
                    assignments.append(SplitAssignment(example_id=example.example_id, physical_unit_id=None, capture_id=example.capture_id, session_id=session_id, split=split, split_reason=f"{policy}:unknowns_never_in_train"))

        leakage = self._compute_leakage(assignments, {e.example_id: e for e in examples})
        return self._finalize(dataset, scientific_task, policy, assignments, leakage, created_at)

    # ------------------------------------------------------------------

    def _leakage_value(self, example: ExampleRecord, field: str) -> str:
        if field == "sample_range":
            return f"{example.source_iq_sha256}:{example.iq_start_sample}:{example.iq_end_sample}"
        return str(getattr(example, field))

    def _compute_leakage(self, assignments: list[SplitAssignment], examples_by_id: dict[str, ExampleRecord]) -> LeakageCheckResult:
        value_to_splits: dict[str, dict[str, set[str]]] = {field: {} for field in _LEAKAGE_FIELDS}
        for assignment in assignments:
            example = examples_by_id[assignment.example_id]
            for field in _LEAKAGE_FIELDS:
                value = self._leakage_value(example, field)
                value_to_splits[field].setdefault(value, set()).add(assignment.split)

        overlapping: dict[str, list[str]] = {}
        for field, mapping in value_to_splits.items():
            bad = sorted(value for value, splits in mapping.items() if len(splits) > 1)
            if bad:
                overlapping[field] = bad

        return LeakageCheckResult(
            status="FAILED" if overlapping else "PASSED",
            checked_group_fields=_LEAKAGE_FIELDS,
            overlapping_keys=overlapping,
            evidence=f"Checked {len(assignments)} assignment(s) across {len(examples_by_id)} example(s).",
        )

    def _not_feasible(self, dataset: DatasetManifest, scientific_task: str, policy: str, reason: str, created_at: str) -> SplitManifest:
        manifest = SplitManifest(
            dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version, scientific_task=scientific_task, policy=policy,
            split_status="NOT_FEASIBLE", infeasibility_reason=reason, assignments=[],
            leakage_check=LeakageCheckResult(status="NOT_EXECUTED"), created_at=created_at,
        )
        sha256 = manifest.content_hash(exclude={"split_manifest_sha256"})
        return manifest.model_copy(update={"split_manifest_sha256": sha256})

    def _finalize(self, dataset: DatasetManifest, scientific_task: str, policy: str, assignments: list[SplitAssignment], leakage: LeakageCheckResult, created_at: str) -> SplitManifest:
        if leakage.status == "FAILED":
            split_status, infeasibility_reason = "NOT_FEASIBLE", f"Leakage check failed on field(s): {sorted(leakage.overlapping_keys.keys())}"
        else:
            split_status, infeasibility_reason = "READY", None
        manifest = SplitManifest(
            dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version, scientific_task=scientific_task, policy=policy,
            split_status=split_status, infeasibility_reason=infeasibility_reason, assignments=assignments, leakage_check=leakage, created_at=created_at,
        )
        sha256 = manifest.content_hash(exclude={"split_manifest_sha256"})
        return manifest.model_copy(update={"split_manifest_sha256": sha256})
