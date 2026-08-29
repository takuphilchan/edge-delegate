"""Sequential executor that accepts only statically validated plans."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from edge_delegate.contracts import Route, StepReference
from edge_delegate.contracts.state import JsonValue
from edge_delegate.ir import ValidatedPlan
from edge_delegate.simulator import CapabilityInvocationError, SimulatedWorld

from .idempotency import IdempotencyConflict, IdempotencyStore


class StepStatus(StrEnum):
    SUCCEEDED = "succeeded"
    REPLAYED = "replayed"
    FAILED = "failed"


class ExecutionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


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


def _invocation_fingerprint(capability_id: str, arguments: Mapping[str, JsonValue]) -> str:
    payload = json.dumps(
        {"capability_id": capability_id, "arguments": arguments},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Executor:
    def __init__(self, *, idempotency: IdempotencyStore | None = None) -> None:
        self._idempotency = idempotency or IdempotencyStore()

    def execute(self, validated: ValidatedPlan, world: SimulatedWorld) -> ExecutionResult:
        plan = validated.plan
        if plan.route not in {Route.LOCAL, Route.HYBRID}:
            raise ValueError("only local and hybrid local steps are executable")

        outputs: dict[str, JsonValue] = {}
        records: list[StepExecution] = []
        for step in plan.steps:
            arguments = {
                name: outputs[value.step_id] if isinstance(value, StepReference) else value
                for name, value in step.arguments.items()
            }
            fingerprint = _invocation_fingerprint(step.capability_id, arguments)
            scoped_key = (
                None
                if step.idempotency_key is None
                else f"{step.capability_id}:{step.idempotency_key}"
            )
            try:
                cached = (
                    None
                    if scoped_key is None
                    else self._idempotency.lookup(scoped_key, fingerprint)
                )
                if cached is not None:
                    result = cached.result
                    status = StepStatus.REPLAYED
                else:
                    result = world.invoke(step.capability_id, arguments)
                    status = StepStatus.SUCCEEDED
                    if scoped_key is not None:
                        self._idempotency.record(scoped_key, fingerprint, result)
            except (CapabilityInvocationError, IdempotencyConflict, KeyError) as exc:
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
