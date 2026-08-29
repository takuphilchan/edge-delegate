"""Plan-structure and execution-outcome metrics."""

from __future__ import annotations

from dataclasses import dataclass

from edge_delegate.contracts import PlanIR
from edge_delegate.ir import canonicalize_plan


@dataclass(frozen=True, slots=True)
class PlanComparison:
    route_correct: bool
    capability_sequence_exact: bool
    plan_exact: bool


def compare_plans(predicted: PlanIR, expected: PlanIR) -> PlanComparison:
    return PlanComparison(
        route_correct=predicted.route is expected.route,
        capability_sequence_exact=(
            tuple(step.capability_id for step in predicted.steps)
            == tuple(step.capability_id for step in expected.steps)
        ),
        plan_exact=canonicalize_plan(predicted) == canonicalize_plan(expected),
    )
