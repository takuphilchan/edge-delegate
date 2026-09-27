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


@dataclass(frozen=True, slots=True)
class PlanningObservation:
    """Optional per-call evidence, never authority to execute a device action.

    decision is the plugin's checked decision before deterministic plan compilation,
    not necessarily the raw model output. No shared last-decision state is used.
    """

    plan: PlanIR | None = None
    decision: dict[str, object] | None = None
    error: Exception | None = None

    def unwrap(self) -> PlanIR:
        if self.error is not None:
            raise self.error
        if not isinstance(self.plan, PlanIR):
            raise PlannerOutputError("observation contains no typed plan")
        return self.plan


@runtime_checkable
class Planner(Protocol):
    def plan(self, request: PlanningRequest, context: PlannerContext) -> PlanIR:
        """Produce a candidate plan; deterministic validation happens afterward."""
        ...
