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


def test_target_vs_background_is_ready_and_keeps_negatives_out_of_train(split_builder, tmp_path):
    examples = [
        make_example(example_index=i, physical_unit_id="TARGET-UNIT", session_id=f"TARGET-S-{i}", source_iq_sha256=f"sha-t{i}")
        for i in range(3)
    ] + [
        make_example(example_index=100 + i, physical_unit_id=None, session_id=f"BG-S-{i}", source_iq_sha256=f"sha-bg{i}")
        for i in range(2)
    ]
    dataset = _frozen_dataset(tmp_path, examples)
    manifest = split_builder.build(dataset=dataset, examples=examples, scientific_task="TARGET_VS_BACKGROUND", created_at="2026-07-26T00:00:00Z")

    assert manifest.split_status == "READY"
    assert manifest.leakage_check.status == "PASSED"
    background_assignments = [a for a in manifest.assignments if a.physical_unit_id is None]
    assert background_assignments
    assert all(a.split != "TRAIN" for a in background_assignments)


def test_unknown_device_rejection_not_feasible_without_enough_unknown_sessions(split_builder, tmp_path):
    examples = make_multi_unit_multi_session_examples(units=1, sessions_per_unit=3)
    dataset = _frozen_dataset(tmp_path, examples)
    manifest = split_builder.build(dataset=dataset, examples=examples, scientific_task="UNKNOWN_DEVICE_REJECTION", created_at="2026-07-26T00:00:00Z")
    assert manifest.split_status == "NOT_FEASIBLE"


def test_unknown_device_rejection_is_ready_and_keeps_unknowns_out_of_train(split_builder, tmp_path):
    known = make_multi_unit_multi_session_examples(units=1, sessions_per_unit=3, examples_per_session=4)
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
