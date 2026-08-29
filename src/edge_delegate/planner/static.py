"""Deterministic planner used for integration tests and embedded host wiring."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from edge_delegate.contracts import PlanIR, PlanningRequest

from .base import Planner, PlannerContext


@dataclass(slots=True)
class StaticPlanner(Planner):
    """Return reviewed plans without loading a model."""

    plans: Mapping[str, PlanIR] | Callable[[PlanningRequest, PlannerContext], PlanIR]

    def plan(self, request: PlanningRequest, context: PlannerContext) -> PlanIR:
        if callable(self.plans):
            return self.plans(request, context)
        try:
            return self.plans[request.request_id]
        except KeyError as exc:
            raise LookupError(f"no static plan for request {request.request_id!r}") from exc

