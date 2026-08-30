"""Tests for non-executing real-model diagnostic reporting."""

from edge_delegate.contracts import PlanIR
from edge_delegate.data import generate_records
from edge_delegate.evaluation import ModelDoctor, select_controlled_records
from edge_delegate.ir import canonicalize_plan
from edge_delegate.model_plugins.functiongemma import FunctionGemmaDiagnosticSession
from edge_delegate.planner import FunctionGemmaPlanner, ScriptedFunctionGemmaBackend, StaticPlanner


def _function_call(plan: PlanIR) -> str:
    return (
        "<start_function_call>call:submit_plan{plan_json:<escape>"
        f"{canonicalize_plan(plan)}"
        "<escape>}<end_function_call>"
    )


def _doctor(outputs: list[str]) -> ModelDoctor:
    backend = ScriptedFunctionGemmaBackend(outputs)
    return ModelDoctor(
        FunctionGemmaDiagnosticSession(
            backend=backend,
            planner=FunctionGemmaPlanner(backend),
            retrieval_limit=8,
        )
    )


def test_model_doctor_separates_operational_and_quality_results() -> None:
    records = select_controlled_records(generate_records())[:2]
    outputs = [_function_call(PlanIR.from_dict(record["expected_plan"])) for record in records]
    report = _doctor(outputs).run(records)

    assert report["purpose"] == "integration_smoke_not_model_quality_benchmark"
    assert report["operational"]["all_generations_succeeded"] is True
    assert report["quality_smoke"]["parse_valid_rate"] == 1.0
    assert report["quality_smoke"]["exact_plan_accuracy"] == 1.0
    assert report["execution_policy"].endswith("never executed")
    assert report["cases"][0]["generation"]["raw_output"].startswith("<start_function_call>")


def test_model_doctor_preserves_and_classifies_malformed_output() -> None:
    record = select_controlled_records(generate_records())[0]
    report = _doctor(["not a function call"]).run([record])

    assert report["operational"]["generation_success_count"] == 1
    assert report["quality_smoke"]["parse_valid_rate"] == 0.0
    assert report["failure_counts"] == {"output_format": 1}
    assert report["cases"][0]["generation"]["raw_output"] == "not a function call"


def test_model_doctor_accepts_a_model_neutral_diagnostic_session() -> None:
    record = select_controlled_records(generate_records())[0]
    expected = PlanIR.from_dict(record["expected_plan"])

    class Session:
        def __init__(self):
            self.planner = StaticPlanner({str(record["record_id"]): expected})
            self.model_info = {"model_id": "generic-test-model"}

        def selected_capability_ids(self, request, context):
            del request
            return tuple(card.capability_id for card in context.capabilities)

        def last_generation(self, *, include_raw_output):
            result = {
                "latency_ms": 1.0,
                "peak_gpu_memory_bytes": None,
            }
            if include_raw_output:
                result["raw_output"] = "typed-plan"
            return result

        def classify_error(self, error):
            del error
            return "generic_error"

    report = ModelDoctor(Session()).run([record])

    assert report["model"] == {"model_id": "generic-test-model"}
    assert report["quality_smoke"]["exact_plan_accuracy"] == 1.0
