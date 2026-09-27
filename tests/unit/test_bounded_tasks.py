from dataclasses import replace

import pytest

from edge_delegate.contracts import PlanningRequest, Policy, Route, StepReference
from edge_delegate.planner import PlannerContext, PlannerOutputError
from edge_delegate.planner.tasks import TaskCatalog, TaskDecision, TaskDefinition, reference_catalog
from edge_delegate.simulator.examples import local_display


def test_task_compiler_binds_and_constructs_dependencies():
    world, policy = local_display()
    context = PlannerContext(world.capability_cards, world.snapshot(), policy)
    request = PlanningRequest("example", "Show temperature")
    plan = reference_catalog().compile(TaskDecision("show_temperature"), request, context)
    assert plan.request_id == "example"
    assert plan.steps[1].arguments["value"] == StepReference("read_temperature")
    assert all(step.timeout_ms == 500 and step.idempotency_key for step in plan.steps)
    denied = reference_catalog().compile(
        TaskDecision("show_temperature"), request, replace(context, policy=Policy("no-write"))
    )
    assert denied.route is Route.DENY


@pytest.mark.parametrize(
    "decision",
    [
        TaskDecision("shell"),
        TaskDecision("display_number", {"value": True}),
        TaskDecision("read_temperature", {"value": 4}),
        TaskDecision("deny", {"shell": "x"}),
    ],
)
def test_tasks_fail_closed(decision):
    world, policy = local_display()
    with pytest.raises((PlannerOutputError, ValueError)):
        reference_catalog().compile(
            decision,
            PlanningRequest("x", "request"),
            PlannerContext(world.capability_cards, world.snapshot(), policy),
        )


def test_catalog_metadata_is_validated_and_builders_are_code():
    with pytest.raises(ValueError):
        TaskCatalog([], version="")
    for definition in (
        {"task_id": "custom", "build": "import arbitrary"},
        TaskDefinition("", "Missing identifier", lambda _: ()),
        TaskDefinition("custom", "", lambda _: ()),
        TaskDefinition("custom", "Not executable", "module:run"),
        TaskDefinition("deny", "Reserved", lambda _: ()),
    ):
        with pytest.raises(ValueError):
            TaskCatalog([definition])
