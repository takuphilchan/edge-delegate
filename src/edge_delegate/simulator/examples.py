"""Small explicit device fixtures, shared by the runtime demo and model lab."""

from datetime import UTC, datetime

from edge_delegate.contracts import ExecutionBudget, Policy, ValueKind

from .actuators import register_state_writer
from .clock import ManualClock
from .sensors import register_state_sensor
from .world import SimulatedWorld


def local_display(*, clock=None) -> tuple[SimulatedWorld, Policy]:
    """A fresh in-memory temperature sensor and display with a local-only policy."""
    world = SimulatedWorld(
        values={"environment.temperature_c": 24.5, "display.last_value": None},
        available_memory_bytes=128 * 1024 * 1024,
        clock=ManualClock(datetime.now(UTC)) if clock is None else clock,
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
    policy = Policy(
        policy_id="demo-local-only",
        granted_permissions=frozenset({"display.write"}),
        budget=ExecutionBudget(max_steps=4),
    )
    return world, policy
