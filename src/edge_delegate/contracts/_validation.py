"""Small dependency-free helpers for strict wire-contract parsing."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NoReturn


@dataclass(frozen=True, slots=True)
class ContractIssue:
    """A machine-readable error found while parsing a wire contract."""

    path: str
    code: str
    message: str


class ContractError(ValueError):
    """Raised when untrusted data does not satisfy a versioned contract."""

    def __init__(self, *issues: ContractIssue) -> None:
        if not issues:
            raise ValueError("ContractError requires at least one issue")
        self.issues = issues
        summary = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
        super().__init__(summary)


def fail(path: str, code: str, message: str) -> NoReturn:
    raise ContractError(ContractIssue(path=path, code=code, message=message))


def expect_mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        fail(path, "type", "expected an object")
    if not all(isinstance(key, str) for key in value):
        fail(path, "key_type", "object keys must be strings")
    return value


def expect_sequence(value: object, path: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        fail(path, "type", "expected an array")
    return value


def expect_str(
    value: object,
    path: str,
    *,
    min_length: int = 1,
    max_length: int | None = None,
    pattern: str | None = None,
) -> str:
    if not isinstance(value, str):
        fail(path, "type", "expected a string")
    if len(value) < min_length:
        fail(path, "min_length", f"must contain at least {min_length} character(s)")
    if max_length is not None and len(value) > max_length:
        fail(path, "max_length", f"must contain at most {max_length} characters")
    if pattern is not None and re.fullmatch(pattern, value) is None:
        fail(path, "pattern", "has an invalid format")
    return value


def expect_bool(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        fail(path, "type", "expected a boolean")
    return value


def expect_int(
    value: object,
    path: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        fail(path, "type", "expected an integer")
    if minimum is not None and value < minimum:
        fail(path, "minimum", f"must be at least {minimum}")
    if maximum is not None and value > maximum:
        fail(path, "maximum", f"must be at most {maximum}")
    return value


def expect_number(
    value: object,
    path: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail(path, "type", "expected a finite number")
    result = float(value)
    if not math.isfinite(result):
        fail(path, "finite", "must be finite")
    if minimum is not None and result < minimum:
        fail(path, "minimum", f"must be at least {minimum}")
    if maximum is not None and result > maximum:
        fail(path, "maximum", f"must be at most {maximum}")
    return result


def expect_datetime(value: object, path: str) -> datetime:
    text = expect_str(value, path)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        fail(path, "date_time", "expected an ISO-8601 date-time")
    if parsed.tzinfo is None:
        fail(path, "timezone", "date-time must include a timezone")
    return parsed.astimezone(UTC)


def format_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("date-time must include a timezone")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def expect_enum(value: object, path: str, enum_type: type):
    try:
        return enum_type(value)
    except (TypeError, ValueError):
        allowed = ", ".join(repr(item.value) for item in enum_type)
        fail(path, "enum", f"expected one of: {allowed}")


def require(mapping: Mapping[str, object], key: str, path: str) -> object:
    if key not in mapping:
        fail(f"{path}.{key}", "required", "field is required")
    return mapping[key]


def reject_unknown(mapping: Mapping[str, object], allowed: set[str], path: str) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        fail(path, "unknown_fields", f"unknown field(s): {', '.join(unknown)}")


def expect_string_set(value: object, path: str) -> frozenset[str]:
    items = expect_sequence(value, path)
    parsed = [expect_str(item, f"{path}[{index}]") for index, item in enumerate(items)]
    if len(set(parsed)) != len(parsed):
        fail(path, "unique", "items must be unique")
    return frozenset(parsed)


def json_value(value: object, path: str = "$"):
    """Validate and defensively copy a JSON-compatible value."""

    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            fail(path, "finite", "JSON numbers must be finite")
        return value
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            fail(path, "key_type", "JSON object keys must be strings")
        return {key: json_value(item, f"{path}.{key}") for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [json_value(item, f"{path}[{index}]") for index, item in enumerate(value)]
    fail(path, "json_type", "value is not JSON-compatible")
