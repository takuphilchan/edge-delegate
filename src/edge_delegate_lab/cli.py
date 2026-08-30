"""Host-side commands for datasets, model plugins, training, and evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from edge_delegate import __version__
from edge_delegate.contracts import PlanIR
from edge_delegate.data import build_record_world, generate_records, validate_records, write_dataset
from edge_delegate.evaluation import EvaluationRunner, ModelDoctor, select_controlled_records
from edge_delegate.model_plugins import (
    ComputeRequest,
    ModelArtifactManifest,
    TrainableModelPlugin,
    available_model_plugins,
    conservative_compute_plan,
)
from edge_delegate.planner import StaticPlanner

from .client import ClientProfile, QueryClient, interactive_help, render_result
from .compute import detect_hardware_inventory

MAX_RECORD_BYTES = 1024 * 1024


def _reject_constant(value: str):
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def _without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if len(line.encode("utf-8")) > MAX_RECORD_BYTES:
                raise ValueError(f"JSONL line {line_number} exceeds the size limit")
            if not line.strip():
                continue
            value = json.loads(
                line,
                object_pairs_hook=_without_duplicates,
                parse_constant=_reject_constant,
            )
            if not isinstance(value, dict):
                raise ValueError(f"JSONL line {line_number} must be an object")
            records.append(value)
    return records


def _load_json_object(path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    if len(payload) > MAX_RECORD_BYTES:
        raise ValueError(f"plugin settings exceed the size limit: {path}")
    value = json.loads(
        payload.decode("utf-8"),
        object_pairs_hook=_without_duplicates,
        parse_constant=_reject_constant,
    )
    if not isinstance(value, dict):
        raise ValueError("plugin settings must be a JSON object")
    return value


def _plugin_settings(args: argparse.Namespace) -> dict[str, object]:
    settings = {} if args.plugin_settings is None else _load_json_object(args.plugin_settings)
    for name in ("model_id", "retrieval_limit", "max_new_tokens"):
        value = getattr(args, name, None)
        if value is not None:
            settings[name] = value
    return settings


def _records(path: Path | None) -> list[dict[str, object]]:
    records = generate_records() if path is None else _load_jsonl(path)
    validate_records(records)
    return records


def _generate_data_command(args: argparse.Namespace) -> int:
    registry = available_model_plugins()
    requested = args.export_plugin or ["functiongemma"]
    exporters = []
    for plugin_id in requested:
        plugin = registry.get(plugin_id)
        if not isinstance(plugin, TrainableModelPlugin):
            raise ValueError(f"model plugin {plugin_id!r} does not provide training exports")
        exporters.append(plugin)
    manifest = write_dataset(args.output, seed=args.seed, exporters=exporters)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


def _evaluate_command(args: argparse.Namespace) -> int:
    records = _records(args.dataset)
    if args.planner == "gold":
        planner = StaticPlanner(
            {
                str(record["record_id"]): PlanIR.from_dict(record["expected_plan"])
                for record in records
            }
        )
    else:
        registry = available_model_plugins()
        try:
            plugin = registry.get(args.planner)
        except KeyError as exc:
            available = ", ".join(registry.plugin_ids())
            raise ValueError(
                f"unknown model plugin {args.planner!r}; available: {available}"
            ) from exc
        planner = plugin.create_planner(
            artifact_path=args.adapter,
            settings=_plugin_settings(args),
        )
    report = EvaluationRunner(planner, execution_harness=build_record_world).evaluate(records)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
        print(json.dumps({"output": str(args.output), "metrics": report["metrics"]}, indent=2))
    return 0


def _model_doctor_command(args: argparse.Namespace) -> int:
    if args.cases < 1:
        raise ValueError("--cases must be positive")
    records = select_controlled_records(_records(args.dataset))[: args.cases]
    if not records:
        raise ValueError("the dataset does not contain a supported diagnostic route")
    registry = available_model_plugins()
    plugin = registry.get(args.plugin)
    session = plugin.create_diagnostic_session(
        artifact_path=args.adapter,
        settings=_plugin_settings(args),
    )
    report = ModelDoctor(session).run(
        records,
        include_raw_output=not args.omit_raw_output,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    output = args.output or Path(f"artifacts/model-doctor/{args.plugin}-smoke.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8", newline="\n")
    summary = {
        "output": str(output),
        "model": report["model"],
        "operational": report["operational"],
        "quality_smoke": report["quality_smoke"],
        "latency": report["latency"],
        "failure_counts": report["failure_counts"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if report["operational"]["all_generations_succeeded"] else 2


def _train_command(args: argparse.Namespace) -> int:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("training requires the training dependency group") from exc
    header = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    if not isinstance(header, dict) or not isinstance(header.get("plugin_id"), str):
        raise ValueError("training config must declare a string plugin_id")
    plugin_id = args.plugin or header["plugin_id"]
    registry = available_model_plugins()
    plugin = registry.get(plugin_id)
    if not isinstance(plugin, TrainableModelPlugin):
        raise ValueError(f"model plugin {plugin_id!r} is inference-only")
    report = dict(
        plugin.train_from_config(
            config_path=args.config,
            preflight_only=args.preflight_only,
        )
    )
    summary = {
        "status": report["status"],
        "purpose": report["purpose"],
        "preflight": report["preflight"],
        "hardware_inventory": report["hardware_inventory"],
        "resolved_compute_plan": report["resolved_compute_plan"],
    }
    if report["status"] == "completed":
        summary.update(
            {
                "adapter": report["adapter"],
                "duration_seconds": report["duration_seconds"],
                "train_metrics": report["train_metrics"],
                "eval_metrics": report["eval_metrics"],
                "compute_telemetry": report["compute_telemetry"],
            }
        )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _models_command(args: argparse.Namespace) -> int:
    del args
    registry = available_model_plugins()
    result = []
    for plugin_id in registry.plugin_ids():
        plugin = registry.get(plugin_id)
        result.append(
            {
                "plugin": asdict(plugin.descriptor),
                "compute_capabilities": asdict(plugin.compute_capabilities),
            }
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _compute_inspect_command(args: argparse.Namespace) -> int:
    del args
    print(json.dumps(asdict(detect_hardware_inventory()), indent=2, sort_keys=True))
    return 0


def _compute_plan_command(args: argparse.Namespace) -> int:
    registry = available_model_plugins()
    plugin = registry.get(args.plugin)
    plan = conservative_compute_plan(
        detect_hardware_inventory(),
        plugin.compute_capabilities,
        ComputeRequest(
            effective_batch_size=args.effective_batch_size,
            max_context_tokens=args.max_context_tokens,
            requested_precision=args.precision,
            requested_attention_backend=args.attention_backend,
            maximum_vram_fraction=args.maximum_vram_fraction,
        ),
    )
    print(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
    return 0


def _artifact_verify_command(args: argparse.Namespace) -> int:
    root = args.artifact.resolve()
    manifest_path = root / "edge-delegate-artifact.json"
    manifest = ModelArtifactManifest.read(manifest_path)
    plugin_id = args.plugin or manifest.plugin_id
    plugin = available_model_plugins().get(plugin_id)
    manifest.ensure_plugin_compatible(plugin.descriptor)
    manifest.verify_files(root)
    print(
        json.dumps(
            {
                "artifact_root": str(root),
                "manifest": manifest.to_dict(),
                "valid": True,
                "verified_adapter_files": len(manifest.adapter_files),
                "verified_tokenizer_files": len(manifest.tokenizer_files),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _query_client(args: argparse.Namespace) -> QueryClient:
    profile = ClientProfile.load(args.profile)
    plugin = available_model_plugins().get(args.plugin)
    session = plugin.create_diagnostic_session(
        artifact_path=args.adapter,
        settings=_plugin_settings(args),
    )
    return QueryClient(
        session,
        profile,
        locale=args.locale,
    )


def _plan_command(args: argparse.Namespace) -> int:
    client = _query_client(args)
    result = client.query(args.text, include_raw_output=not args.omit_raw_output)
    print(render_result(result))
    return 0 if result["valid"] else 2


def _interactive_command(args: argparse.Namespace) -> int:
    client = _query_client(args)
    include_raw_output = not args.omit_raw_output
    model_id = client.model_info.get("model_id", args.plugin)
    print(f"Loaded {model_id}")
    print(f"Profile: {client.profile.root}")
    print(interactive_help())

    def run_query(text: str) -> None:
        result = client.query(text, include_raw_output=include_raw_output)
        print(render_result(result))

    if args.text is not None:
        run_query(args.text)
    while True:
        try:
            text = input("edge-delegate> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not text:
            continue
        if text in {"/quit", "/exit"}:
            return 0
        if text == "/help":
            print(interactive_help())
            continue
        if text == "/context":
            print(render_result(client.profile.to_dict()))
            continue
        if text.startswith("/raw"):
            parts = text.split()
            if len(parts) != 2 or parts[1] not in {"on", "off"}:
                print("usage: /raw on|off")
                continue
            include_raw_output = parts[1] == "on"
            print(f"raw model output: {'on' if include_raw_output else 'off'}")
            continue
        if text.startswith("/"):
            print("unknown command; use /help")
            continue
        run_query(text)


def _add_query_arguments(
    command: argparse.ArgumentParser,
    *,
    text_required: bool,
) -> None:
    command.add_argument("--plugin", default="functiongemma")
    command.add_argument("--plugin-settings", type=Path)
    command.add_argument("--model-id")
    command.add_argument("--adapter")
    command.add_argument("--retrieval-limit", type=int)
    command.add_argument("--max-new-tokens", type=int)
    command.add_argument("--profile", required=True, type=Path)
    command.add_argument("--locale", default="en")
    command.add_argument("--text", required=text_required)
    command.add_argument("--omit-raw-output", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edge-delegate-lab",
        description="Build, train, and evaluate Edge Delegate model plugins.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    generate = commands.add_parser("generate-data", help="build canonical and model exports")
    generate.add_argument("--output", required=True, type=Path)
    generate.add_argument("--seed", type=int, default=17)
    generate.add_argument(
        "--export-plugin",
        action="append",
        help="model plugin training export to create; repeat for multiple plugins",
    )
    generate.set_defaults(handler=_generate_data_command)

    evaluate = commands.add_parser("evaluate", help="evaluate gold or an installed model plugin")
    evaluate.add_argument("--dataset", type=Path)
    evaluate.add_argument("--planner", default="gold")
    evaluate.add_argument("--plugin-settings", type=Path)
    evaluate.add_argument("--model-id")
    evaluate.add_argument("--adapter")
    evaluate.add_argument("--retrieval-limit", type=int)
    evaluate.add_argument("--max-new-tokens", type=int)
    evaluate.add_argument("--output", type=Path)
    evaluate.set_defaults(handler=_evaluate_command)

    doctor = commands.add_parser("model-doctor", help="run model-plugin integration diagnostics")
    doctor.add_argument("--plugin", default="functiongemma")
    doctor.add_argument("--plugin-settings", type=Path)
    doctor.add_argument("--dataset", type=Path)
    doctor.add_argument("--model-id")
    doctor.add_argument("--adapter")
    doctor.add_argument("--retrieval-limit", type=int)
    doctor.add_argument("--max-new-tokens", type=int)
    doctor.add_argument("--cases", type=int, default=6)
    doctor.add_argument(
        "--output",
        type=Path,
    )
    doctor.add_argument("--omit-raw-output", action="store_true")
    doctor.set_defaults(handler=_model_doctor_command)

    train = commands.add_parser("train", help="preflight or train an installed model plugin")
    train.add_argument("--plugin", help="override and verify the config's plugin_id")
    train.add_argument("--config", required=True, type=Path)
    train.add_argument("--preflight-only", action="store_true")
    train.set_defaults(handler=_train_command)

    models = commands.add_parser("models", help="list installed model plugins")
    models.set_defaults(handler=_models_command)

    inspect = commands.add_parser("compute-inspect", help="inspect host compute without a model")
    inspect.set_defaults(handler=_compute_inspect_command)

    compute = commands.add_parser("compute-plan", help="resolve a conservative compute plan")
    compute.add_argument("--plugin", default="functiongemma")
    compute.add_argument("--effective-batch-size", type=int, default=4)
    compute.add_argument("--max-context-tokens", type=int, default=2048)
    compute.add_argument("--precision", default="auto")
    compute.add_argument("--attention-backend", default="auto")
    compute.add_argument("--maximum-vram-fraction", type=float, default=0.88)
    compute.set_defaults(handler=_compute_plan_command)

    artifact = commands.add_parser(
        "artifact-verify",
        help="verify a portable adapter manifest and every recorded file",
    )
    artifact.add_argument("--artifact", required=True, type=Path)
    artifact.add_argument("--plugin", help="optionally require a specific plugin ID")
    artifact.set_defaults(handler=_artifact_verify_command)

    plan = commands.add_parser(
        "plan",
        help="generate and validate one query without executing capabilities",
    )
    _add_query_arguments(plan, text_required=True)
    plan.set_defaults(handler=_plan_command)

    interactive = commands.add_parser(
        "interactive",
        help="keep a model loaded for non-executing interactive queries",
    )
    _add_query_arguments(interactive, text_required=False)
    interactive.set_defaults(handler=_interactive_command)
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
