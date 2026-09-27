"""Dataset contract and consistency checks."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from edge_delegate.contracts import (
    CapabilityCard,
    DeviceState,
    PlanIR,
    PlanningRequest,
    Policy,
    Route,
)
from edge_delegate.ir import check_plan

from .fingerprint import content_fingerprint


def validate_record(record: dict[str, object]) -> None:
    required = {
        "schema_version",
        "record_id",
        "request",
        "capabilities",
        "state",
        "policy",
        "expected_plan",
        "expected_outcome",
        "metadata",
        "content_sha256",
    }
    missing = required - record.keys()
    if missing:
        raise ValueError(f"dataset record missing fields: {', '.join(sorted(missing))}")
    if record["schema_version"] not in {"edge-delegate-dataset.v0", "edge-delegate-dataset.v1"}:
        raise ValueError("unsupported dataset record version")
    request = PlanningRequest.from_dict(record["request"])
    plan = PlanIR.from_dict(record["expected_plan"])
    if request.request_id != plan.request_id or record["record_id"] != request.request_id:
        raise ValueError("record, request, and expected-plan identifiers must match")
    expected_outcome = {
        Route.LOCAL: "executed",
        Route.HYBRID: "external_required",
        Route.EXTERNAL: "external_required",
        Route.CLARIFY: "clarification_required",
        Route.DEFER: "deferred",
        Route.DENY: "denied",
    }[plan.route]
    if record["expected_outcome"] != expected_outcome and not (
        record["schema_version"] == "edge-delegate-dataset.v1"
        and record["expected_outcome"] == "invalid_plan"
    ):
        raise ValueError("expected outcome is inconsistent with the expected route")
    raw_cards = record["capabilities"]
    if not isinstance(raw_cards, list):
        raise ValueError("capabilities must be a list")
    cards = tuple(
        CapabilityCard.from_dict(card, f"$.capabilities[{index}]")
        for index, card in enumerate(raw_cards)
    )
    state = DeviceState.from_dict(record["state"])
    policy = Policy.from_dict(record["policy"])
    now = (
        datetime.fromisoformat(record["evaluation_at"])
        if "evaluation_at" in record
        else state.observed_at
    )
    report = check_plan(plan, cards, state, policy, now=now)
    expected_valid = record["expected_outcome"] != "invalid_plan"
    if report.valid != expected_valid:
        raise ValueError("expected plan fails deterministic validation")
    if record["schema_version"] == "edge-delegate-dataset.v1":
        from edge_delegate.evaluation.outcomes import check_effects
        from edge_delegate.planner.tasks import TaskDecision

        TaskDecision.from_dict(record["expected_task"])
        check_effects(
            record["expected_effects"], state=state.values, final_output=None, invocations=[]
        )
    unsigned = dict(record)
    claimed = unsigned.pop("content_sha256")
    if claimed != content_fingerprint(unsigned):
        raise ValueError("dataset record content fingerprint does not match")
    metadata = record["metadata"]
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
    for field in ("template_id", "scenario_family", "device_family", "paraphrase_cluster"):
        if not metadata.get(field):
            raise ValueError(f"metadata field is required: {field}")


def validate_records(records: Iterable[dict[str, object]]) -> None:
    identifiers: set[object] = set()
    for record in records:
        validate_record(record)
        if record["record_id"] in identifiers:
            raise ValueError(f"duplicate record id: {record['record_id']}")
        identifiers.add(record["record_id"])
