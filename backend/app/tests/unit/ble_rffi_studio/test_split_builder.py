from __future__ import annotations

import pytest

from app.modules.ble_rffi_studio.dataset import DatasetBuilder
from app.modules.ble_rffi_studio.quality import SplitBuilder

from ._helpers import make_example, make_multi_unit_multi_session_examples


@pytest.fixture
def split_builder():
    return SplitBuilder()


def _frozen_dataset(tmp_path, examples, dataset_id="DS1"):
    builder = DatasetBuilder(tmp_path / "datasets")
    draft = builder.build_draft(dataset_id=dataset_id, dataset_version="1.0.0", project_id="P1", campaign_id="C1", examples=examples, data_origin="REAL_B200", creation_policy={}, created_at="2026-07-26T00:00:00Z")
    return builder.freeze(draft)


def test_same_model_unit_identification_not_feasible_with_a_single_unit(split_builder, tmp_path):
    examples = make_multi_unit_multi_session_examples(units=1, sessions_per_unit=3)
    dataset = _frozen_dataset(tmp_path, examples)
    manifest = split_builder.build(dataset=dataset, examples=examples, scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", created_at="2026-07-26T00:00:00Z")
    assert manifest.split_status == "NOT_FEASIBLE"
    assert "physical unit" in manifest.infeasibility_reason.lower()
    assert manifest.assignments == []


def test_same_model_unit_identification_not_feasible_with_too_few_sessions(split_builder, tmp_path):
    examples = make_multi_unit_multi_session_examples(units=2, sessions_per_unit=2)
    dataset = _frozen_dataset(tmp_path, examples)
    manifest = split_builder.build(dataset=dataset, examples=examples, scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", created_at="2026-07-26T00:00:00Z")
    assert manifest.split_status == "NOT_FEASIBLE"


def test_same_model_unit_identification_is_ready_with_enough_sessions(split_builder, tmp_path):
    examples = make_multi_unit_multi_session_examples(units=2, sessions_per_unit=3, examples_per_session=4)
    dataset = _frozen_dataset(tmp_path, examples)
    manifest = split_builder.build(dataset=dataset, examples=examples, scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", created_at="2026-07-26T00:00:00Z")

    assert manifest.split_status == "READY"
    assert manifest.leakage_check.status == "PASSED"
    assert manifest.split_manifest_sha256 is not None
    splits_used = {a.split for a in manifest.assignments}
    assert splits_used == {"TRAIN", "VALIDATION", "TEST"}
    # Both units appear in all three splits -- physical_unit_id repeating
    # across splits is correct, not leakage.
    for unit in ("SYN-UNIT-00", "SYN-UNIT-01"):
        unit_splits = {a.split for a in manifest.assignments if a.physical_unit_id == unit}
        assert unit_splits == {"TRAIN", "VALIDATION", "TEST"}


def test_same_model_unit_identification_grows_validation_and_test_with_more_sessions(split_builder, tmp_path):
    # Real bug found and fixed: VALIDATION/TEST used to get exactly 1
    # session each no matter how many sessions a unit had, so 10x the real
    # captures never made the held-out evaluation any more statistically
    # robust -- it only grew TRAIN. With 10 sessions/unit and a 0.2
    # fraction, VALIDATION and TEST must each get 2 sessions (round(10*0.2)),
    # not the old fixed 1.
    examples = make_multi_unit_multi_session_examples(units=2, sessions_per_unit=10, examples_per_session=2)
    dataset = _frozen_dataset(tmp_path, examples)
    manifest = split_builder.build(dataset=dataset, examples=examples, scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", created_at="2026-07-26T00:00:00Z")
    assert manifest.split_status == "READY"
    assert manifest.leakage_check.status == "PASSED"
    for unit in ("SYN-UNIT-00", "SYN-UNIT-01"):
        sessions_by_split: dict[str, set[str]] = {"TRAIN": set(), "VALIDATION": set(), "TEST": set()}
        for a in manifest.assignments:
            if a.physical_unit_id == unit:
                sessions_by_split[a.split].add(a.session_id)
        assert len(sessions_by_split["VALIDATION"]) == 2
        assert len(sessions_by_split["TEST"]) == 2
        assert len(sessions_by_split["TRAIN"]) == 6
        # Still session-disjoint: no session shared between splits.
        assert not (sessions_by_split["TRAIN"] & sessions_by_split["VALIDATION"])
        assert not (sessions_by_split["TRAIN"] & sessions_by_split["TEST"])
        assert not (sessions_by_split["VALIDATION"] & sessions_by_split["TEST"])


def test_same_model_unit_identification_never_splits_a_session_across_two_splits(split_builder, tmp_path):
    examples = make_multi_unit_multi_session_examples(units=2, sessions_per_unit=3, examples_per_session=4)
    dataset = _frozen_dataset(tmp_path, examples)
    manifest = split_builder.build(dataset=dataset, examples=examples, scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", created_at="2026-07-26T00:00:00Z")
    session_to_splits: dict[str, set[str]] = {}
    for a in manifest.assignments:
        session_to_splits.setdefault(a.session_id, set()).add(a.split)
    assert all(len(splits) == 1 for splits in session_to_splits.values())


def test_target_vs_background_not_feasible_without_background_sessions(split_builder, tmp_path):
    examples = [
        make_example(example_index=i, physical_unit_id="TARGET-UNIT", session_id=f"S-{i}", source_iq_sha256=f"sha-{i}")
        for i in range(3)
    ]
    dataset = _frozen_dataset(tmp_path, examples)
    manifest = split_builder.build(dataset=dataset, examples=examples, scientific_task="TARGET_VS_BACKGROUND", created_at="2026-07-26T00:00:00Z")
    assert manifest.split_status == "NOT_FEASIBLE"
    assert "background" in manifest.infeasibility_reason.lower()


def test_target_vs_background_requires_declared_background_environment_captures(split_builder, tmp_path):
    """3 target sessions + 3 physical_unit_id=None sessions is not enough on
    its own -- an example with no address match is only trustworthy negative
    evidence when its OWN capture was declared BACKGROUND_ENVIRONMENT (see
    module docstring). Undeclared "no match" examples (e.g. from a
    TARGET_DEVICE capture whose address just never resolved) must never
    silently count as background."""
    examples = [
        make_example(example_index=i, physical_unit_id="TARGET-UNIT", session_id=f"TARGET-S-{i}", source_iq_sha256=f"sha-t{i}")
        for i in range(3)
    ] + [
        make_example(example_index=100 + i, physical_unit_id=None, session_id=f"BG-S-{i}", source_iq_sha256=f"sha-bg{i}", capture_purpose=None)
        for i in range(3)
    ]
    dataset = _frozen_dataset(tmp_path, examples)
    manifest = split_builder.build(dataset=dataset, examples=examples, scientific_task="TARGET_VS_BACKGROUND", created_at="2026-07-26T00:00:00Z")

    assert manifest.split_status == "NOT_FEASIBLE"
    assert "background" in manifest.infeasibility_reason.lower()


def test_target_vs_background_is_ready_and_distributes_both_classes_across_all_splits(split_builder, tmp_path):
    examples = [
        make_example(example_index=i, physical_unit_id="TARGET-UNIT", session_id=f"TARGET-S-{i}", source_iq_sha256=f"sha-t{i}", capture_purpose="TARGET_DEVICE_ON")
        for i in range(3)
    ] + [
        make_example(example_index=100 + i, physical_unit_id=None, session_id=f"BG-S-{i}", source_iq_sha256=f"sha-bg{i}", capture_purpose="BACKGROUND_TARGET_OFF")
        for i in range(3)
    ]
    dataset = _frozen_dataset(tmp_path, examples)
    manifest = split_builder.build(dataset=dataset, examples=examples, scientific_task="TARGET_VS_BACKGROUND", created_at="2026-07-26T00:00:00Z")

    assert manifest.split_status == "READY"
    assert manifest.leakage_check.status == "PASSED"
    background_assignments = [a for a in manifest.assignments if a.physical_unit_id is None]
    target_assignments = [a for a in manifest.assignments if a.physical_unit_id is not None]
    assert background_assignments and target_assignments
    # Both classes are now genuinely present in ALL three splits -- the
    # previous design kept negatives out of TRAIN entirely, which left every
    # classifier trained on a single class (a real, observed failure).
    assert {a.split for a in background_assignments} == {"TRAIN", "VALIDATION", "TEST"}
    assert {a.split for a in target_assignments} == {"TRAIN", "VALIDATION", "TEST"}
    train_labels = {"TARGET_DEVICE" if a.physical_unit_id else "BACKGROUND_ENVIRONMENT" for a in manifest.assignments if a.split == "TRAIN"}
    assert train_labels == {"TARGET_DEVICE", "BACKGROUND_ENVIRONMENT"}


def test_target_vs_background_ignores_a_no_match_example_from_a_target_device_capture_as_background(split_builder, tmp_path):
    """The exact real failure mode this fix targets: a TARGET_DEVICE-declared
    capture whose evidence never matched a registered address must never be
    silently counted as background, even if it has plenty of sessions and
    physical_unit_id=None examples."""
    examples = [
        make_example(example_index=i, physical_unit_id="TARGET-UNIT", session_id=f"TARGET-S-{i}", source_iq_sha256=f"sha-t{i}", capture_purpose="TARGET_DEVICE_ON")
        for i in range(3)
    ] + [
        # Declared TARGET_DEVICE (operator meant to capture the device on),
        # but the address never matched -- association_status NONE/CONFLICT,
        # physical_unit_id=None. NOT legitimate background evidence.
        make_example(example_index=200 + i, physical_unit_id=None, session_id=f"UNMATCHED-S-{i}", source_iq_sha256=f"sha-unm{i}", capture_purpose="TARGET_DEVICE_ON", association_status="NONE")
        for i in range(5)
    ]
    dataset = _frozen_dataset(tmp_path, examples)
    manifest = split_builder.build(dataset=dataset, examples=examples, scientific_task="TARGET_VS_BACKGROUND", created_at="2026-07-26T00:00:00Z")

    assert manifest.split_status == "NOT_FEASIBLE"
    assert "background" in manifest.infeasibility_reason.lower()


def test_unknown_device_rejection_with_only_one_known_unit_is_blocked_by_the_common_single_class_gate(split_builder, tmp_path):
    """UNKNOWN_DEVICE_REJECTION's own feasibility check only requires >=1
    known unit (unknowns are never assigned to TRAIN by design) -- with
    exactly 1 known unit, TRAIN ends up with a single label ("that one
    unit"), the same fundamental problem TARGET_VS_BACKGROUND had. The
    common _finalize gate catches this even though this task's own
    task-specific check does not."""
    known = make_multi_unit_multi_session_examples(units=1, sessions_per_unit=3, examples_per_session=4)
    unknown = [
        make_example(example_index=200 + i, physical_unit_id=None, session_id=f"UNK-S-{i}", source_iq_sha256=f"sha-unk{i}")
        for i in range(2)
    ]
    examples = known + unknown
    dataset = _frozen_dataset(tmp_path, examples)
    manifest = split_builder.build(dataset=dataset, examples=examples, scientific_task="UNKNOWN_DEVICE_REJECTION", created_at="2026-07-26T00:00:00Z")

    assert manifest.split_status == "NOT_FEASIBLE"
    assert "TRAINING_REQUIRES_AT_LEAST_TWO_CLASSES" in manifest.infeasibility_reason


def test_unknown_device_rejection_not_feasible_without_enough_unknown_sessions(split_builder, tmp_path):
    examples = make_multi_unit_multi_session_examples(units=1, sessions_per_unit=3)
    dataset = _frozen_dataset(tmp_path, examples)
    manifest = split_builder.build(dataset=dataset, examples=examples, scientific_task="UNKNOWN_DEVICE_REJECTION", created_at="2026-07-26T00:00:00Z")
    assert manifest.split_status == "NOT_FEASIBLE"


def test_unknown_device_rejection_is_ready_and_keeps_unknowns_out_of_train(split_builder, tmp_path):
    # 2 known units, not 1 -- a "known-vs-unknown" classifier needs >=2 real
    # classes in TRAIN to be meaningful (the same principle
    # TARGET_VS_BACKGROUND's redesign enforces), matching
    # write_unknown_device_rejection_fixture's own default elsewhere in this
    # test suite.
    known = make_multi_unit_multi_session_examples(units=2, sessions_per_unit=3, examples_per_session=4)
    unknown = [
        make_example(example_index=200 + i, physical_unit_id=None, session_id=f"UNK-S-{i}", source_iq_sha256=f"sha-unk{i}")
        for i in range(2)
    ]
    examples = known + unknown
    dataset = _frozen_dataset(tmp_path, examples)
    manifest = split_builder.build(dataset=dataset, examples=examples, scientific_task="UNKNOWN_DEVICE_REJECTION", created_at="2026-07-26T00:00:00Z")

    assert manifest.split_status == "READY"
    unknown_assignments = [a for a in manifest.assignments if a.physical_unit_id is None]
    assert unknown_assignments
    assert all(a.split != "TRAIN" for a in unknown_assignments)
    assert {a.split for a in unknown_assignments} <= {"VALIDATION", "TEST"}


def test_unknown_scientific_task_raises(split_builder, tmp_path):
    examples = [make_example(example_index=1, physical_unit_id="U1", session_id="S1")]
    dataset = _frozen_dataset(tmp_path, examples)
    with pytest.raises(ValueError):
        split_builder.build(dataset=dataset, examples=examples, scientific_task="NOT_A_REAL_TASK", created_at="2026-07-26T00:00:00Z")


def test_split_manifest_round_trips_through_canonical_json(split_builder, tmp_path):
    import json

    from app.modules.ble_rffi_studio.contracts import SplitManifest

    examples = make_multi_unit_multi_session_examples(units=2, sessions_per_unit=3, examples_per_session=2)
    dataset = _frozen_dataset(tmp_path, examples)
    manifest = split_builder.build(dataset=dataset, examples=examples, scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", created_at="2026-07-26T00:00:00Z")
    restored = SplitManifest.model_validate(json.loads(manifest.canonical_json()))
    assert restored == manifest
