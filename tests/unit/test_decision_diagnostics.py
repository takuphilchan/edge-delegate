from dataclasses import replace

import pytest

from edge_delegate.contracts import PlanningRequest
from edge_delegate.data import build_record_world
from edge_delegate.data.tasks import generate_task_records
from edge_delegate.evaluation import EvaluationRunner
from edge_delegate.planner import PlannerContext, PlannerOutputError
from edge_delegate.planner.tasks import BoundedPlanner, TaskDecision
from edge_delegate.simulator.examples import local_display
from edge_delegate_lab.validation_audit import compare_modes, primary_finding


@pytest.fixture(scope="module")
def records():
    return generate_task_records()


@pytest.mark.parametrize("batch", [False, True])
def test_wrong_intent_blocked_by_context_is_not_scored_as_understanding(records, batch):
    record = next(r for r in records if r["record_id"] == "deny-03-02")
    calls = []

    def decide(request, context):
        calls.append("single")
        return TaskDecision("read_temperature")

    def decide_many(requests, contexts):
        calls.append("batch")
        return [TaskDecision("read_temperature") for _ in requests]

    planner = BoundedPlanner(decide, decide_batch=decide_many)
    result = EvaluationRunner(
        planner, execution_harness=build_record_world, diagnostics=True, use_batch=batch
    ).evaluate([record])
    case = result["cases"][0]
    assert case["task_success"] is True  # Legacy effect/status score retained explicitly.
    assert case["diagnostics"]["intent_correct"] is False
    assert case["diagnostics"]["invocations"] == []
    assert primary_finding(case) == "wrong_intent_masked_by_runtime"
    assert result["decision_metrics"]["correct_count"] == 0
    assert result["decision_metrics"]["assessed_count"] == 1
    assert calls == ["batch" if batch else "single"]


def test_invalid_parameters_preserve_decision_but_never_execute(records):
    record = records[0]
    planner = BoundedPlanner(lambda *_: TaskDecision("read_temperature", {"value": 987654321}))
    result = EvaluationRunner(planner, diagnostics=True).evaluate([record])
    case = result["cases"][0]
    assert not case["parse_valid"]
    assert case["diagnostics"]["decision_available"]
    assert case["diagnostics"]["intent_correct"] is False
    assert case["diagnostics"]["error_type"] == "PlannerOutputError"
    assert "987654321" not in str(case["diagnostics"])


def test_parser_failure_is_unassessed_not_a_correct_abstention(records):
    def broken(*_):
        raise PlannerOutputError("bad envelope")

    result = EvaluationRunner(BoundedPlanner(broken), diagnostics=True).evaluate([records[0]])
    assert result["decision_metrics"]["assessed_count"] == 0
    assert result["decision_metrics"]["unassessed_count"] == 1
    assert result["decision_metrics"]["accuracy"] is None


def test_observations_are_per_call_and_normal_plan_contract_is_preserved():
    world, policy = local_display()
    context = PlannerContext(world.capability_cards, world.snapshot(), policy)
    planner = BoundedPlanner(lambda request, _: TaskDecision(request.text))
    request = PlanningRequest("first", "read_temperature")
    first = planner.plan_with_diagnostics(request, context)
    second = planner.plan_with_diagnostics(
        replace(request, request_id="second", text="deny"), context
    )
    assert first.decision == {"task": "read_temperature", "parameters": {}}
    assert second.decision["task"] == "deny"
    assert planner.plan(request, context) == first.plan
    assert planner.plan_many([request], [context]) == [first.plan]
    first.decision["parameters"]["value"] = 99
    assert not planner.plan_with_diagnostics(request, context).decision["parameters"]


def test_legacy_evaluation_shape_and_metrics_do_not_change(records):
    planner = BoundedPlanner(lambda *_: TaskDecision("read_temperature"))
    plain = EvaluationRunner(planner, execution_harness=build_record_world).evaluate(records[:1])
    detailed = EvaluationRunner(
        planner, execution_harness=build_record_world, diagnostics=True
    ).evaluate(records[:1])
    assert "decision_metrics" not in plain
    assert "diagnostics" not in plain["cases"][0]
    assert plain["metrics"] == detailed["metrics"]
    assert detailed["decision_metrics"]["correct_count"] == 1


def test_mode_comparison_exposes_intent_regression_with_identical_outcomes():
    def report(correct):
        return {
            "dataset_sha256": "same",
            "cases": [
                {
                    "record_id": "one",
                    "task_success": True,
                    "diagnostics": {"intent_correct": correct},
                }
            ],
        }

    comparison = compare_modes(report(True), report(False))
    assert comparison["single_regressions"] == []
    assert comparison["checked_intent_regressions"] == ["one"]
