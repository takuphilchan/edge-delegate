"""Bounded decisions compiled by trusted code into ordinary, untrusted Plan IR."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from hashlib import sha256

from edge_delegate.contracts import PlanIR, PlanningRequest, PlanStep, Route, StepReference
from edge_delegate.contracts._validation import json_value
from edge_delegate.policy.permissions import capability_allowed, missing_permissions

from .base import PlannerContext, PlannerOutputError, PlanningObservation

TASK_PROTOCOL = "bounded-task.v1"


@dataclass(frozen=True)
class TaskDecision:
    task: str
    parameters: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != {"task", "parameters"}:
            raise PlannerOutputError("task decision requires only task and parameters")
        if not isinstance(value["task"], str) or not isinstance(value["parameters"], dict):
            raise PlannerOutputError("invalid task decision types")
        return cls(value["task"], json_value(value["parameters"], "$.parameters"))

    def to_dict(self):
        return {"task": self.task, "parameters": dict(self.parameters)}


@dataclass(frozen=True)
class TaskDefinition:
    task_id: str
    description: str
    build: Callable[[Mapping[str, object]], tuple[PlanStep, ...]]


def _reference_steps(task, parameters):
    if task == "display_number":
        if set(parameters) != {"value"} or type(parameters["value"]) not in {int, float}:
            raise PlannerOutputError("display_number requires one finite numeric value")
        json_value(parameters["value"], "$.value")
        return (PlanStep("display", "display.value.show", dict(parameters)),)
    if parameters:
        raise PlannerOutputError("this task does not accept parameters")
    read = PlanStep("read_temperature", "sensor.temperature.read")
    if task == "read_temperature":
        return (read,)
    return (read, PlanStep("display", "display.value.show", {"value": StepReference(read.step_id)}))


class TaskCatalog:
    """Only installed application code can register task implementations."""

    def __init__(self, definitions, *, version="local-display.v1"):
        if not isinstance(version, str) or not version.strip():
            raise ValueError("task catalog requires a nonempty version")
        self.version = version
        self.definitions = {}
        for definition in definitions:
            if (
                not isinstance(definition, TaskDefinition)
                or not isinstance(definition.task_id, str)
                or not definition.task_id.strip()
                or not isinstance(definition.description, str)
                or not definition.description.strip()
                or not callable(definition.build)
            ):
                raise ValueError(
                    "task definitions require an identifier, description, and installed builder"
                )
            if definition.task_id in self.definitions or definition.task_id in {"clarify", "deny"}:
                raise ValueError("duplicate or reserved task identifier")
            self.definitions[definition.task_id] = definition

    def compile(self, decision: TaskDecision, request: PlanningRequest, context: PlannerContext):
        # Validate even decisions constructed directly by a plugin.
        decision = TaskDecision.from_dict(decision.to_dict())
        if decision.task in {"clarify", "deny"}:
            if decision.parameters:
                raise PlannerOutputError("abstention takes no parameters")
            return PlanIR(
                request_id=request.request_id,
                route=Route(decision.task),
                clarification="Specify one supported task, target, and any required value."
                if decision.task == "clarify"
                else None,
                reason_codes=(
                    "ambiguous_request" if decision.task == "clarify" else "unsupported_request",
                ),
            )
        definition = self.definitions.get(decision.task)
        if definition is None:
            raise PlannerOutputError("unknown bounded task")
        steps = definition.build(decision.parameters)
        cards = {card.capability_id: card for card in context.capabilities}
        for step in steps:
            card = cards.get(step.capability_id)
            if (
                card is None
                or not capability_allowed(card, context.policy)
                or missing_permissions(card, context.policy)
            ):
                return PlanIR(
                    request_id=request.request_id,
                    route=Route.DENY,
                    reason_codes=("capability_unavailable",),
                )
        from dataclasses import replace

        return PlanIR(
            request_id=request.request_id,
            route=Route.LOCAL,
            steps=tuple(
                replace(
                    step,
                    timeout_ms=500,
                    idempotency_key=sha256(
                        f"{request.request_id}:{step.step_id}".encode()
                    ).hexdigest(),
                )
                for step in steps
            ),
        )


def reference_catalog():
    descriptions = {
        "read_temperature": "Read ambient temperature without displaying it.",
        "display_number": "Display the explicit numeric value supplied in the request.",
        "show_temperature": "Read current ambient temperature and display the reading.",
    }
    return TaskCatalog(
        tuple(
            TaskDefinition(
                name, description, lambda parameters, task=name: _reference_steps(task, parameters)
            )
            for name, description in descriptions.items()
        )
    )


class BoundedPlanner:
    provides_confidence = False

    def __init__(self, decide, *, catalog=None, decide_batch=None):
        self.decide = decide
        self.decide_batch = decide_batch
        self.catalog = reference_catalog() if catalog is None else catalog

    def plan(self, request, context):
        # Keep the normal single-request path free of diagnostic allocations.
        return self.catalog.compile(self.decide(request, context), request, context)

    def _observe(self, request, context, decision=None):
        evidence = None
        try:
            if isinstance(decision, Exception):
                raise decision
            if decision is None:
                decision = self.decide(request, context)
            evidence = TaskDecision.from_dict(decision.to_dict()).to_dict()
            plan = self.catalog.compile(TaskDecision.from_dict(evidence), request, context)
            return PlanningObservation(plan=plan, decision=evidence)
        except Exception as exc:
            return PlanningObservation(decision=evidence, error=exc)

    def plan_with_diagnostics(self, request, context):
        return self._observe(request, context)

    def plan_many(self, requests, contexts):
        results = []
        for observation in self.plan_many_with_diagnostics(requests, contexts):
            try:
                results.append(observation.unwrap())
            except Exception as exc:
                results.append(exc)
        return results

    def plan_many_with_diagnostics(self, requests, contexts):
        decisions = (
            self.decide_batch(requests, contexts)
            if self.decide_batch is not None
            else [None] * len(requests)
        )
        return [
            self._observe(request, context, decision)
            for request, context, decision in zip(requests, contexts, decisions, strict=True)
        ]
