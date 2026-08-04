"""Builds TRAIN/VALIDATION/TEST splits by whole session, never by window
within a session, and never assumes 3 splits are always possible -- each
scientific_task has its own minimum-evidence rule (design correction #7).
When a task's requirement isn't met, split_status=NOT_FEASIBLE with an exact
reason, never an artificial split.

physical_unit_id repeating across splits is correct here (needed to evaluate
that class); what must never repeat is capture_id/execution_id/session_id/
candidate_id/packet_id/sample-range -- computed and checked for real via
_compute_leakage, never assumed from the construction method alone.

TARGET_VS_BACKGROUND's "background" side is real negative evidence ONLY when
it comes from an example whose OWN capture was declared
capture_purpose=BACKGROUND_TARGET_OFF or BACKGROUND_GENERAL (operator
explicitly confirmed the target was off/removed, or recorded ambient
environment with no target in question) -- never from a
TARGET_DEVICE_ON-declared capture whose evidence merely failed to match a
registered address (association_status NONE/CONFLICT), and never from
UNKNOWN_DEVICE_COLLECTION (that purpose exists only to feed
UNKNOWN_DEVICE_REJECTION, never TARGET_VS_BACKGROUND's negative class).
"No address match" is not "confirmed absent"; treating it as background
contaminates the negative class with inconclusive data (a real, observed
failure mode: two TARGET_DEVICE_ON captures with no address match were
silently counted as background sessions, driving a whole TRAIN split down to
one class).

A supervised classifier trained on a single label is never scientifically
meaningful regardless of which scientific_task asked for it -- _finalize()
enforces this as one common, task-agnostic gate before a split can ever be
marked READY, so it blocks every model type training_service.py can train
(logistic_regression, svm_rbf, random_forest, cnn1d, cnn2d) uniformly,
rather than relying on each model's own library to notice (sklearn's
LogisticRegression/SVC raise on a single class; RandomForestClassifier and
the CNN trainers do not, and will silently "succeed" with a meaningless
model otherwise).
"""
from __future__ import annotations

from ..contracts import DatasetManifest, ExampleRecord, LeakageCheckResult, SplitAssignment, SplitManifest

_SPLIT_NAMES = ("TRAIN", "VALIDATION", "TEST")
_LEAKAGE_FIELDS = ["capture_id", "execution_id", "session_id", "candidate_id", "packet_id", "sample_range"]
_MIN_SESSIONS_PER_UNIT = 3
_MIN_TARGET_SESSIONS = 3
# One background session per split (TRAIN/VALIDATION/TEST) -- was 1 total
# (background reserved for VALIDATION/TEST only), which meant TRAIN never
# saw a background example and every classifier trained on one class alone.
# Symmetric with _MIN_TARGET_SESSIONS now that both classes are genuinely
# distributed across all three splits.
_MIN_BACKGROUND_SESSIONS = 3
_MIN_UNKNOWN_SESSIONS = 2
# Fraction of a unit's sessions allocated to VALIDATION and to TEST each in
# _closed_set_classification (SAME_MODEL_UNIT_IDENTIFICATION/MULTI_DEVICE_
# CLASSIFICATION) -- see that method's docstring for why a fixed count of 1
# regardless of how many sessions exist was a real, confirmed problem.
_VAL_TEST_SESSION_FRACTION = 0.2

TARGET_DEVICE_LABEL = "TARGET_DEVICE"
BACKGROUND_ENVIRONMENT_LABEL = "BACKGROUND_ENVIRONMENT"
UNKNOWN_CLASS_LABEL = "UNKNOWN"


