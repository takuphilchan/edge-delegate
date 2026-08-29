"""Shared deterministic fixtures for the first vertical slice."""

from datetime import UTC, datetime

import pytest

from edge_delegate.contracts import (
    ExecutionBudget,
    PlanIR,
    PlanningRequest,
    PlanStep,
    Policy,
    Route,
    StepReference,
    ValueKind,
)
from edge_delegate.simulator import ManualClock, SimulatedWorld
from edge_delegate.simulator.actuators import register_state_writer
from edge_delegate.simulator.sensors import register_state_sensor

FIXED_NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def demo_world() -> SimulatedWorld:
    world = SimulatedWorld(
        values={"environment.temperature_c": 24.5, "display.last_value": None},
        available_memory_bytes=128 * 1024 * 1024,
        clock=ManualClock(FIXED_NOW),
    )
    register_state_sensor(
        world,
        capability_id="sensor.temperature.read",
        state_key="environment.temperature_c",
        result_kind=ValueKind.NUMBER,
        description="Read the current ambient temperature in Celsius.",
    )
    register_state_writer(
        world,
        capability_id="display.value.show",
        state_key="display.last_value",
        value_kind=ValueKind.NUMBER,
        description="Show a numeric value on the local display.",
        permission="display.write",
    )
    return world


@pytest.fixture
def demo_policy() -> Policy:
    return Policy(
        policy_id="test-policy",
        granted_permissions=frozenset({"display.write"}),
        budget=ExecutionBudget(
            max_steps=4,
            max_step_timeout_ms=1_000,
            max_total_latency_ms=5_000,
            max_total_energy_mj=100,
        ),
    )


@pytest.fixture
def demo_request() -> PlanningRequest:
    return PlanningRequest(
        request_id="req-display-temperature",
        text="Show the current temperature on the local display.",
    )


@pytest.fixture
def demo_plan(demo_request: PlanningRequest) -> PlanIR:
    return PlanIR(
        request_id=demo_request.request_id,
        route=Route.LOCAL,
        confidence=0.93,
        steps=(
            PlanStep(step_id="read_temperature", capability_id="sensor.temperature.read"),
            PlanStep(
                step_id="show_temperature",
                capability_id="display.value.show",
                arguments={"value": StepReference("read_temperature")},
                idempotency_key="show-temperature-v1",
            ),
        ),
    )
