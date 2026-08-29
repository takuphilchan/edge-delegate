"""Versioned device-state and precondition contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from ._validation import (
    expect_datetime,
    expect_enum,
    expect_int,
    expect_mapping,
    expect_number,
    expect_str,
    fail,
    format_datetime,
    json_value,
    reject_unknown,
    require,
)

type JsonValue = bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None


class Connectivity(StrEnum):
    OFFLINE = "offline"
    METERED = "metered"
    ONLINE = "online"


class PredicateOperator(StrEnum):
    EXISTS = "exists"
    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"


@dataclass(frozen=True, slots=True)
class StatePredicate:
    """A deliberately small precondition language; never arbitrary code."""

    key: str
    operator: PredicateOperator
    value: JsonValue = None

    @classmethod
    def from_dict(cls, raw: object, path: str = "$.preconditions[]") -> StatePredicate:
        data = expect_mapping(raw, path)
        reject_unknown(data, {"key", "operator", "value"}, path)
        operator = expect_enum(require(data, "operator", path), f"{path}.operator", PredicateOperator)
        value = json_value(data.get("value"), f"{path}.value")
        if operator is PredicateOperator.EXISTS and not isinstance(value, bool):
            fail(f"{path}.value", "type", "exists predicates require a boolean value")
        return cls(
            key=expect_str(require(data, "key", path), f"{path}.key", max_length=128),
            operator=operator,
            value=value,
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {"key": self.key, "operator": self.operator.value, "value": self.value}

    def evaluate(self, values: Mapping[str, JsonValue]) -> bool:
        present = self.key in values
        if self.operator is PredicateOperator.EXISTS:
            return present is self.value
        if not present:
            return False
        actual = values[self.key]
        try:
            if self.operator is PredicateOperator.EQ:
                return actual == self.value
            if self.operator is PredicateOperator.NE:
                return actual != self.value
            if self.operator is PredicateOperator.GT:
                return actual > self.value  # type: ignore[operator]
            if self.operator is PredicateOperator.GTE:
                return actual >= self.value  # type: ignore[operator]
            if self.operator is PredicateOperator.LT:
                return actual < self.value  # type: ignore[operator]
            if self.operator is PredicateOperator.LTE:
                return actual <= self.value  # type: ignore[operator]
            if self.operator is PredicateOperator.IN:
                return isinstance(self.value, list) and actual in self.value
        except TypeError:
            return False
        return False


@dataclass(frozen=True, slots=True)
class DeviceState:
    """A point-in-time, bounded snapshot supplied to planning and validation."""

    snapshot_id: str
    observed_at: datetime
    values: Mapping[str, JsonValue] = field(default_factory=dict)
    connectivity: Connectivity = Connectivity.OFFLINE
    battery_percent: float | None = None
    available_memory_bytes: int | None = None
    schema_version: str = field(default="device-state.v0", init=False)

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must include a timezone")

    @classmethod
    def from_dict(cls, raw: object, path: str = "$") -> DeviceState:
        data = expect_mapping(raw, path)
        reject_unknown(
            data,
            {
                "schema_version",
                "snapshot_id",
                "observed_at",
                "values",
                "connectivity",
                "battery_percent",
                "available_memory_bytes",
            },
            path,
        )
        version = expect_str(require(data, "schema_version", path), f"{path}.schema_version")
        if version != "device-state.v0":
            fail(f"{path}.schema_version", "version", "unsupported device-state version")
        values = expect_mapping(require(data, "values", path), f"{path}.values")
        return cls(
            snapshot_id=expect_str(
                require(data, "snapshot_id", path), f"{path}.snapshot_id", max_length=128
            ),
            observed_at=expect_datetime(require(data, "observed_at", path), f"{path}.observed_at"),
            values={key: json_value(value, f"{path}.values.{key}") for key, value in values.items()},
            connectivity=expect_enum(
                data.get("connectivity", Connectivity.OFFLINE.value),
                f"{path}.connectivity",
                Connectivity,
            ),
            battery_percent=(
                None
                if data.get("battery_percent") is None
                else expect_number(
                    data["battery_percent"], f"{path}.battery_percent", minimum=0, maximum=100
                )
            ),
            available_memory_bytes=(
                None
                if data.get("available_memory_bytes") is None
                else expect_int(
                    data["available_memory_bytes"],
                    f"{path}.available_memory_bytes",
                    minimum=0,
                )
            ),
        )

    def age_seconds(self, now: datetime | None = None) -> float:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        return max(0.0, (current - self.observed_at.astimezone(UTC)).total_seconds())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "observed_at": format_datetime(self.observed_at),
            "values": dict(self.values),
            "connectivity": self.connectivity.value,
            "battery_percent": self.battery_percent,
            "available_memory_bytes": self.available_memory_bytes,
        }
