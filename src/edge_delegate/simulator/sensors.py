"""Helpers for registering deterministic read-only sensors."""

from __future__ import annotations

from edge_delegate.contracts import (
    CapabilityCard,
    PrivacyClass,
    ResourceCost,
    SideEffect,
    ValueKind,
    ValueSpec,
)

from .world import SimulatedWorld


def register_state_sensor(
    world: SimulatedWorld,
    *,
    capability_id: str,
    state_key: str,
    result_kind: ValueKind,
    description: str,
    privacy_class: PrivacyClass = PrivacyClass.PUBLIC,
    latency_ms: int = 1,
) -> CapabilityCard:
    card = CapabilityCard(
        capability_id=capability_id,
        version="0.1.0",
        description=description,
        arguments={},
        result=ValueSpec(kind=result_kind),
        side_effect=SideEffect.READ,
        privacy_classes=frozenset({privacy_class}),
        cost=ResourceCost(latency_ms=latency_ms),
    )

    def read_sensor(arguments, simulated_world):
        del arguments
        return simulated_world.read(state_key)

    world.register(card, read_sensor)
    return card

