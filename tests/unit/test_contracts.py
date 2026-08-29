"""Unit tests for strict contracts and their external JSON schemas."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from edge_delegate.contracts import (
    ApprovalGrant,
    CapabilityCard,
    ContractError,
    DeviceState,
    ExternalHandoff,
    PlanIR,
    Policy,
    ValueSpec,
)
from edge_delegate.ir import PlanParseError, canonicalize_plan, parse_plan

SCHEMA_ROOT = Path(__file__).parents[2] / "schemas"


def _schema(name: str) -> dict:
    return json.loads((SCHEMA_ROOT / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("schema_name", "instance"),
    [
        (
            "capability-card.v0.schema.json",
            {
                "schema_version": "capability-card.v0",
                "capability_id": "sensor.temperature.read",
                "version": "0.1.0",
                "description": "Read temperature.",
                "arguments": {},
                "result": {"kind": "number"},
                "side_effect": "read",
            },
        ),
        (
            "device-state.v0.schema.json",
            {
                "schema_version": "device-state.v0",
                "snapshot_id": "snapshot-1",
                "observed_at": "2026-01-01T12:00:00Z",
                "values": {"temperature": 24.5},
            },
        ),
        (
            "policy.v0.schema.json",
            {"schema_version": "policy.v0", "policy_id": "default"},
        ),
        (
            "plan-ir.v0.schema.json",
            {
                "schema_version": "plan-ir.v0",
                "request_id": "req-1",
                "route": "clarify",
                "clarification": "Which sensor should I use?",
            },
        ),
        (
            "handoff.v0.schema.json",
            {
                "schema_version": "handoff.v0",
                "request_id": "req-1",
                "reason": "Local parser lacks the required language coverage.",
                "task": "Extract the requested time range.",
                "context": {},
                "questions": ["What time range did the user specify?"],
                "included_privacy_classes": ["public"],
                "expires_at": "2026-01-01T12:05:00Z",
            },
        ),
    ],
)
def test_schema_is_valid_and_accepts_minimal_instance(schema_name: str, instance: dict) -> None:
    schema = _schema(schema_name)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(instance)


def test_contract_round_trips_match_schema(demo_world, demo_policy, demo_plan) -> None:
    instances = [
        (
            "capability-card.v0.schema.json",
            CapabilityCard.from_dict(demo_world.capability_cards[0].to_dict()).to_dict(),
        ),
        (
            "device-state.v0.schema.json",
            DeviceState.from_dict(demo_world.snapshot().to_dict()).to_dict(),
        ),
        ("policy.v0.schema.json", Policy.from_dict(demo_policy.to_dict()).to_dict()),
        ("plan-ir.v0.schema.json", PlanIR.from_dict(demo_plan.to_dict()).to_dict()),
    ]
    for schema_name, instance in instances:
        Draft202012Validator(_schema(schema_name), format_checker=FormatChecker()).validate(
            instance
        )


def test_plan_parser_rejects_duplicate_keys_and_non_finite_numbers() -> None:
    with pytest.raises(PlanParseError, match="duplicate object key"):
        parse_plan('{"schema_version":"plan-ir.v0","schema_version":"plan-ir.v0"}')
    with pytest.raises(PlanParseError, match="non-finite"):
        parse_plan(
            '{"schema_version":"plan-ir.v0","request_id":"r","route":"deny",'
            '"reason_codes":["unsafe"],"confidence":NaN}'
        )


def test_plan_parser_rejects_non_json_output_types() -> None:
    with pytest.raises(PlanParseError, match="JSON object, string, or byte sequence"):
        parse_plan(42)  # type: ignore[arg-type]


def test_value_spec_rejects_constraints_for_the_wrong_kind() -> None:
    with pytest.raises(ContractError, match="enum values"):
        ValueSpec.from_dict({"kind": "number", "enum": ["not-a-number"]}, "$.value")
    with pytest.raises(ContractError, match="numeric bounds"):
        ValueSpec.from_dict({"kind": "string", "minimum": 1}, "$.value")


def test_handoff_requires_an_explicit_question() -> None:
    with pytest.raises(ContractError, match="at least one external question"):
        ExternalHandoff.from_dict(
            {
                "schema_version": "handoff.v0",
                "request_id": "req-1",
                "reason": "local limit",
                "task": "parse input",
                "context": {},
                "questions": [],
                "included_privacy_classes": ["public"],
                "expires_at": "2026-01-01T12:05:00Z",
            }
        )


def test_contracts_reject_unknown_fields() -> None:
    with pytest.raises(ContractError) as exc_info:
        Policy.from_dict(
            {"schema_version": "policy.v0", "policy_id": "p", "model_can_override": True}
        )
    assert exc_info.value.issues[0].code == "unknown_fields"


def test_plan_canonicalization_is_stable(demo_plan) -> None:
    canonical = canonicalize_plan(demo_plan)
    reparsed = parse_plan(canonical)
    assert reparsed == demo_plan
    assert canonicalize_plan(reparsed) == canonical


def test_approval_is_request_scoped_and_expires() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    grant = ApprovalGrant(
        grant_id="grant-1",
        request_id="req-1",
        capability_id="relay.set",
        plan_sha256="a" * 64,
        expires_at=now + timedelta(minutes=1),
    )
    assert grant.is_valid_for("req-1", "relay.set", "a" * 64, now)
    assert not grant.is_valid_for("req-2", "relay.set", "a" * 64, now)
    assert not grant.is_valid_for("req-1", "relay.set", "b" * 64, now)
    assert not grant.is_valid_for("req-1", "relay.set", "a" * 64, now + timedelta(minutes=2))
