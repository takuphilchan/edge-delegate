"""Runtime boundary and bound-execution authorization tests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

import pytest

from edge_delegate.contracts import CapabilityCard, DeviceState, Policy, ValueKind, ValueSpec
from edge_delegate.contracts.state import JsonValue
from edge_delegate.ir import ValidatedPlan, check_plan, validate_plan
from edge_delegate.planner import StaticPlanner
from edge_delegate.runtime import Coordinator, CoordinatorStatus, Executor
from edge_delegate.runtime.ports import IdempotencyEntry


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


class UncheckedDevice(DelegatingDevice):
    """Real-adapter stand-in: deliberately performs no simulator validation."""

    def __init__(self, delegate, *, temperature=24.5, display_result=True, cards=None):
        super().__init__(delegate)
        self.temperature = temperature
        self.display_result = display_result
        self.cards = delegate.capability_cards if cards is None else cards
        self.calls = []

    @property
    def capability_cards(self):
        return self.cards

    def invoke(self, capability_id, arguments):
        self.calls.append((capability_id, arguments))
        return (
            self.temperature if capability_id == "sensor.temperature.read" else self.display_result
        )


def _validated(device, policy, plan):
    return validate_plan(
        plan, device.capability_cards, device.snapshot(), policy, now=device.clock.now()
    )


@pytest.mark.parametrize("value", ["INVALID-SENSOR-VALUE", float("nan"), float("inf"), object()])
def test_executor_rejects_untrusted_device_output_before_next_step(
    demo_world, demo_policy, demo_plan, value
):
    device = UncheckedDevice(demo_world, temperature=value)
    result = Executor().execute(_validated(device, demo_policy, demo_plan), device, demo_policy)

    assert result.status.value == "failed"
    assert len(device.calls) == 1
    assert result.steps[0].status.value == "failed"
    assert result.final_output is None


@pytest.mark.parametrize(
    "spec", [ValueSpec(ValueKind.NUMBER, maximum=20), ValueSpec(ValueKind.NUMBER, enum=(10, 20))]
)
def test_executor_checks_resolved_reference_against_destination_constraints(
    demo_world, demo_policy, demo_plan, spec
):
    cards = tuple(
        replace(card, arguments={"value": spec})
        if card.capability_id == "display.value.show"
        else card
        for card in demo_world.capability_cards
    )
    device = UncheckedDevice(demo_world, cards=cards)
    result = Executor().execute(_validated(device, demo_policy, demo_plan), device, demo_policy)

    assert result.status.value == "failed"
    assert "resolved argument" in result.error
    assert len(device.calls) == 1


def test_executor_does_not_cache_invalid_results(demo_world, demo_policy, demo_plan):
    device = UncheckedDevice(demo_world, display_result="wrong type")
    executor = Executor()
    validated = _validated(device, demo_policy, demo_plan)
    assert executor.execute(validated, device, demo_policy).status.value == "failed"
    device.display_result = True
    assert executor.execute(validated, device, demo_policy).status.value == "succeeded"
    assert executor.execute(validated, device, demo_policy).steps[-1].status.value == "replayed"
    assert sum(call[0] == "display.value.show" for call in device.calls) == 2


def test_executor_validates_results_from_idempotency_repository(demo_world, demo_policy, demo_plan):
    class CorruptCache:
        def lookup(self, key, fingerprint):
            return IdempotencyEntry(fingerprint=fingerprint, result="corrupt cached value")

        def record(self, *args):
            pytest.fail("invalid cached value must not be recorded")

    device = UncheckedDevice(demo_world)
    result = Executor(idempotency=CorruptCache()).execute(
        _validated(device, demo_policy, demo_plan), device, demo_policy
    )
    assert result.status.value == "failed"
    assert "device result violates" in result.error
    assert len(device.calls) == 1


def test_executor_rejects_undeclared_output(demo_world, demo_policy, demo_plan):
    cards = tuple(
        replace(card, result=None) if card.capability_id == "display.value.show" else card
        for card in demo_world.capability_cards
    )
    device = UncheckedDevice(demo_world, cards=cards)
    result = Executor().execute(_validated(device, demo_policy, demo_plan), device, demo_policy)
    assert result.status.value == "failed"
    assert "device result violates" in result.error
