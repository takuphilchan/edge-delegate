"""A model-shaped response crosses the real parser, coordinator, executor, and simulator."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from edge_delegate.contracts import PlanIR, PlanStep, Route
from edge_delegate.ir import canonicalize_plan
from edge_delegate.planner import FunctionGemmaPlanner, ScriptedFunctionGemmaBackend, StaticPlanner
from edge_delegate_lab.cli import main
from edge_delegate_lab.presentation import render_simulation
from edge_delegate_lab.simulation import run_simulation


def _planner(plan):
    output = (
        "<start_function_call>call:submit_plan{plan_json:<escape>"
        + canonicalize_plan(plan)
        + "<escape>}<end_function_call>"
    )
    return FunctionGemmaPlanner(ScriptedFunctionGemmaBackend([output]))


def test_model_response_causes_observable_simulated_outcome(demo_plan, demo_request):
    result = run_simulation(_planner(demo_plan), demo_request)
    assert result["status"] == "executed"
    assert result["state_before"]["display.last_value"] is None
    assert result["state_after"]["display.last_value"] == 24.5
    assert result["invocation_count"] == 2
    assert result["external_call_attempted"] is False
    assert "SIMULATOR" in render_simulation(result)


@pytest.mark.parametrize("failure", ["unknown_capability", "wrong_request", "malformed_output"])
def test_invalid_model_proposals_leave_device_unchanged(demo_plan, demo_request, failure):
    if failure == "unknown_capability":
        plan = replace(demo_plan, steps=(PlanStep(step_id="bad", capability_id="device.unknown"),))
        planner = _planner(plan)
    elif failure == "wrong_request":
        planner = _planner(replace(demo_plan, request_id="another-request"))
    else:
        planner = FunctionGemmaPlanner(ScriptedFunctionGemmaBackend(["not a tool call"]))
    result = run_simulation(planner, demo_request)
    assert result["status"] == "invalid_plan"
    assert result["state_after"] == result["state_before"]
    assert result["invocation_count"] == 0


def test_simulation_does_not_mistake_execution_for_intent_correctness(demo_request):
    wrong_but_permitted = PlanIR(
        request_id=demo_request.request_id,
        route=Route.LOCAL,
        steps=(
            PlanStep(
                step_id="show_wrong_value",
                capability_id="display.value.show",
                arguments={"value": 999},
                idempotency_key="wrong-value",
            ),
        ),
    )
    result = run_simulation(_planner(wrong_but_permitted), demo_request)
    assert result["status"] == "executed"
    assert result["state_after"]["display.last_value"] == 999
    assert result["intent_correctness"] == "not_evaluated"


def test_simulations_use_fresh_worlds(demo_plan, demo_request):
    planner = StaticPlanner({demo_request.request_id: demo_plan})
    first = run_simulation(planner, demo_request)
    second = run_simulation(planner, demo_request)
    assert first["state_before"] == second["state_before"]
    assert second["execution"]["steps"][-1]["status"] == "succeeded"


def test_simulation_cli_uses_selected_plugin_and_real_runtime(demo_plan, monkeypatch, capsys):
    seen = []

    def create_planner(*, artifact_path, settings):
        seen.append((artifact_path, settings))
        return _planner(replace(demo_plan, request_id="simulation-query"))

    class Registry:
        def get(self, plugin_id):
            assert plugin_id == "test-plugin"
            return SimpleNamespace(create_planner=create_planner)

    monkeypatch.setattr("edge_delegate_lab.cli.available_model_plugins", Registry)
    assert (
        main(
            [
                "simulate",
                "--plugin",
                "test-plugin",
                "--adapter",
                "test-adapter",
                "--text",
                "Show temperature",
                "--format",
                "json",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["state_after"]["display.last_value"] == 24.5
    assert seen == [("test-adapter", {})]


def test_simulation_cli_reports_non_execution_with_nonzero_exit(monkeypatch, capsys):
    denied = PlanIR(
        request_id="simulation-query", route=Route.DENY, reason_codes=("unsupported_request",)
    )
    plugin = SimpleNamespace(create_planner=lambda **kwargs: _planner(denied))
    monkeypatch.setattr(
        "edge_delegate_lab.cli.available_model_plugins",
        lambda: SimpleNamespace(get=lambda _: plugin),
    )
    assert main(["simulate", "--text", "request", "--format", "json"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "denied"


def test_simulation_rejects_invalid_input_before_model_load(monkeypatch):
    def no_plugins():
        pytest.fail("invalid request must be rejected before model load")

    monkeypatch.setattr("edge_delegate_lab.cli.available_model_plugins", no_plugins)
    assert main(["simulate", "--text", "x" * 8001]) == 1


@pytest.mark.parametrize("route", [Route.EXTERNAL, Route.HYBRID])
def test_local_only_simulator_rejects_external_work_before_any_invocation(
    demo_plan, demo_request, route
):
    plan = replace(demo_plan, route=route, steps=demo_plan.steps if route is Route.HYBRID else ())
    result = run_simulation(_planner(plan), demo_request)
    assert result["status"] == "invalid_plan"
    assert result["external_call_attempted"] is False
    assert result["invocation_count"] == 0
    assert result["state_before"] == result["state_after"]
