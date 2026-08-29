"""Tests for non-executing real-model diagnostic reporting."""

from edge_delegate.contracts import PlanIR
from edge_delegate.data import generate_records
from edge_delegate.evaluation import ModelDoctor, select_controlled_records
from edge_delegate.ir import canonicalize_plan
from edge_delegate.planner import ScriptedFunctionGemmaBackend


def _function_call(plan: PlanIR) -> str:
    return (
        "<start_function_call>call:submit_plan{plan_json:<escape>"
        f"{canonicalize_plan(plan)}"
        "<escape>}<end_function_call>"
    )


def test_model_doctor_separates_operational_and_quality_results() -> None:
    records = select_controlled_records(generate_records())[:2]
    outputs = [_function_call(PlanIR.from_dict(record["expected_plan"])) for record in records]
    report = ModelDoctor(ScriptedFunctionGemmaBackend(outputs)).run(records)

    assert report["purpose"] == "integration_smoke_not_model_quality_benchmark"
    assert report["operational"]["all_generations_succeeded"] is True
    assert report["quality_smoke"]["parse_valid_rate"] == 1.0
    assert report["quality_smoke"]["exact_plan_accuracy"] == 1.0
    assert report["execution_policy"].endswith("never executed")
    assert report["cases"][0]["generation"]["raw_output"].startswith("<start_function_call>")


def test_model_doctor_preserves_and_classifies_malformed_output() -> None:
    record = select_controlled_records(generate_records())[0]
    report = ModelDoctor(ScriptedFunctionGemmaBackend(["not a function call"])).run([record])

    assert report["operational"]["generation_success_count"] == 1
    assert report["quality_smoke"]["parse_valid_rate"] == 0.0
    assert report["failure_counts"] == {"output_format": 1}
    assert report["cases"][0]["generation"]["raw_output"] == "not a function call"
