"""Deterministic Plan-IR validation against capabilities, state, and policy."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from edge_delegate.contracts import (
    CapabilityCard,
    Connectivity,
    DeviceState,
    PlanIR,
    Policy,
    Route,
    SideEffect,
    StepReference,
)
from edge_delegate.policy import capability_allowed, has_approval, missing_permissions

from .canonicalize import plan_fingerprint


@dataclass(frozen=True, slots=True)
class CheckIssue:
    path: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class StaticCheckReport:
    issues: tuple[CheckIssue, ...]
    total_latency_ms: int
    total_energy_mj: float
    peak_memory_bytes: int

    @property
    def valid(self) -> bool:
        return not self.issues


@dataclass(frozen=True, slots=True)
class ValidatedPlan:
    """A plan accompanied by evidence that deterministic checks passed."""

    plan: PlanIR
    report: StaticCheckReport

    def __post_init__(self) -> None:
        if not self.report.valid:
            raise ValueError("ValidatedPlan requires a valid report")


class PlanValidationError(ValueError):
    def __init__(self, report: StaticCheckReport) -> None:
        self.report = report
        summary = "; ".join(f"{issue.code} at {issue.path}" for issue in report.issues)
        super().__init__(summary)


def _capability_map(
    capabilities: Mapping[str, CapabilityCard] | Iterable[CapabilityCard],
) -> dict[str, CapabilityCard]:
    if isinstance(capabilities, Mapping):
        result = dict(capabilities)
    else:
        result = {}
        for card in capabilities:
            if card.capability_id in result:
                raise ValueError(f"duplicate capability card: {card.capability_id}")
            result[card.capability_id] = card
    for key, card in result.items():
        if key != card.capability_id:
            raise ValueError(f"capability index key {key!r} does not match card identifier")
    return result


def check_plan(
    plan: PlanIR,
    capabilities: Mapping[str, CapabilityCard] | Iterable[CapabilityCard],
    state: DeviceState,
    policy: Policy,
    *,
    now: datetime | None = None,
) -> StaticCheckReport:
    cards = _capability_map(capabilities)
    current = (now or datetime.now(UTC)).astimezone(UTC)
    plan_sha256 = plan_fingerprint(plan)
    issues: list[CheckIssue] = []

    def issue(path: str, code: str, message: str) -> None:
        issues.append(CheckIssue(path=path, code=code, message=message))

    _check_route_invariants(plan, policy, issue)
    if len(plan.steps) > policy.budget.max_steps:
        issue("$.steps", "step_budget", "plan exceeds the policy step limit")
    if state.observed_at.astimezone(UTC) > current + timedelta(seconds=5):
        issue("$.state.observed_at", "state_from_future", "device state timestamp is in the future")
    if plan.steps and state.age_seconds(current) > policy.max_state_age_seconds:
        issue("$.state.observed_at", "stale_state", "device state is older than policy allows")

    total_latency = 0
    total_energy = 0.0
    peak_memory = 0
    seen_steps: dict[str, CapabilityCard] = {}
    seen_ids: set[str] = set()
    seen_idempotency: set[tuple[str, str]] = set()

    for index, step in enumerate(plan.steps):
        path = f"$.steps[{index}]"
        if step.step_id in seen_ids:
            issue(f"{path}.step_id", "duplicate_step", "step identifiers must be unique")
        seen_ids.add(step.step_id)

        card = cards.get(step.capability_id)
        if card is None:
            issue(f"{path}.capability_id", "unknown_capability", "capability is not declared")
            continue
        if not capability_allowed(card, policy):
            issue(f"{path}.capability_id", "capability_denied", "capability is denied by policy")
        missing = missing_permissions(card, policy)
        if missing:
            issue(
                f"{path}.capability_id",
                "missing_permission",
                f"missing permission(s): {', '.join(sorted(missing))}",
            )
        if not has_approval(card, policy, plan.request_id, plan_sha256, current):
            issue(
                f"{path}.capability_id",
                "approval_required",
                "a valid request-scoped approval is required",
            )
        if card.cost.network_required and state.connectivity is Connectivity.OFFLINE:
            issue(f"{path}.capability_id", "network_unavailable", "capability requires a network")
        if (
            state.available_memory_bytes is not None
            and card.cost.memory_bytes > state.available_memory_bytes
        ):
            issue(
                f"{path}.capability_id",
                "memory_budget",
                "capability exceeds currently available memory",
            )
        for predicate_index, predicate in enumerate(card.preconditions):
            if not predicate.evaluate(state.values):
                issue(
                    f"{path}.preconditions[{predicate_index}]",
                    "precondition_failed",
                    f"device-state precondition failed for {predicate.key!r}",
                )

        expected_names = set(card.arguments)
        supplied_names = set(step.arguments)
        for name, spec in card.arguments.items():
            if spec.required and name not in supplied_names:
                issue(f"{path}.arguments.{name}", "required_argument", "argument is required")
        for name in sorted(supplied_names - expected_names):
            issue(f"{path}.arguments.{name}", "unknown_argument", "argument is not declared")
        for name in sorted(supplied_names & expected_names):
            value = step.arguments[name]
            spec = card.arguments[name]
            if isinstance(value, StepReference):
                source_card = seen_steps.get(value.step_id)
                if source_card is None:
                    issue(
                        f"{path}.arguments.{name}.$ref",
                        "invalid_reference",
                        "references must target an earlier valid step",
                    )
                elif source_card.result is None:
                    issue(
                        f"{path}.arguments.{name}.$ref",
                        "missing_output",
                        "referenced capability does not declare an output",
                    )
                elif not spec.accepts_kind(source_card.result.kind):
                    issue(
                        f"{path}.arguments.{name}.$ref",
                        "reference_type",
                        "referenced output type is incompatible with the argument",
                    )
            elif not spec.matches(value):
                issue(
                    f"{path}.arguments.{name}",
                    "argument_type",
                    f"argument does not satisfy declared {spec.kind.value} constraints",
                )

        if step.timeout_ms is not None and step.timeout_ms > policy.budget.max_step_timeout_ms:
            issue(f"{path}.timeout_ms", "timeout_budget", "step timeout exceeds policy")
        if card.side_effect in {SideEffect.WRITE, SideEffect.PHYSICAL} and not step.idempotency_key:
            issue(
                f"{path}.idempotency_key",
                "idempotency_required",
                "write and physical capabilities require an idempotency key",
            )
        if step.idempotency_key is not None:
            idempotency_scope = (step.capability_id, step.idempotency_key)
            if idempotency_scope in seen_idempotency:
                issue(
                    f"{path}.idempotency_key",
                    "duplicate_idempotency",
                    "a capability idempotency key may appear only once per plan",
                )
            seen_idempotency.add(idempotency_scope)

        total_latency += card.cost.latency_ms
        total_energy += card.cost.energy_mj
        peak_memory = max(peak_memory, card.cost.memory_bytes)
        seen_steps[step.step_id] = card

    if total_latency > policy.budget.max_total_latency_ms:
        issue("$.steps", "latency_budget", "estimated plan latency exceeds policy")
    if total_energy > policy.budget.max_total_energy_mj:
        issue("$.steps", "energy_budget", "estimated plan energy exceeds policy")

    return StaticCheckReport(
        issues=tuple(issues),
        total_latency_ms=total_latency,
        total_energy_mj=total_energy,
        peak_memory_bytes=peak_memory,
    )


def _check_route_invariants(plan: PlanIR, policy: Policy, issue) -> None:
    if plan.route is Route.LOCAL:
        if not plan.steps:
            issue("$.steps", "route_shape", "local routes require at least one step")
        if plan.clarification is not None:
            issue("$.clarification", "route_shape", "local routes cannot ask for clarification")
    elif plan.route is Route.HYBRID:
        if not plan.steps:
            issue("$.steps", "route_shape", "hybrid routes require at least one local step")
        if not policy.external_allowed:
            issue("$.route", "external_denied", "policy does not allow external processing")
    elif plan.route is Route.EXTERNAL:
        if plan.steps:
            issue("$.steps", "route_shape", "external routes cannot contain local steps")
        if not policy.external_allowed:
            issue("$.route", "external_denied", "policy does not allow external processing")
    elif plan.route is Route.CLARIFY:
        if plan.steps:
            issue("$.steps", "route_shape", "clarification routes cannot contain steps")
        if plan.clarification is None:
            issue("$.clarification", "route_shape", "clarification text is required")
    elif plan.route in {Route.DEFER, Route.DENY}:
        if plan.steps:
            issue("$.steps", "route_shape", "defer and deny routes cannot contain steps")
        if not plan.reason_codes:
            issue("$.reason_codes", "route_shape", "defer and deny routes require a reason code")


def validate_plan(
    plan: PlanIR,
    capabilities: Mapping[str, CapabilityCard] | Iterable[CapabilityCard],
    state: DeviceState,
    policy: Policy,
    *,
    now: datetime | None = None,
) -> ValidatedPlan:
    report = check_plan(plan, capabilities, state, policy, now=now)
    if not report.valid:
        raise PlanValidationError(report)
    return ValidatedPlan(plan=plan, report=report)
