"""explain_feasibility()'s next_steps and recommend_scientific_task() exist
because an operator with no RF-fingerprinting background cannot infer "add 3
more target sessions" from a bare have/need number dump, and has no way to
know which of the three scientific tasks even fits their current data
without checking each one by hand -- this is exactly the real confusion
reported in session (one physical unit + environment captures, but the
default task, SAME_MODEL_UNIT_IDENTIFICATION, needs two units of the same
model and can never become feasible with only one).
"""
from __future__ import annotations

from app.modules.ble_rffi_studio.quality.feasibility_explainer import explain_feasibility, recommend_scientific_task

from ._helpers import make_example


def _one_unit_plus_environment_examples() -> list:
    """Exactly the real scenario reported: one physical unit (Shelly, one
    isolation-declared session) plus three environment-only sessions."""
    examples = []
    counter = 0
    for session_index in range(3):
        session_id = f"ENV-SESSION-{session_index:02d}"
        examples.append(make_example(example_index=counter, physical_unit_id=None, session_id=session_id))
        counter += 1
    examples.append(make_example(example_index=counter, physical_unit_id="SHELLY-PLUG-01", session_id="SHELLY-SESSION-00"))
    return examples


def test_same_model_unit_identification_next_steps_names_the_missing_unit_count():
    examples = _one_unit_plus_environment_examples()
    result = explain_feasibility(examples, "SAME_MODEL_UNIT_IDENTIFICATION")
    assert result["feasible"] is False
    assert any("1 unidad" in step and "mismo modelo" in step for step in result["next_steps"])


def test_target_vs_background_next_steps_names_missing_target_sessions():
    examples = _one_unit_plus_environment_examples()
    result = explain_feasibility(examples, "TARGET_VS_BACKGROUND")
    assert result["feasible"] is False
    # 1 target session so far, needs 3 -- next_steps must say exactly 2 more.
    assert any("2 sesion" in step and "objetivo" in step for step in result["next_steps"])


def test_feasible_task_reports_no_next_steps():
    examples = _one_unit_plus_environment_examples()
    # Pad up to 3 independent target sessions and >=1 background session --
    # matches TARGET_VS_BACKGROUND's real minimums.
    examples += [make_example(example_index=100 + i, physical_unit_id="SHELLY-PLUG-01", session_id=f"SHELLY-SESSION-{i:02d}") for i in range(1, 3)]
    result = explain_feasibility(examples, "TARGET_VS_BACKGROUND")
    assert result["feasible"] is True
    assert result["next_steps"] == []


def test_recommend_scientific_task_prefers_target_vs_background_for_a_single_unit():
    """The exact real confusion this exists to prevent: with only one
    physical unit registered, SAME_MODEL_UNIT_IDENTIFICATION can never be
    feasible (it structurally needs two units of the same model) --
    TARGET_VS_BACKGROUND is the task that actually fits this data."""
    examples = _one_unit_plus_environment_examples()
    recommendation = recommend_scientific_task(examples)
    assert recommendation["recommended_task"] == "TARGET_VS_BACKGROUND"
    assert len(recommendation["candidates"]) == 3
    same_model = next(c for c in recommendation["candidates"] if c["scientific_task"] == "SAME_MODEL_UNIT_IDENTIFICATION")
    assert same_model["feasible"] is False


def test_recommend_scientific_task_prefers_an_already_feasible_task_over_a_partially_ready_one():
    examples = _one_unit_plus_environment_examples()
    examples += [make_example(example_index=100 + i, physical_unit_id="SHELLY-PLUG-01", session_id=f"SHELLY-SESSION-{i:02d}") for i in range(1, 3)]
    recommendation = recommend_scientific_task(examples)
    assert recommendation["recommended_task"] == "TARGET_VS_BACKGROUND"
    recommended_candidate = next(c for c in recommendation["candidates"] if c["scientific_task"] == "TARGET_VS_BACKGROUND")
    assert recommended_candidate["feasible"] is True
    assert "suficientes datos" in recommendation["reason"]


def test_recommend_scientific_task_with_no_data_at_all_still_returns_a_best_guess():
    recommendation = recommend_scientific_task([])
    assert recommendation["recommended_task"] in {"TARGET_VS_BACKGROUND", "SAME_MODEL_UNIT_IDENTIFICATION", "UNKNOWN_DEVICE_REJECTION"}
    assert len(recommendation["candidates"]) == 3
    assert all(c["feasible"] is False for c in recommendation["candidates"])
