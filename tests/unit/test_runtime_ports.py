"""Runtime boundary and bound-execution authorization tests."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from edge_delegate.contracts import CapabilityCard, DeviceState, Policy
from edge_delegate.contracts.state import JsonValue
from edge_delegate.ir import ValidatedPlan, check_plan, validate_plan
from edge_delegate.planner import StaticPlanner
from edge_delegate.runtime import Coordinator, CoordinatorStatus, Executor


class DelegatingDevice:
    """A non-simulator type implementing the runtime device port."""

    def __init__(self, delegate) -> None:
        self._delegate = delegate

    @property
    def clock(self):
        return self._delegate.clock

    @property
    def capability_cards(self) -> tuple[CapabilityCard, ...]:
        return self._delegate.capability_cards

    def snapshot(self) -> DeviceState:
        return self._delegate.snapshot()

    def invoke(self, capability_id: str, arguments: Mapping[str, JsonValue]) -> JsonValue:
        return self._delegate.invoke(capability_id, arguments)


def test_runtime_accepts_a_device_port_not_a_simulator_type(
    demo_world, demo_policy, demo_request, demo_plan
) -> None:
    device = DelegatingDevice(demo_world)
    result = Coordinator(
        planner=StaticPlanner({demo_request.request_id: demo_plan}),
        world=device,
        policy=demo_policy,
    ).handle(demo_request)

    assert result.status is CoordinatorStatus.EXECUTED
    assert demo_world.read("display.last_value") == 24.5


def test_validated_plan_cannot_be_constructed_from_an_unbound_report(
    demo_world, demo_policy, demo_plan
) -> None:
    report = check_plan(
        demo_plan,
        demo_world.capability_cards,
        demo_world.snapshot(),
        demo_policy,
        now=demo_world.clock.now(),
    )

    with pytest.raises(TypeError, match="validate_plan"):
        ValidatedPlan(plan=demo_plan, report=report)


def test_executor_rejects_policy_mismatch_before_device_invocation(
    demo_world, demo_policy, demo_plan
) -> None:
    validated = validate_plan(
        demo_plan,
        demo_world.capability_cards,
        demo_world.snapshot(),
        demo_policy,
        now=demo_world.clock.now(),
    )
    changed_policy = Policy(
        policy_id="changed-policy",
        denied_capabilities=frozenset({"display.value.show"}),
    )

    result = Executor().execute(validated, demo_world, changed_policy)

    assert result.status.value == "failed"
    assert result.error == "execution authorization does not match the active policy"
    assert demo_world.invocations == ()
