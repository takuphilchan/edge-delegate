"""Assemble a fixed, exposed review pilot. Never generate training exports or approvals."""

import argparse
import json
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

from edge_delegate.contracts import PlanIR, PlanningRequest, PlanStep, Route, StepReference
from edge_delegate.data.fingerprint import content_fingerprint, dataset_fingerprint
from edge_delegate.data.reference_oracle import DISPLAY, ORACLE_VERSION, READ, reference_effects
from edge_delegate.data.review import REVIEW_RECORD_VERSION, SPLITS, validate_review_dataset
from edge_delegate.simulator import ManualClock
from edge_delegate.simulator.examples import local_display

from .jsonio import MAX_RECORD_BYTES, reject_constant, without_duplicates

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
CONTEXTS = {
    "normal": "Fresh snapshot; both capabilities available; display.write permission granted.",
    "no_display_permission": "Fresh snapshot; both capabilities available; display.write permission absent.",
    "no_sensor": "Fresh snapshot; temperature-read capability unavailable; display available and permitted.",
    "no_display": "Fresh snapshot; display capability unavailable; temperature read available.",
    "stale": "Both capabilities and display permission present, but the saved snapshot is older than the permitted age.",
}


def _plan(identifier, task, parameters, status):
    """Author expected plan structure from fixture rules, without TaskCatalog.compile."""
    route = {
        "executed": Route.LOCAL,
        "invalid_plan": Route.LOCAL,
        "denied": Route.DENY,
        "clarification_required": Route.CLARIFY,
    }[status]
    steps = ()
    if route is Route.LOCAL:
        read = PlanStep("read_temperature", READ)
        if task == "read_temperature":
            steps = (read,)
        elif task == "display_number":
            steps = (PlanStep("display", DISPLAY, parameters),)
        elif task == "show_temperature":
            steps = (read, PlanStep("display", DISPLAY, {"value": StepReference(read.step_id)}))
        else:
            raise ValueError("non-action task cannot have a local plan")
    return PlanIR(
        identifier,
        route,
        steps=tuple(
            replace(
                step,
                timeout_ms=500,
                idempotency_key=sha256(f"{identifier}:{step.step_id}".encode()).hexdigest(),
            )
            for step in steps
        ),
        clarification="Please specify the task, reference, or supported numeric value."
        if route is Route.CLARIFY
        else None,
        reason_codes=("ambiguous_request",)
        if route is Route.CLARIFY
        else ("unsupported_request" if task == "deny" else "capability_unavailable",)
        if route is Route.DENY
        else (),
    )


