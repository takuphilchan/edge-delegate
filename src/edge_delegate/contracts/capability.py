"""Versioned capability-card contracts and value constraints."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from ._validation import (
    expect_bool,
    expect_enum,
    expect_int,
    expect_mapping,
    expect_number,
    expect_sequence,
    expect_str,
    expect_string_set,
    fail,
    json_value,
    reject_unknown,
    require,
)
from .policy import PrivacyClass
from .state import JsonValue, StatePredicate

CAPABILITY_ID_PATTERN = r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"
SEMVER_PATTERN = r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$"


class ValueKind(StrEnum):
    ANY = "any"
    NULL = "null"
    BOOLEAN = "boolean"
    INTEGER = "integer"
    NUMBER = "number"
    STRING = "string"
    ARRAY = "array"
    OBJECT = "object"


class SideEffect(StrEnum):
    NONE = "none"
    READ = "read"
    WRITE = "write"
    PHYSICAL = "physical"


def kind_of(value: JsonValue) -> ValueKind:
    if value is None:
        return ValueKind.NULL
    if isinstance(value, bool):
        return ValueKind.BOOLEAN
    if isinstance(value, int):
        return ValueKind.INTEGER
    if isinstance(value, float):
        return ValueKind.NUMBER
    if isinstance(value, str):
        return ValueKind.STRING
    if isinstance(value, list):
        return ValueKind.ARRAY
    return ValueKind.OBJECT


def kind_accepts(expected: ValueKind, actual: ValueKind) -> bool:
    return (
        expected is ValueKind.ANY
        or expected is actual
        or (expected is ValueKind.NUMBER and actual is ValueKind.INTEGER)
    )


@dataclass(frozen=True, slots=True)
class ValueSpec:
    kind: ValueKind
    required: bool = True
    enum: tuple[JsonValue, ...] = ()
    minimum: float | None = None
    maximum: float | None = None

    def __post_init__(self) -> None:
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum cannot be greater than maximum")
        if (self.minimum is not None or self.maximum is not None) and self.kind not in {
            ValueKind.INTEGER,
            ValueKind.NUMBER,
        }:
            raise ValueError("numeric bounds require an integer or number kind")
        if any(not kind_accepts(self.kind, kind_of(item)) for item in self.enum):
            raise ValueError("enum values must satisfy the declared kind")

    @classmethod
    def from_dict(cls, raw: object, path: str) -> ValueSpec:
        data = expect_mapping(raw, path)
        reject_unknown(data, {"kind", "required", "enum", "minimum", "maximum"}, path)
        enum_raw = expect_sequence(data.get("enum", []), f"{path}.enum")
        kind = expect_enum(require(data, "kind", path), f"{path}.kind", ValueKind)
        enum = tuple(
            json_value(item, f"{path}.enum[{index}]") for index, item in enumerate(enum_raw)
        )
        minimum = (
            None
            if data.get("minimum") is None
            else expect_number(data["minimum"], f"{path}.minimum")
        )
        maximum = (
            None
            if data.get("maximum") is None
            else expect_number(data["maximum"], f"{path}.maximum")
        )
        if minimum is not None and maximum is not None and minimum > maximum:
            fail(path, "bounds", "minimum cannot be greater than maximum")
        if (minimum is not None or maximum is not None) and kind not in {
            ValueKind.INTEGER,
            ValueKind.NUMBER,
        }:
            fail(path, "bounds", "numeric bounds require an integer or number kind")
        if any(not kind_accepts(kind, kind_of(item)) for item in enum):
            fail(f"{path}.enum", "enum_type", "enum values must satisfy the declared kind")
        return cls(
            kind=kind,
            required=expect_bool(data.get("required", True), f"{path}.required"),
            enum=enum,
            minimum=minimum,
            maximum=maximum,
        )

    def accepts_kind(self, actual: ValueKind) -> bool:
        return kind_accepts(self.kind, actual)

    def matches(self, value: JsonValue) -> bool:
        if not self.accepts_kind(kind_of(value)):
            return False
        if self.enum and value not in self.enum:
            return False
        if self.minimum is not None or self.maximum is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return False
            if self.minimum is not None and value < self.minimum:
                return False
            if self.maximum is not None and value > self.maximum:
                return False
        return True

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"kind": self.kind.value, "required": self.required}
        if self.enum:
            result["enum"] = list(self.enum)
        if self.minimum is not None:
            result["minimum"] = self.minimum
        if self.maximum is not None:
            result["maximum"] = self.maximum
        return result


@dataclass(frozen=True, slots=True)
class ResourceCost:
    latency_ms: int = 0
    energy_mj: float = 0.0
    memory_bytes: int = 0
    network_required: bool = False

    @classmethod
    def from_dict(cls, raw: object, path: str = "$.cost") -> ResourceCost:
        data = expect_mapping(raw, path)
        reject_unknown(
            data, {"latency_ms", "energy_mj", "memory_bytes", "network_required"}, path
        )
        return cls(
            latency_ms=expect_int(data.get("latency_ms", 0), f"{path}.latency_ms", minimum=0),
            energy_mj=expect_number(data.get("energy_mj", 0), f"{path}.energy_mj", minimum=0),
            memory_bytes=expect_int(
                data.get("memory_bytes", 0), f"{path}.memory_bytes", minimum=0
            ),
            network_required=expect_bool(
                data.get("network_required", False), f"{path}.network_required"
            ),
        )

    def to_dict(self) -> dict[str, int | float | bool]:
        return {
            "latency_ms": self.latency_ms,
            "energy_mj": self.energy_mj,
            "memory_bytes": self.memory_bytes,
            "network_required": self.network_required,
        }


@dataclass(frozen=True, slots=True)
class CapabilityCard:
    capability_id: str
    version: str
    description: str
    arguments: Mapping[str, ValueSpec]
    result: ValueSpec | None = None
    preconditions: tuple[StatePredicate, ...] = ()
    side_effect: SideEffect = SideEffect.NONE
    permissions: frozenset[str] = field(default_factory=frozenset)
    approval_required: bool = False
    privacy_classes: frozenset[PrivacyClass] = field(
        default_factory=lambda: frozenset({PrivacyClass.PUBLIC})
    )
    cost: ResourceCost = field(default_factory=ResourceCost)
    schema_version: str = field(default="capability-card.v0", init=False)

    @classmethod
    def from_dict(cls, raw: object, path: str = "$") -> CapabilityCard:
        data = expect_mapping(raw, path)
        reject_unknown(
            data,
            {
                "schema_version",
                "capability_id",
                "version",
                "description",
                "arguments",
                "result",
                "preconditions",
                "side_effect",
                "permissions",
                "approval_required",
                "privacy_classes",
                "cost",
            },
            path,
        )
        version = expect_str(require(data, "schema_version", path), f"{path}.schema_version")
        if version != "capability-card.v0":
            fail(f"{path}.schema_version", "version", "unsupported capability-card version")
        arguments_raw = expect_mapping(require(data, "arguments", path), f"{path}.arguments")
        preconditions_raw = expect_sequence(
            data.get("preconditions", []), f"{path}.preconditions"
        )
        privacy_raw = expect_sequence(
            data.get("privacy_classes", [PrivacyClass.PUBLIC.value]), f"{path}.privacy_classes"
        )
        result_raw = data.get("result")
        return cls(
            capability_id=expect_str(
                require(data, "capability_id", path),
                f"{path}.capability_id",
                max_length=128,
                pattern=CAPABILITY_ID_PATTERN,
            ),
            version=expect_str(
                require(data, "version", path),
                f"{path}.version",
                max_length=32,
                pattern=SEMVER_PATTERN,
            ),
            description=expect_str(
                require(data, "description", path), f"{path}.description", max_length=1000
            ),
            arguments={
                expect_str(name, f"{path}.arguments.<key>", max_length=128): ValueSpec.from_dict(
                    spec, f"{path}.arguments.{name}"
                )
                for name, spec in arguments_raw.items()
            },
            result=(
                None if result_raw is None else ValueSpec.from_dict(result_raw, f"{path}.result")
            ),
            preconditions=tuple(
                StatePredicate.from_dict(item, f"{path}.preconditions[{index}]")
                for index, item in enumerate(preconditions_raw)
            ),
            side_effect=expect_enum(
                data.get("side_effect", SideEffect.NONE.value),
                f"{path}.side_effect",
                SideEffect,
            ),
            permissions=expect_string_set(data.get("permissions", []), f"{path}.permissions"),
            approval_required=expect_bool(
                data.get("approval_required", False), f"{path}.approval_required"
            ),
            privacy_classes=frozenset(
                expect_enum(item, f"{path}.privacy_classes[{index}]", PrivacyClass)
                for index, item in enumerate(privacy_raw)
            ),
            cost=ResourceCost.from_dict(data.get("cost", {}), f"{path}.cost"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "capability_id": self.capability_id,
            "version": self.version,
            "description": self.description,
            "arguments": {name: spec.to_dict() for name, spec in self.arguments.items()},
            "result": None if self.result is None else self.result.to_dict(),
            "preconditions": [predicate.to_dict() for predicate in self.preconditions],
            "side_effect": self.side_effect.value,
            "permissions": sorted(self.permissions),
            "approval_required": self.approval_required,
            "privacy_classes": sorted(item.value for item in self.privacy_classes),
            "cost": self.cost.to_dict(),
        }
