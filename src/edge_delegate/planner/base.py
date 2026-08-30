"""Model-independent planner protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from edge_delegate.contracts import CapabilityCard, DeviceState, PlanIR, PlanningRequest, Policy


class PlannerError(RuntimeError):
    """Raised when a planner cannot produce a candidate plan."""


class PlannerOutputError(PlannerError):
    """Raised when a planner backend emits an invalid typed proposal."""


@dataclass(frozen=True, slots=True)
class PlannerContext:
    capabilities: tuple[CapabilityCard, ...]
    state: DeviceState
    policy: Policy


@runtime_checkable
class Planner(Protocol):
    def plan(self, request: PlanningRequest, context: PlannerContext) -> PlanIR:
        """Produce a candidate plan; deterministic validation happens afterward."""
        ...