def build_pilot(source):
    if (
        source.get("schema_version") != "edge-pilot-source.v1"
        or source.get("exposure") != "development"
    ):
        raise ValueError("pilot source must declare its version and development exposure")
    if source.get("assembly_seed") != 0:
        raise ValueError("pilot assembly is deterministic and requires assembly_seed 0")
    records, sources = [], {}
    families = set()
    for group in source["groups"]:
        family = "pilot-" + group["family"]
        if family in families:
            raise ValueError("duplicate pilot family")
        families.add(family)
        sources[family] = {
            "family": family,
            "contributor": source["author"],
            "exposure": "development",
            "rights": "AI-assisted project draft; distribution terms require owner review.",
            "source_sha256": content_fingerprint(source),
            "group_sha256": content_fingerprint(group),
        }
        for case in group["cases"]:
            index = len(records)
            identifier = f"pilot-{index + 1:03d}"
            task = case.get("task", group["task"])
            parameters = {"value": case["value"]} if task == "display_number" else {}
            if task != "display_number" and "value" in case:
                raise ValueError("non-display task cannot carry a value")
            context = case.get("context", "normal")
            if context not in CONTEXTS:
                raise ValueError("unknown pilot context")
            world, policy = local_display(clock=ManualClock(NOW))
            temperature = 18.25 + (index % 13) * 0.5
            previous = case.get("display_before", -40 + index % 11)
            if previous == "temperature":
                previous = temperature
            world.write("environment.temperature_c", temperature)
            world.write("display.last_value", previous)
            state, cards = world.snapshot(), world.capability_cards
            if context == "no_display_permission":
                policy = replace(policy, granted_permissions=frozenset())
            if context in {"no_sensor", "no_display"}:
                missing = READ if context == "no_sensor" else DISPLAY
                cards = tuple(card for card in cards if card.capability_id != missing)
            if context == "stale":
                state = replace(
                    state, observed_at=NOW - timedelta(seconds=policy.max_state_age_seconds + 1)
                )
            # Expected status is declared by the review scenario, not observed by executing it.
            status = "executed"
            if task in {"deny", "clarify"}:
                status = "denied" if task == "deny" else "clarification_required"
            elif context == "stale":
                status = "invalid_plan"
            elif (
                (
                    context == "no_display_permission"
                    and task in {"display_number", "show_temperature"}
                )
                or (context == "no_sensor" and task in {"read_temperature", "show_temperature"})
                or (context == "no_display" and task in {"display_number", "show_temperature"})
            ):
                status = "denied"
            decision = {"task": task, "parameters": parameters}
            record = {
                "schema_version": REVIEW_RECORD_VERSION,
                "record_id": identifier,
                "request": PlanningRequest(identifier, case["text"]).to_dict(),
                "capabilities": [card.to_dict() for card in cards],
                "state": state.to_dict(),
                "policy": policy.to_dict(),
                "evaluation_at": NOW.isoformat(),
                "expected_task": decision,
                "expected_plan": _plan(identifier, task, parameters, status).to_dict(),
                "expected_outcome": status,
                "expected_effects": reference_effects(
                    decision, state.values, status, [c.capability_id for c in cards]
                ),
                "metadata": {
                    "scenario_group": family,
                    "template_id": family,
                    "paraphrase_cluster": family,
                    "scenario_family": task,
                    "device_family": "local-display.v1",
                    "category": case.get("category", group["category"]),
                    "catalog_version": "local-display.v1",
                    "label_policy": source["label_policy"],
                    "oracle_version": ORACLE_VERSION,
                    "context_description": CONTEXTS[context],
                    "context_variant": context,
                    "note": case.get("note", ""),
                    "sources_sha256": content_fingerprint({family: sources[family]}),
                    "provenance": {
                        "source_ids": [family],
                        "parent_ids": [],
                        "method": "generated",
                        "generator": source["generator"],
                        "seed": 0,
                    },
                    "review": {
                        "status": "pending",
                        "author": source["author"],
                        "author_decision": decision,
                        "rationale": group["rationale"],
                    },
                },
            }
            if status in {"denied", "invalid_plan"} and task not in {"deny", "clarify"}:
                record["metadata"]["restriction_reason"] = CONTEXTS[context]
            record["content_sha256"] = content_fingerprint(record)
            records.append(record)
    if len(records) != 80:
        raise ValueError("this pilot recipe requires exactly 80 authored examples")
    # All examples are exposed development drafts. Do not invent fresh held-out evidence.
    splits = {name: records if name == "train" else [] for name in SPLITS}
    manifest = {
        "schema_version": "edge-dataset-review.v1",
        "catalog": "local-display.v1",
        "oracle": ORACLE_VERSION,
        "label_policy": source["label_policy"],
        "sources": sources,
        "split_counts": {name: len(rows) for name, rows in splits.items()},
        "split_sha256": {name: dataset_fingerprint(rows) for name, rows in splits.items()},
        "source_sha256": content_fingerprint(source),
        "purpose": "Exposed pilot for label review, not training or independent evaluation.",
        "policy_approved": False,
        "independent_review_complete": False,
    }
    report = validate_review_dataset(splits, manifest, require_review=False)
    return splits, manifest, report


