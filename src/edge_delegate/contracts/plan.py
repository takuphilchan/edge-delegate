"""Versioned, typed Plan-IR contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from ._validation import (
    expect_enum,
    expect_int,
    expect_mapping,
    expect_number,
    expect_sequence,
    expect_str,
    fail,
    json_value,
    reject_unknown,
    require,
)
from .capability import CAPABILITY_ID_PATTERN
from .state import JsonValue

STEP_ID_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"


class Route(StrEnum):
    LOCAL = "local"
    HYBRID = "hybrid"
    EXTERNAL = "external"
    CLARIFY = "clarify"
    DEFER = "defer"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class StepReference:
    """Reference the output of an earlier step by stable step identifier."""

    step_id: str

    @classmethod
    def from_dict(cls, raw: object, path: str) -> StepReference:
        data = expect_mapping(raw, path)
        reject_unknown(data, {"$ref"}, path)
        return cls(
            step_id=expect_str(
                require(data, "$ref", path),
                f"{path}.$ref",
                max_length=64,
                pattern=STEP_ID_PATTERN,
            )
        )

    def to_dict(self) -> dict[str, str]:
        return {"$ref": self.step_id}


type ArgumentValue = JsonValue | StepReference


def parse_argument(value: object, path: str) -> ArgumentValue:
    if isinstance(value, Mapping) and "$ref" in value:
        return StepReference.from_dict(value, path)
    return json_value(value, path)


@dataclass(frozen=True, slots=True)
class PlanStep:
    step_id: str
    capability_id: str
    arguments: Mapping[str, ArgumentValue] = field(default_factory=dict)
    timeout_ms: int | None = None
    idempotency_key: str | None = None

    @classmethod
    def from_dict(cls, raw: object, path: str = "$.steps[]") -> PlanStep:
        data = expect_mapping(raw, path)
        reject_unknown(
            data,
            {"step_id", "capability_id", "arguments", "timeout_ms", "idempotency_key"},
            path,
        )
        arguments_raw = expect_mapping(data.get("arguments", {}), f"{path}.arguments")
        timeout_raw = data.get("timeout_ms")
        idempotency_raw = data.get("idempotency_key")
        return cls(
            step_id=expect_str(
                require(data, "step_id", path),
                f"{path}.step_id",
                max_length=64,
                pattern=STEP_ID_PATTERN,
            ),
            capability_id=expect_str(
                require(data, "capability_id", path),
                f"{path}.capability_id",
                max_length=128,
                pattern=CAPABILITY_ID_PATTERN,
            ),
            arguments={
                name: parse_argument(value, f"{path}.arguments.{name}")
                for name, value in arguments_raw.items()
            },
            timeout_ms=(
                None
                if timeout_raw is None
                else expect_int(timeout_raw, f"{path}.timeout_ms", minimum=1)
            ),
            idempotency_key=(
                None
                if idempotency_raw is None
                else expect_str(idempotency_raw, f"{path}.idempotency_key", max_length=128)
            ),
        )

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "step_id": self.step_id,
            "capability_id": self.capability_id,
            "arguments": {
                name: value.to_dict() if isinstance(value, StepReference) else value
                for name, value in self.arguments.items()
            },
        }
        if self.timeout_ms is not None:
            result["timeout_ms"] = self.timeout_ms
        if self.idempotency_key is not None:
            result["idempotency_key"] = self.idempotency_key
        return result


@dataclass(frozen=True, slots=True)
class PlanIR:
    request_id: str
    route: Route
    steps: tuple[PlanStep, ...] = ()
    reason_codes: tuple[str, ...] = ()
    confidence: float = 0.0
    clarification: str | None = None
    schema_version: str = field(default="plan-ir.v0", init=False)

    @classmethod
    def from_dict(cls, raw: object, path: str = "$") -> PlanIR:
        data = expect_mapping(raw, path)
        reject_unknown(
            data,
            {
                "schema_version",
                "request_id",
                "route",
                "steps",
                "reason_codes",
                "confidence",
                "clarification",
            },
            path,
        )
        version = expect_str(require(data, "schema_version", path), f"{path}.schema_version")
        if version != "plan-ir.v0":
            fail(f"{path}.schema_version", "version", "unsupported Plan-IR version")
        steps_raw = expect_sequence(data.get("steps", []), f"{path}.steps")
        reasons_raw = expect_sequence(data.get("reason_codes", []), f"{path}.reason_codes")
        reasons = tuple(
            expect_str(item, f"{path}.reason_codes[{index}]", max_length=64)
            for index, item in enumerate(reasons_raw)
        )
        if len(set(reasons)) != len(reasons):
            fail(f"{path}.reason_codes", "unique", "reason codes must be unique")
        clarification_raw = data.get("clarification")
        return cls(
            request_id=expect_str(
                require(data, "request_id", path), f"{path}.request_id", max_length=128
            ),
            route=expect_enum(require(data, "route", path), f"{path}.route", Route),
            steps=tuple(
                PlanStep.from_dict(item, f"{path}.steps[{index}]")
                for index, item in enumerate(steps_raw)
            ),
            reason_codes=reasons,
            confidence=expect_number(
                data.get("confidence", 0.0), f"{path}.confidence", minimum=0, maximum=1
            ),
            clarification=(
                None
                if clarification_raw is None
                else expect_str(clarification_raw, f"{path}.clarification", max_length=1000)
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "route": self.route.value,
            "steps": [step.to_dict() for step in self.steps],
            "reason_codes": list(self.reason_codes),
            "confidence": self.confidence,
            "clarification": self.clarification,
        }