def train_label_for(scientific_task: str, example: ExampleRecord) -> str:
    """The label training_service.py's own y_train will actually use for this
    example -- kept in exactly one place so SplitBuilder's own train-class
    gate can never silently disagree with what training actually sees."""
    if scientific_task == "TARGET_VS_BACKGROUND":
        return TARGET_DEVICE_LABEL if example.physical_unit_id else BACKGROUND_ENVIRONMENT_LABEL
    return example.physical_unit_id or UNKNOWN_CLASS_LABEL


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

        # Real gap found and fixed here: this used to always send exactly the
        # FIRST sorted session to TRAIN, the SECOND to VALIDATION, the THIRD
        # to TEST, and every remaining session (4th onward) to TRAIN too --
        # so a unit with 30 real sessions still got a VALIDATION/TEST
        # evaluation resting on exactly one session each, identical to a unit
        # with the bare minimum of 3. More captured sessions only ever grew
        # TRAIN, never made the held-out evaluation more statistically
        # robust -- confirmed the hard way: a real identity-training run
        # collapsed to 0.0 recall on VALIDATION for classes with few
        # sessions while hitting 1.0 on TRAIN, and adding sessions elsewhere
        # in the same run did nothing to fix that because those splits
        # never grew. Now VALIDATION and TEST each get a session count
        # proportional to how many sessions this unit actually has
        # (_VAL_TEST_SESSION_FRACTION each, rounded, minimum 1), so five
        # times more data means a five-times-more-independent evaluation,
        # not just a bigger TRAIN. At the minimum feasible count (3
        # sessions) this still resolves to exactly 1/1/1, unchanged from
        # before.
        assignments: list[SplitAssignment] = []
        for unit, sessions in ready_units.items():
            session_ids = sorted(sessions.keys())
            n = len(session_ids)
            n_val = max(1, round(n * _VAL_TEST_SESSION_FRACTION))
            n_test = max(1, round(n * _VAL_TEST_SESSION_FRACTION))
            if n - n_val - n_test < 1:
                n_val = n_test = 1
            val_ids = session_ids[:n_val]
            test_ids = session_ids[n_val:n_val + n_test]
            train_ids = session_ids[n_val + n_test:]
            for split_name, split_session_ids in (("TRAIN", train_ids), ("VALIDATION", val_ids), ("TEST", test_ids)):
                for session_id in split_session_ids:
                    for example in sessions[session_id]:
                        assignments.append(SplitAssignment(example_id=example.example_id, physical_unit_id=unit, capture_id=example.capture_id, session_id=session_id, split=split_name, split_reason=policy))

        leakage = self._compute_leakage(assignments, {e.example_id: e for e in examples})
        return self._finalize(dataset, scientific_task, policy, assignments, leakage, created_at, {e.example_id: e for e in examples})

    def _target_vs_background(
        self, dataset: DatasetManifest, examples: list[ExampleRecord], created_at: str,
    ) -> SplitManifest:
        scientific_task, policy = "TARGET_VS_BACKGROUND", "target_background_session_disjoint"
        target_examples = [e for e in examples if e.physical_unit_id]
        # A background example is only trustworthy negative evidence when its
        # OWN capture was declared BACKGROUND_TARGET_OFF or BACKGROUND_GENERAL
        # (denormalized onto the example itself at evidence-build time,
        # EvidenceStage) -- an example with no physical_unit_id from a
        # TARGET_DEVICE_ON capture just means the address never matched THAT
        # session, never that the device was confirmed absent. See module
        # docstring.
        background_examples = [e for e in examples if not e.physical_unit_id and e.capture_purpose in ("BACKGROUND_TARGET_OFF", "BACKGROUND_GENERAL")]
        target_sessions = sorted({e.session_id for e in target_examples})
        background_sessions = sorted({e.session_id for e in background_examples})

        if len(target_sessions) < _MIN_TARGET_SESSIONS:
            reason = f"{scientific_task} requires >={_MIN_TARGET_SESSIONS} independent target sessions (one per split); found {len(target_sessions)}."
            return self._not_feasible(dataset, scientific_task, policy, reason, created_at)
        if len(background_sessions) < _MIN_BACKGROUND_SESSIONS:
            reason = (
                f"{scientific_task} requires >={_MIN_BACKGROUND_SESSIONS} independent BACKGROUND_ENVIRONMENT-declared "
                f"session(s) (one per split -- TRAIN/VALIDATION/TEST all need a real background example, never just "
                f"VALIDATION/TEST); found {len(background_sessions)}. Captures whose evidence simply did not match a "
                "registered address do not count -- only a capture where the operator explicitly confirmed the "
                "target was off/removed does."
            )
            return self._not_feasible(dataset, scientific_task, policy, reason, created_at)

        assignments: list[SplitAssignment] = []
        for idx, session_id in enumerate(target_sessions):
            split = _SPLIT_NAMES[idx] if idx < 3 else "TRAIN"
            for example in target_examples:
                if example.session_id == session_id:
                    assignments.append(SplitAssignment(example_id=example.example_id, physical_unit_id=example.physical_unit_id, capture_id=example.capture_id, session_id=session_id, split=split, split_reason=policy))

        # Both classes are now genuinely distributed across all three splits
        # -- a real, deliberate change from the previous "negatives never in
        # TRAIN" design, which left every classifier trained on one class
        # alone (see module docstring).
        for idx, session_id in enumerate(background_sessions):
            split = _SPLIT_NAMES[idx] if idx < 3 else "TRAIN"
            for example in background_examples:
                if example.session_id == session_id:
                    assignments.append(SplitAssignment(example_id=example.example_id, physical_unit_id=None, capture_id=example.capture_id, session_id=session_id, split=split, split_reason=f"{policy}:background_environment_declared"))

        leakage = self._compute_leakage(assignments, {e.example_id: e for e in examples})
        return self._finalize(dataset, scientific_task, policy, assignments, leakage, created_at, {e.example_id: e for e in examples})

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
        return self._finalize(dataset, scientific_task, policy, assignments, leakage, created_at, {e.example_id: e for e in examples})

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

    def _finalize(
        self, dataset: DatasetManifest, scientific_task: str, policy: str, assignments: list[SplitAssignment],
        leakage: LeakageCheckResult, created_at: str, examples_by_id: dict[str, ExampleRecord],
    ) -> SplitManifest:
        if leakage.status == "FAILED":
            split_status, infeasibility_reason = "NOT_FEASIBLE", f"Leakage check failed on field(s): {sorted(leakage.overlapping_keys.keys())}"
        else:
            # One common, task-agnostic gate: no classifier training is ever
            # scientifically meaningful with a single label in TRAIN,
            # regardless of which scientific_task asked for it or which
            # model library happens to tolerate a single class silently
            # (sklearn's LogisticRegression/SVC raise; RandomForestClassifier
            # and the CNN trainers do not -- this must not depend on that).
            train_labels = {train_label_for(scientific_task, examples_by_id[a.example_id]) for a in assignments if a.split == "TRAIN"}
            if len(train_labels) < 2:
                split_status, infeasibility_reason = "NOT_FEASIBLE", (
                    f"TRAINING_REQUIRES_AT_LEAST_TWO_CLASSES: TRAIN contains only {sorted(train_labels)}. "
                    "A model trained on a single class cannot be scientifically evaluated -- this blocks every "
                    "candidate model type uniformly, not just the ones whose library happens to raise on its own."
                )
            else:
                split_status, infeasibility_reason = "READY", None
        manifest = SplitManifest(
            dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version, scientific_task=scientific_task, policy=policy,
            split_status=split_status, infeasibility_reason=infeasibility_reason, assignments=assignments, leakage_check=leakage, created_at=created_at,
        )
        sha256 = manifest.content_hash(exclude={"split_manifest_sha256"})
        return manifest.model_copy(update={"split_manifest_sha256": sha256})