def render_review(records, *, answers=False):
    title = (
        "Proposed answers - pending independent review"
        if answers
        else "Independent review worksheet"
    )
    lines = [
        f"# {title}",
        "",
        "80 exposed development examples. Not a frozen test or training release.",
        "",
        "Each request is independent. Read [POLICY.md](POLICY.md) first. All contexts are saved simulator snapshots.",
        "",
    ]
    if not answers:
        lines += [
            "Label each request before opening PROPOSED-ANSWERS.md or train.jsonl. Do not run the candidate model to choose labels.",
            "",
            "Reviewer alias: ______  Date: ______  Policy reservations: ______",
            "",
            "Use read_temperature, display_number, show_temperature, clarify, or deny; flag any disputed rule.",
            "",
        ]
    lines += [
        "Review in batches of ten: "
        + " | ".join(
            f"[{index + 1:03d}-{min(index + 10, len(records)):03d}](#{records[index]['record_id']})"
            for index in range(0, len(records), 10)
        ),
        "",
    ]
    for record in records:
        before = record["state"]["values"]
        lines += [
            f"## {record['record_id']}",
            "",
            f"> {record['request']['text']}",
            "",
            record["metadata"]["context_description"],
            "",
            f"Before: temperature = {before['environment.temperature_c']} Celsius; screen = {before['display.last_value']}.",
            "",
        ]
        if answers:
            effects = record["expected_effects"]
            calls = []
            for step in record["expected_plan"]["steps"]:
                arguments = ", ".join(
                    f"{key} = result of {value['$ref']}"
                    if isinstance(value, dict) and "$ref" in value
                    else f"{key} = {json.dumps(value)}"
                    for key, value in step["arguments"].items()
                )
                calls.append(f"{len(calls) + 1}. `{step['capability_id']}({arguments})`")
            lines += [
                f"Proposed task: `{json.dumps(record['expected_task'], sort_keys=True)}`",
                f"Expected runtime status: `{record['expected_outcome']}`",
                "",
                "Expected calls, in order:",
                "",
                *(calls or ["None. No read or write may be invoked."]),
                "",
                f"After: temperature = {effects['state']['environment.temperature_c']} Celsius; screen = {effects['state']['display.last_value']}.",
                f"Returned value: `{json.dumps(effects['final_output'])}`. No other state change allowed.",
                "Forbidden calls: "
                + (
                    ", ".join(effects["forbidden_invocations"])
                    or "no additional calls beyond the sequence above"
                )
                + ".",
                "",
                record["metadata"]["review"]["rationale"],
                record["metadata"]["note"],
                "",
            ]
        else:
            lines += [
                "- Intended task and parameters: ______",
                "- Execute / clarify / deny / invalid snapshot: ______",
                "- Allowed calls, arguments, and order: ______",
                "- Expected final screen value and returned value: ______",
                "- Forbidden calls; ambiguities or policy objections: ______",
                "",
            ]
    return "\n".join(lines)


def write_pilot(source_path, output):
    payload = source_path.read_bytes()
    if len(payload) > MAX_RECORD_BYTES:
        raise ValueError("pilot source exceeds size limit")
    source = json.loads(
        payload, object_pairs_hook=without_duplicates, parse_constant=reject_constant
    )
    splits, manifest, report = build_pilot(source)
    policy = source_path.with_name("POLICY.md").read_text(encoding="utf-8")
    manifest["policy_document_sha256"] = sha256(policy.encode("utf-8")).hexdigest()
    # Never replace a reviewer's work, even if an existing directory appears empty.
    output.mkdir(parents=True, exist_ok=False)
    for name, rows in splits.items():
        (output / f"{name}.jsonl").write_text(
            "".join(json.dumps(row, sort_keys=True, allow_nan=False) + "\n" for row in rows),
            encoding="utf-8",
        )
    for name, value in (("manifest.json", manifest), ("draft-check.json", report)):
        (output / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    (output / "POLICY.md").write_text(policy, encoding="utf-8")
    (output / "REVIEW.md").write_text(render_review(splits["train"]), encoding="utf-8")
    (output / "PROPOSED-ANSWERS.md").write_text(
        render_review(splits["train"], answers=True), encoding="utf-8"
    )
    return {
        "output": str(output),
        "record_count": 80,
        "accepted_count": 0,
        "categories": dict(Counter(r["metadata"]["category"] for r in splits["train"])),
        "training_eligible": False,
        "held_out_cases": 0,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(write_pilot(args.source, args.output), indent=2))
        return 0
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
