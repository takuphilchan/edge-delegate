from dataclasses import replace

from edge_delegate.contracts import PlanIR, PlanStep
from edge_delegate.data import build_record_world, generate_records
from edge_delegate.evaluation import EvaluationRunner
from edge_delegate.planner import StaticPlanner


def test_wrong_but_permitted_value_does_not_get_task_credit():
    record = generate_records()[0]
    gold = PlanIR.from_dict(record["expected_plan"])
    wrong = replace(
        gold,
        steps=(PlanStep("wrong", "display.value.show", {"value": 999}, idempotency_key="wrong"),),
    )
    report = EvaluationRunner(
        StaticPlanner({gold.request_id: wrong}), execution_harness=build_record_world
    ).evaluate([record])
    assert report["metrics"]["status_accuracy"] == 1
    assert report["metrics"]["task_success_rate"] == 0
    assert report["metrics"]["wrong_but_permitted_count"] == 1


def test_gold_task_effects_are_verified():
    records = generate_records()
    planner = StaticPlanner({r["record_id"]: PlanIR.from_dict(r["expected_plan"]) for r in records})
    report = EvaluationRunner(planner, execution_harness=build_record_world).evaluate(records)
    assert report["metrics"]["task_success_rate"] == 1
