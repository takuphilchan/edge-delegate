"""Fail-closed coordinator for planning, validation, routing, and execution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from edge_delegate.contracts import PlanIR, PlanningRequest, Policy, Route
from edge_delegate.ir import (
    PlanParseError,
    StaticCheckReport,
    check_plan,
    parse_plan,
    plan_fingerprint,
)
from edge_delegate.planner import Planner, PlannerContext
from edge_delegate.simulator import SimulatedWorld

from .audit import InMemoryAuditLog
from .executor import ExecutionResult, ExecutionStatus, Executor


class CoordinatorStatus(StrEnum):
    EXECUTED = "executed"
    CLARIFICATION_REQUIRED = "clarification_required"
    DENIED = "denied"
    DEFERRED = "deferred"
    EXTERNAL_REQUIRED = "external_required"
    INVALID_PLAN = "invalid_plan"
    PLANNER_FAILED = "planner_failed"
    EXECUTION_FAILED = "execution_failed"


@dataclass(frozen=True, slots=True)
class CoordinatorResult:
    request_id: str
    status: CoordinatorStatus
    plan: PlanIR | None = None
    validation: StaticCheckReport | None = None
    execution: ExecutionResult | None = None
    message: str | None = None


class Coordinator:
    def __init__(
        self,
        *,
        planner: Planner,
        world: SimulatedWorld,
        policy: Policy,
        executor: Executor | None = None,
        audit: InMemoryAuditLog | None = None,
    ) -> None:
        self._planner = planner
        self._world = world
        self._policy = policy
        self._executor = executor or Executor()
        self._audit = audit or InMemoryAuditLog()

    @property
    def audit(self) -> InMemoryAuditLog:
        return self._audit

    def handle(self, request: PlanningRequest) -> CoordinatorResult:
        state = self._world.snapshot()
        context = PlannerContext(
            capabilities=self._world.capability_cards,
            state=state,
            policy=self._policy,
        )
        try:
            output = self._planner.plan(request, context)
            plan = output if isinstance(output, PlanIR) else parse_plan(output)
        except Exception as exc:
            self._audit.append(
                request_id=request.request_id,
                event_type="planning",
                outcome="failed",
                details={"error_type": type(exc).__name__},
                timestamp=self._world.clock.now(),
            )
            return CoordinatorResult(
                request_id=request.request_id,
                status=(
                    CoordinatorStatus.INVALID_PLAN
                    if isinstance(exc, PlanParseError)
                    else CoordinatorStatus.PLANNER_FAILED
                ),
                message=str(exc),
            )

        if plan.request_id != request.request_id:
            self._audit.append(
                request_id=request.request_id,
                event_type="validation",
                outcome="rejected",
                details={"reason": "request_id_mismatch"},
                timestamp=self._world.clock.now(),
            )
            return CoordinatorResult(
                request_id=request.request_id,
                status=CoordinatorStatus.INVALID_PLAN,
                plan=plan,
                message="plan request_id does not match the request",
            )

        report = check_plan(
            plan,
            context.capabilities,
            state,
            self._policy,
            now=self._world.clock.now(),
        )
        if not report.valid:
            self._audit.append(
                request_id=request.request_id,
                event_type="validation",
                outcome="rejected",
                details={"issue_count": len(report.issues)},
                timestamp=self._world.clock.now(),
            )
            return CoordinatorResult(
                request_id=request.request_id,
                status=CoordinatorStatus.INVALID_PLAN,
                plan=plan,
                validation=report,
                message="candidate plan failed deterministic validation",
            )

        self._audit.append(
            request_id=request.request_id,
            event_type="validation",
            outcome="accepted",
            details={"route": plan.route.value, "plan_sha256": plan_fingerprint(plan)},
            timestamp=self._world.clock.now(),
        )
        if plan.route in {Route.LOCAL, Route.HYBRID}:
            from edge_delegate.ir import ValidatedPlan

            execution = self._executor.execute(
                ValidatedPlan(plan=plan, report=report), self._world
            )
            self._audit.append(
                request_id=request.request_id,
                event_type="execution",
                outcome=execution.status.value,
                details={"step_count": len(execution.steps)},
                timestamp=self._world.clock.now(),
            )
            if execution.status is ExecutionStatus.FAILED:
                return CoordinatorResult(
                    request_id=request.request_id,
                    status=CoordinatorStatus.EXECUTION_FAILED,
                    plan=plan,
                    validation=report,
                    execution=execution,
                )
            if plan.route is Route.HYBRID:
                return CoordinatorResult(
                    request_id=request.request_id,
                    status=CoordinatorStatus.EXTERNAL_REQUIRED,
                    plan=plan,
                    validation=report,
                    execution=execution,
                    message="local portion completed; external handoff is still required",
                )
            return CoordinatorResult(
                request_id=request.request_id,
                status=CoordinatorStatus.EXECUTED,
                plan=plan,
                validation=report,
                execution=execution,
            )

        status = {
            Route.CLARIFY: CoordinatorStatus.CLARIFICATION_REQUIRED,
            Route.DENY: CoordinatorStatus.DENIED,
            Route.DEFER: CoordinatorStatus.DEFERRED,
            Route.EXTERNAL: CoordinatorStatus.EXTERNAL_REQUIRED,
        }[plan.route]
        return CoordinatorResult(
            request_id=request.request_id,
            status=status,
            plan=plan,
            validation=report,
            message=plan.clarification,
        )
