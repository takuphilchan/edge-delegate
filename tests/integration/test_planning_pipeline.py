"""End-to-end tests for request -> plan -> validation -> simulated execution."""

import json
from pathlib import Path

from edge_delegate.cli import main
from edge_delegate.planner import StaticPlanner
from edge_delegate.runtime import Coordinator, CoordinatorStatus, StepStatus

EXAMPLE_ROOT = Path(__file__).parents[2] / "examples" / "local-display"


def test_local_plan_executes_and_resolves_prior_step_reference(
    demo_world, demo_policy, demo_request, demo_plan
) -> None:
    coordinator = Coordinator(
        planner=StaticPlanner({demo_request.request_id: demo_plan}),
        world=demo_world,
        policy=demo_policy,
    )

    result = coordinator.handle(demo_request)

    assert result.status is CoordinatorStatus.EXECUTED
    assert result.validation is not None and result.validation.valid
    assert result.execution is not None
    assert result.execution.final_output is True
    assert demo_world.read("display.last_value") == 24.5
    assert [item.capability_id for item in demo_world.invocations] == [
        "sensor.temperature.read",
        "display.value.show",
    ]


def test_retry_replays_side_effect_instead_of_invoking_it_twice(
    demo_world, demo_policy, demo_request, demo_plan
) -> None:
    coordinator = Coordinator(
        planner=StaticPlanner({demo_request.request_id: demo_plan}),
        world=demo_world,
        policy=demo_policy,
    )

    first = coordinator.handle(demo_request)
    second = coordinator.handle(demo_request)

    assert first.status is CoordinatorStatus.EXECUTED
    assert second.status is CoordinatorStatus.EXECUTED
    assert second.execution is not None
    assert second.execution.steps[1].status is StepStatus.REPLAYED
    assert [item.capability_id for item in demo_world.invocations].count("display.value.show") == 1


def test_audit_excludes_request_text_and_step_arguments(
    demo_world, demo_policy, demo_request, demo_plan
) -> None:
    coordinator = Coordinator(
        planner=StaticPlanner({demo_request.request_id: demo_plan}),
        world=demo_world,
        policy=demo_policy,
    )
    coordinator.handle(demo_request)

    serialized_details = repr([event.details for event in coordinator.audit.events])
    assert demo_request.text not in serialized_details
    assert "24.5" not in serialized_details
    assert {event.event_type for event in coordinator.audit.events} == {"validation", "execution"}


def test_cli_demo_runs_the_vertical_slice(capsys) -> None:
    assert main(["demo"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "executed"
    assert output["display_value"] == 24.5
    assert output["validation"]["valid"] is True


def test_cli_validates_external_contract_files(capsys) -> None:
    result = main(
        [
            "validate",
            "--capabilities",
            str(EXAMPLE_ROOT / "capabilities.json"),
            "--state",
            str(EXAMPLE_ROOT / "state.json"),
            "--policy",
            str(EXAMPLE_ROOT / "policy.json"),
            "--plan",
            str(EXAMPLE_ROOT / "plan.json"),
            "--now",
            "2026-01-01T12:00:00Z",
        ]
    )
    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["valid"] is True
