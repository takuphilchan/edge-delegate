"""Sequential executor that accepts only statically validated plans."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from edge_delegate.contracts import CapabilityCard, Route, StepReference
from edge_delegate.contracts._validation import json_value
from edge_delegate.contracts.policy import Policy
from edge_delegate.contracts.state import JsonValue
from edge_delegate.ir import ValidatedPlan, check_execution_step, check_plan

from .idempotency import IdempotencyConflict, IdempotencyStore
from .journal import OperationJournal
from .ports import (
    CapabilityExecutionError,
    DeadlineGateway,
    DeviceGateway,
    IdempotencyRepository,
    UnknownPhysicalOutcome,
)


class StepStatus(StrEnum):
    SUCCEEDED = "succeeded"
    REPLAYED = "replayed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ExecutionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class StepExecution:
    step_id: str
    capability_id: str
    status: StepStatus
    result: JsonValue = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    request_id: str
    status: ExecutionStatus
    steps: tuple[StepExecution, ...]
    final_output: JsonValue = None
    error: str | None = None


def _invocation_fingerprint(capability_id: str, arguments: Mapping[str, JsonValue]) -> str:
    payload = json.dumps(
        {"capability_id": capability_id, "arguments": arguments},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _checked_arguments(card: CapabilityCard, arguments: Mapping[str, JsonValue]) -> dict:
    unknown = set(arguments) - set(card.arguments)
    missing = {name for name, spec in card.arguments.items() if spec.required} - set(arguments)
    if unknown or missing:
        raise CapabilityExecutionError("resolved arguments do not match capability parameters")
    checked = json_value(arguments, "$.arguments")
    for name, value in checked.items():
        if not card.arguments[name].matches(value):
            raise CapabilityExecutionError(
                f"resolved argument violates capability contract: {name}"
            )
    return checked


def _checked_result(card: CapabilityCard, result: object) -> JsonValue:
    checked = json_value(result, "$.result")
    if (card.result is None and checked is not None) or (
        card.result is not None and not card.result.matches(checked)
    ):
        raise CapabilityExecutionError("device result violates capability contract")
    return checked


class Executor:
    def __init__(
        self,
        *,
        idempotency: IdempotencyRepository | None = None,
        journal: OperationJournal | None = None,
        on_invoke: Callable[[str], None] | None = None,
    ) -> None:
        self._idempotency = IdempotencyStore() if idempotency is None else idempotency
        self._journal = journal
        self._on_invoke = on_invoke

    def _bounded(self, device, validated, policy, step, card, arguments, execution_deadline):
        plan = validated.plan
        if device.api_version != "edge-delegate-gateway.v2":
            raise CapabilityExecutionError("unsupported deadline gateway version")
        if self._journal is None:
            raise CapabilityExecutionError("deadline gateway requires a durable journal")
        operation_id = hashlib.sha256(
            json.dumps(
                [device.device_id, plan.request_id, step.step_id], separators=(",", ":")
            ).encode()
        ).hexdigest()
        fingerprint = _invocation_fingerprint(step.capability_id, arguments)
        status, result = self._journal.claim(
            operation_id,
            device.device_id,
            fingerprint,
            request_id=plan.request_id,
            metadata={
                "step_id": step.step_id,
                "capability_id": card.capability_id,
                "result_spec": None if card.result is None else card.result.to_dict(),
            },
        )
        deadline = min(
            execution_deadline, time.monotonic() + min(step.timeout_ms or 500, 500) / 1000
        )
        if status == "succeeded":
            return _checked_result(card, result), StepStatus.REPLAYED
        if status == "failed":
            raise CapabilityExecutionError("previous operation definitively failed")
        if time.monotonic() >= deadline:
            if status == "claimed":
                self._journal.finish(operation_id, "failed")
                raise CapabilityExecutionError("execution deadline exhausted before dispatch")
            raise UnknownPhysicalOutcome("deadline exhausted before reconciliation")
        if status == "unknown":
            try:
                resolution = device.reconcile(operation_id, deadline=deadline)
                if resolution.status == "succeeded":
                    result = _checked_result(card, resolution.result)
                    self._journal.finish(operation_id, "succeeded", result)
                    return result, StepStatus.REPLAYED
            except Exception as exc:
                raise UnknownPhysicalOutcome("reconciliation failed") from exc
            if resolution.status == "failed":
                self._journal.finish(operation_id, "failed")
                raise CapabilityExecutionError("reconciled operation failed")
            raise UnknownPhysicalOutcome("operation remains unresolved; not replayed")
        if status != "claimed":
            raise UnknownPhysicalOutcome("unrecognized operation status; not replayed")
        # Only a new dispatch needs fresh execution guards. A receipt lookup above
        # must remain possible after a completed action changes its own precondition.
        try:
            current = check_execution_step(
                validated,
                step.step_id,
                device.capability_cards,
                device.snapshot(),
                policy,
                now=device.clock.now(),
            )
            if not current.valid:
                raise CapabilityExecutionError("fresh per-step authorization rejected")
            if time.monotonic() >= deadline:
                raise CapabilityExecutionError("execution deadline exhausted before dispatch")
        except Exception:
            self._journal.finish(operation_id, "failed")
            raise
        try:
            if self._on_invoke is not None:
                self._on_invoke(step.capability_id)
            result = _checked_result(
                card,
                device.invoke_bounded(
                    step.capability_id,
                    arguments,
                    operation_id=operation_id,
                    deadline=deadline,
                ),
            )
            self._journal.finish(operation_id, "succeeded", result)
            return result, StepStatus.SUCCEEDED
        except Exception as exc:
            # Even a bad response may follow a successful physical write.
            raise UnknownPhysicalOutcome("no confirmed result; reconciliation required") from exc

    def execute(
        self,
        validated: ValidatedPlan,
        device: DeviceGateway,
        policy: Policy,
    ) -> ExecutionResult:
        plan = validated.plan
        execution_deadline = time.monotonic() + policy.budget.max_total_latency_ms / 1000
        if plan.route not in {Route.LOCAL, Route.HYBRID}:
            raise ValueError("only local and hybrid local steps are executable")

        try:
            binding_error = validated.binding_error(device.capability_cards, policy)
        except Exception as exc:
            return ExecutionResult(
                request_id=plan.request_id,
                status=ExecutionStatus.FAILED,
                steps=(),
                error=f"execution authorization check failed: {type(exc).__name__}",
            )
        if binding_error is not None:
            return ExecutionResult(
                request_id=plan.request_id,
                status=ExecutionStatus.FAILED,
                steps=(),
                error=binding_error,
            )
        try:
            # Legacy gateways keep their original whole-plan preflight. Deadline
            # gateways check each new dispatch, after handling recorded operations.
            if isinstance(device, DeadlineGateway):
                if self._journal is None:
                    raise CapabilityExecutionError("deadline gateway requires a durable journal")
                self._journal.bind_plan(device.device_id, plan)
                current_report = None
            else:
                current_state = device.snapshot()
                current_report = check_plan(
                    plan,
                    device.capability_cards,
                    current_state,
                    policy,
                    now=device.clock.now(),
                )
        except Exception as exc:
            return ExecutionResult(
                request_id=plan.request_id,
                status=ExecutionStatus.FAILED,
                steps=(),
                error=f"execution preflight failed: {type(exc).__name__}",
            )
        if current_report is not None and not current_report.valid:
            codes = ",".join(sorted({issue.code for issue in current_report.issues}))
            return ExecutionResult(
                request_id=plan.request_id,
                status=ExecutionStatus.FAILED,
                steps=(),
                error=f"execution preflight rejected the active device state: {codes}",
            )

        outputs: dict[str, JsonValue] = {}
        records: list[StepExecution] = []
        cards = {card.capability_id: card for card in device.capability_cards}
        for step in plan.steps:
            scoped_key = (
                None
                if step.idempotency_key is None
                else f"{step.capability_id}:{step.idempotency_key}"
            )
            try:
                card = cards[step.capability_id]
                arguments = _checked_arguments(
                    card,
                    {
                        name: outputs[value.step_id] if isinstance(value, StepReference) else value
                        for name, value in step.arguments.items()
                    },
                )
                fingerprint = _invocation_fingerprint(step.capability_id, arguments)
                cached = (
                    None
                    if scoped_key is None
                    else self._idempotency.lookup(scoped_key, fingerprint)
                )
                if isinstance(device, DeadlineGateway):
                    result, status = self._bounded(
                        device, validated, policy, step, card, arguments, execution_deadline
                    )
                elif cached is not None:
                    result = _checked_result(card, cached.result)
                    status = StepStatus.REPLAYED
                else:
                    if self._on_invoke is not None:
                        self._on_invoke(step.capability_id)
                    result = _checked_result(card, device.invoke(step.capability_id, arguments))
                    status = StepStatus.SUCCEEDED
                    if scoped_key is not None:
                        self._idempotency.record(scoped_key, fingerprint, result)
            except UnknownPhysicalOutcome as exc:
                records.append(
                    StepExecution(
                        step.step_id, step.capability_id, StepStatus.UNKNOWN, error=str(exc)
                    )
                )
                return ExecutionResult(
                    plan.request_id, ExecutionStatus.UNKNOWN, tuple(records), error=str(exc)
                )
            except (CapabilityExecutionError, IdempotencyConflict, KeyError, ValueError) as exc:
                records.append(
                    StepExecution(
                        step_id=step.step_id,
                        capability_id=step.capability_id,
                        status=StepStatus.FAILED,
                        error=str(exc),
                    )
                )
                return ExecutionResult(
                    request_id=plan.request_id,
                    status=ExecutionStatus.FAILED,
                    steps=tuple(records),
                    final_output=None,
                    error=str(exc),
                )
            except Exception as exc:
                records.append(
                    StepExecution(
                        step_id=step.step_id,
                        capability_id=step.capability_id,
                        status=StepStatus.FAILED,
                        error=f"device invocation failed: {type(exc).__name__}",
                    )
                )
                return ExecutionResult(
                    request_id=plan.request_id,
                    status=ExecutionStatus.FAILED,
                    steps=tuple(records),
                    final_output=None,
                    error=f"device invocation failed: {type(exc).__name__}",
                )
            outputs[step.step_id] = result
            records.append(
                StepExecution(
                    step_id=step.step_id,
                    capability_id=step.capability_id,
                    status=status,
                    result=result,
                )
            )

        return ExecutionResult(
            request_id=plan.request_id,
            status=ExecutionStatus.SUCCEEDED,
            steps=tuple(records),
            final_output=records[-1].result if records else None,
        )
