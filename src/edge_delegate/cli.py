"""Command-line entry points for the deterministic vertical slice."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from edge_delegate import __version__
from edge_delegate.contracts import (
    CapabilityCard,
    DeviceState,
    ExecutionBudget,
    PlanIR,
    PlanningRequest,
    PlanStep,
    Policy,
    Route,
    StepReference,
    ValueKind,
)
from edge_delegate.data import generate_records, validate_records, write_dataset
from edge_delegate.evaluation import EvaluationRunner
from edge_delegate.ir import check_plan, parse_plan
from edge_delegate.planner import (
    DEFAULT_MODEL_ID,
    FunctionGemmaPlanner,
    StaticPlanner,
    TransformersFunctionGemmaBackend,
)
from edge_delegate.runtime import Coordinator
from edge_delegate.simulator import ManualClock, SimulatedWorld
from edge_delegate.simulator.actuators import register_state_writer
from edge_delegate.simulator.sensors import register_state_sensor

MAX_CONTRACT_BYTES = 1024 * 1024


def _load_json(path: Path) -> object:
    payload = path.read_bytes()
    if len(payload) > MAX_CONTRACT_BYTES:
        raise ValueError(f"contract file exceeds {MAX_CONTRACT_BYTES} bytes: {path}")
    return json.loads(
        payload.decode("utf-8"),
        object_pairs_hook=_object_without_duplicates,
        parse_constant=_reject_json_constant,
    )


def _reject_json_constant(value: str):
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def _object_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _parse_now(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--now must include a timezone")
    return parsed.astimezone(UTC)


def _report_dict(report) -> dict[str, object]:
    return {
        "valid": report.valid,
        "issues": [
            {"path": item.path, "code": item.code, "message": item.message}
            for item in report.issues
        ],
        "estimated": {
            "total_latency_ms": report.total_latency_ms,
            "total_energy_mj": report.total_energy_mj,
            "peak_memory_bytes": report.peak_memory_bytes,
        },
    }


def _validate_command(args: argparse.Namespace) -> int:
    raw_cards = _load_json(args.capabilities)
    if not isinstance(raw_cards, list):
        raise ValueError("capabilities file must contain a JSON array of capability cards")
    cards = tuple(
        CapabilityCard.from_dict(item, f"$[{index}]") for index, item in enumerate(raw_cards)
    )
    state = DeviceState.from_dict(_load_json(args.state))
    policy = Policy.from_dict(_load_json(args.policy))
    plan = parse_plan(args.plan.read_bytes())
    report = check_plan(plan, cards, state, policy, now=_parse_now(args.now))
    print(json.dumps(_report_dict(report), indent=2, sort_keys=True))
    return 0 if report.valid else 2


def _demo_command(args: argparse.Namespace) -> int:
    del args
    world = SimulatedWorld(
        values={"environment.temperature_c": 24.5, "display.last_value": None},
        available_memory_bytes=128 * 1024 * 1024,
        clock=ManualClock(datetime.now(UTC)),
    )
    register_state_sensor(
        world,
        capability_id="sensor.temperature.read",
        state_key="environment.temperature_c",
        result_kind=ValueKind.NUMBER,
        description="Read the current ambient temperature in Celsius.",
    )
    register_state_writer(
        world,
        capability_id="display.value.show",
        state_key="display.last_value",
        value_kind=ValueKind.NUMBER,
        description="Show a numeric value on the local display.",
        permission="display.write",
    )
    request = PlanningRequest(
        request_id="demo-display-temperature",
        text="Show the current temperature on the local display.",
    )
    plan = PlanIR(
        request_id=request.request_id,
        route=Route.LOCAL,
        confidence=1.0,
        steps=(
            PlanStep(step_id="read_temperature", capability_id="sensor.temperature.read"),
            PlanStep(
                step_id="show_temperature",
                capability_id="display.value.show",
                arguments={"value": StepReference("read_temperature")},
                idempotency_key="demo-show-temperature",
            ),
        ),
    )
    policy = Policy(
        policy_id="demo-local-only",
        granted_permissions=frozenset({"display.write"}),
        budget=ExecutionBudget(max_steps=4),
    )
    coordinator = Coordinator(
        planner=StaticPlanner({request.request_id: plan}), world=world, policy=policy
    )
    result = coordinator.handle(request)
    output = {
        "status": result.status.value,
        "validation": None if result.validation is None else _report_dict(result.validation),
        "execution": (
            None
            if result.execution is None
            else {
                "status": result.execution.status.value,
                "steps": [
                    {
                        "step_id": item.step_id,
                        "capability_id": item.capability_id,
                        "status": item.status.value,
                    }
                    for item in result.execution.steps
                ],
                "final_output": result.execution.final_output,
            }
        ),
        "display_value": world.read("display.last_value"),
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if result.status.value == "executed" else 1


def _generate_data_command(args: argparse.Namespace) -> int:
    manifest = write_dataset(args.output, seed=args.seed)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if len(line.encode("utf-8")) > MAX_CONTRACT_BYTES:
                raise ValueError(f"JSONL line {line_number} exceeds the size limit")
            if not line.strip():
                continue
            value = json.loads(
                line,
                object_pairs_hook=_object_without_duplicates,
                parse_constant=_reject_json_constant,
            )
            if not isinstance(value, dict):
                raise ValueError(f"JSONL line {line_number} must be an object")
            records.append(value)
    return records


def _evaluate_command(args: argparse.Namespace) -> int:
    records = generate_records() if args.dataset is None else _load_jsonl(args.dataset)
    validate_records(records)
    if args.planner == "gold":
        plans = {
            str(record["record_id"]): PlanIR.from_dict(record["expected_plan"])
            for record in records
        }
        planner = StaticPlanner(plans)
    else:
        planner = FunctionGemmaPlanner(
            TransformersFunctionGemmaBackend(model_id=args.model_id),
            retrieval_limit=args.retrieval_limit,
            max_new_tokens=args.max_new_tokens,
        )
    report = EvaluationRunner(planner).evaluate(records)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
        print(json.dumps({"output": str(args.output), "metrics": report["metrics"]}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edge-delegate",
        description="Validate and execute typed edge plans against declared capabilities.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    demo = commands.add_parser("demo", help="run the deterministic local vertical slice")
    demo.set_defaults(handler=_demo_command)

    validate = commands.add_parser("validate", help="validate Plan IR without executing it")
    validate.add_argument("--capabilities", required=True, type=Path)
    validate.add_argument("--state", required=True, type=Path)
    validate.add_argument("--policy", required=True, type=Path)
    validate.add_argument("--plan", required=True, type=Path)
    validate.add_argument(
        "--now",
        help="timezone-aware ISO-8601 validation time; defaults to the current time",
    )
    validate.set_defaults(handler=_validate_command)

    generate_data = commands.add_parser(
        "generate-data",
        help="build the deterministic scenario dataset and FunctionGemma SFT export",
    )
    generate_data.add_argument("--output", required=True, type=Path)
    generate_data.add_argument("--seed", type=int, default=17)
    generate_data.set_defaults(handler=_generate_data_command)

    evaluate = commands.add_parser(
        "evaluate",
        help="evaluate the gold harness or a local FunctionGemma checkpoint",
    )
    evaluate.add_argument("--dataset", type=Path, help="JSONL dataset; defaults to generated cases")
    evaluate.add_argument("--planner", choices=("gold", "functiongemma"), default="gold")
    evaluate.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    evaluate.add_argument("--retrieval-limit", type=int, default=8)
    evaluate.add_argument("--max-new-tokens", type=int, default=1024)
    evaluate.add_argument("--output", type=Path)
    evaluate.set_defaults(handler=_evaluate_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
