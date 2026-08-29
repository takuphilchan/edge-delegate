"""Strict Plan-IR JSON parsing with bounded input and duplicate-key rejection."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import NoReturn

from edge_delegate.contracts import ContractError, ContractIssue, PlanIR

MAX_PLAN_BYTES = 64 * 1024
MAX_PLAN_DEPTH = 32


class PlanParseError(ContractError):
    """Raised when planner output cannot be treated as a trustworthy Plan IR."""


def _parse_fail(code: str, message: str, path: str = "$") -> NoReturn:
    raise PlanParseError(ContractIssue(path=path, code=code, message=message))


def _reject_constant(value: str) -> NoReturn:
    _parse_fail("non_finite", f"non-finite JSON number is not allowed: {value}")


def _object_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _parse_fail("duplicate_key", f"duplicate object key: {key}")
        result[key] = value
    return result


def _check_depth(value: object, current: int = 1) -> None:
    if current > MAX_PLAN_DEPTH:
        _parse_fail("depth", f"Plan IR exceeds the maximum depth of {MAX_PLAN_DEPTH}")
    if isinstance(value, Mapping):
        for item in value.values():
            _check_depth(item, current + 1)
    elif isinstance(value, list):
        for item in value:
            _check_depth(item, current + 1)


def parse_plan(raw: str | bytes | bytearray | Mapping[str, object]) -> PlanIR:
    """Parse untrusted planner output into a versioned PlanIR instance."""

    if isinstance(raw, Mapping):
        data: object = raw
    elif isinstance(raw, (str, bytes, bytearray)):
        encoded = raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)
        if len(encoded) > MAX_PLAN_BYTES:
            _parse_fail("size", f"Plan IR exceeds the {MAX_PLAN_BYTES}-byte limit")
        try:
            text = encoded.decode("utf-8")
        except UnicodeDecodeError as exc:
            _parse_fail("encoding", f"Plan IR must be UTF-8: {exc}")
        try:
            data = json.loads(
                text,
                object_pairs_hook=_object_without_duplicates,
                parse_constant=_reject_constant,
            )
        except PlanParseError:
            raise
        except json.JSONDecodeError as exc:
            _parse_fail("json", f"invalid JSON at line {exc.lineno}, column {exc.colno}")
    else:
        _parse_fail("type", "Plan IR must be a JSON object, string, or byte sequence")

    _check_depth(data)
    try:
        return PlanIR.from_dict(data)
    except ContractError as exc:
        raise PlanParseError(*exc.issues) from exc
