"""Declarative task-effect assertions; dataset content is never executable code."""

from collections.abc import Mapping, Sequence

from edge_delegate.contracts._validation import json_value


def _equal(actual, expected):
    # JSON numbers permit 12 and 12.0; booleans must never equal numeric 0/1.
    if type(actual) in {int, float} and type(expected) in {int, float}:
        return actual == expected
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            _equal(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _equal(a, b) for a, b in zip(actual, expected, strict=True)
        )
    return actual == expected


def check_effects(
    expected: object,
    *,
    state: Mapping[str, object],
    final_output: object,
    invocations: Sequence[str],
) -> tuple[bool, tuple[str, ...]]:
    if not isinstance(expected, dict):
        raise ValueError("expected_effects must be an object")
    allowed = {"state", "exact_state", "final_output", "invocations", "forbidden_invocations"}
    if set(expected) - allowed or not {"state", "invocations"} <= set(expected):
        raise ValueError(
            "expected_effects requires state and invocations; unknown fields forbidden"
        )
    values = json_value(expected["state"], "$.expected_effects.state")
    if not isinstance(values, dict):
        raise ValueError("expected state must be an object")
    if "exact_state" in expected and type(expected["exact_state"]) is not bool:
        raise ValueError("exact_state must be a boolean")
    for name in ("invocations", "forbidden_invocations"):
        items = expected.get(name, [])
        if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
            raise ValueError(f"{name} must be a list of capability IDs")
    issues = []
    if expected.get("exact_state", False) and set(state) != set(values):
        issues.append("state_keys")
    for key, value in values.items():
        if key not in state or not _equal(state[key], value):
            issues.append(f"state:{key}")
    if "final_output" in expected and not _equal(final_output, expected["final_output"]):
        issues.append("final_output")
    if list(invocations) != expected["invocations"]:
        issues.append("invocations")
    if set(invocations) & set(expected.get("forbidden_invocations", [])):
        issues.append("forbidden_invocations")
    return not issues, tuple(issues)
