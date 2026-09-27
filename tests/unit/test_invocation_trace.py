from edge_delegate.contracts import PlanningRequest
from edge_delegate.ir import validate_plan
from edge_delegate.planner import PlannerContext
from edge_delegate.planner.tasks import TaskDecision, reference_catalog
from edge_delegate.runtime import Executor
from edge_delegate.simulator.examples import local_display


def prepared():
    world, policy = local_display()
    state = world.snapshot()
    plan = reference_catalog().compile(
        TaskDecision("show_temperature"),
        PlanningRequest("trace", "Show temperature"),
        PlannerContext(world.capability_cards, state, policy),
    )
    validated = validate_plan(plan, world.capability_cards, state, policy, now=world.clock.now())
    return world, policy, validated


def test_invocation_observer_excludes_replayed_steps():
    world, policy, plan = prepared()
    observed = []
    executor = Executor(on_invoke=observed.append)
    assert executor.execute(plan, world, policy).status == "succeeded"
    assert observed == ["sensor.temperature.read", "display.value.show"]
    observed.clear()
    assert executor.execute(plan, world, policy).status == "succeeded"
    assert observed == []


def test_invocation_observer_includes_failed_attempt_but_not_dependent_step(monkeypatch):
    world, policy, plan = prepared()
    observed = []

    def fail(*_):
        raise RuntimeError("transport failed")

    monkeypatch.setattr(world, "invoke", fail)
    result = Executor(on_invoke=observed.append).execute(plan, world, policy)
    assert result.status == "failed"
    assert observed == ["sensor.temperature.read"]
