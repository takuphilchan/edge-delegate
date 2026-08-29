"""Helpers for registering deterministic simulated writes and actuators."""

from __future__ import annotations

from edge_delegate.contracts import (
    CapabilityCard,
    ResourceCost,
    SideEffect,
    ValueKind,
    ValueSpec,
)

from .world import SimulatedWorld


def register_state_writer(
    world: SimulatedWorld,
    *,
    capability_id: str,
    state_key: str,
    value_kind: ValueKind,
    description: str,
    permission: str,
    physical: bool = False,
    approval_required: bool = False,
    latency_ms: int = 1,
) -> CapabilityCard:
    card = CapabilityCard(
        capability_id=capability_id,
        version="0.1.0",
        description=description,
        arguments={"value": ValueSpec(kind=value_kind)},
        result=ValueSpec(kind=ValueKind.BOOLEAN),
        side_effect=SideEffect.PHYSICAL if physical else SideEffect.WRITE,
        permissions=frozenset({permission}),
        approval_required=approval_required,
        cost=ResourceCost(latency_ms=latency_ms),
    )

    def write_value(arguments, simulated_world):
        simulated_world.write(state_key, arguments["value"])
        return True

    world.register(card, write_value)
    return card

