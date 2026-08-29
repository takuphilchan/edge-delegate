"""Model-independent planner protocol."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from edge_delegate.contracts import CapabilityCard, DeviceState, PlanIR, PlanningRequest, Policy

type PlannerOutput = PlanIR | str | bytes | bytearray | Mapping[str, object]


class PlannerError(RuntimeError):
    """Raised when a planner cannot produce a candidate plan."""


@dataclass(frozen=True, slots=True)
class PlannerContext:
    capabilities: tuple[CapabilityCard, ...]
    state: DeviceState
    policy: Policy


@runtime_checkable
class Planner(Protocol):
    def plan(self, request: PlanningRequest, context: PlannerContext) -> PlannerOutput:
        """Produce a candidate plan; deterministic validation happens afterward."""
        ...
