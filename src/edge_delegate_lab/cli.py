"""Host-side commands for datasets, model plugins, training, and evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from edge_delegate import __version__
from edge_delegate.contracts import PlanIR, PlanningRequest
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

from .client import QueryClient, interactive_help
from .compute import detect_hardware_inventory
from .jsonio import MAX_RECORD_BYTES
from .jsonio import load_jsonl as _load_jsonl
from .jsonio import reject_constant as _reject_constant
from .jsonio import without_duplicates as _without_duplicates
from .presentation import render_profile, render_query, render_result, render_simulation
from .profiles import ClientProfile
from .simulation import run_simulation


def _load_json_object(path: Path, *, max_bytes=MAX_RECORD_BYTES) -> dict[str, object]:
    with path.open("rb") as stream:
        payload = stream.read(max_bytes + 1)
    if len(payload) > max_bytes:
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
    requested = args.export_plugin or (
        ["functiongemma-tasks", "task-classifier"]
        if args.dataset_version == "v1"
        else ["functiongemma"]
    )
    exporters = []
    for plugin_id in requested:
        plugin = registry.get(plugin_id)
        if not isinstance(plugin, TrainableModelPlugin):
            raise ValueError(f"model plugin {plugin_id!r} does not provide training exports")
        exporters.append(plugin)
    if args.dataset_version == "v1":
        from edge_delegate.data.tasks import write_task_dataset

        manifest = write_task_dataset(args.output, seed=args.seed, exporters=exporters)
    else:
        manifest = write_dataset(args.output, seed=args.seed, exporters=exporters)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


def _review_data_command(args: argparse.Namespace) -> int:
    from edge_delegate.data.review import SPLITS, validate_review_dataset

    from .review_workspace import render_review_status, verify_policy_document

    manifest = _load_json_object(args.directory / "manifest.json")
    policy_document = verify_policy_document(args.directory, manifest)
    splits = {name: _load_jsonl(args.directory / f"{name}.jsonl") for name in SPLITS}
    report = validate_review_dataset(splits, manifest, require_review=not args.allow_pending)
    report["policy_document"] = policy_document
    print(
        render_review_status(report)
        if args.format == "text"
        else json.dumps(report, indent=2, sort_keys=True)
    )
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
    report["model_identity"] = _model_identity(args.planner, args.adapter, _plugin_settings(args))
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
        print(json.dumps({"output": str(args.output), "metrics": report["metrics"]}, indent=2))
    return 0


def _model_identity(plugin_id, artifact, settings=None):
    from .evidence import model_identity

    return model_identity(plugin_id, artifact, settings)


def _audit_validation_command(args):
    from .validation_audit import audit_command

    return audit_command(
        dataset=args.dataset,
        output=args.output,
        plugin_id=args.plugin,
        artifact=args.adapter,
        settings=_plugin_settings(args),
        include_sensitive=args.include_sensitive,
    )


def _benchmark_command(args):
    import time

    from edge_delegate.adapters.unix import UnixGateway
    from edge_delegate.contracts import Policy

    from .benchmark import benchmark
    from .gateway import GatewaySession
    from .latency_profile import TracedDevice, storage_info

    started = time.perf_counter()
    model = (
        available_model_plugins()
        .get(args.plugin)
        .create_diagnostic_session(artifact_path=args.adapter, settings=_plugin_settings(args))
    )
    load_ms = (time.perf_counter() - started) * 1000
    session = GatewaySession(
        model.planner,
        TracedDevice(UnixGateway(args.socket)),
        Policy.from_dict(_load_json_object(args.policy)),
        journal_path=args.journal,
        diagnostics=model,
    )
    metadata = dict(
        storage=storage_info(args.journal.parent),
        model_load_ms=load_ms,
        model_info=dict(model.model_info),
        model_identity=_model_identity(args.plugin, args.adapter, _plugin_settings(args)),
        artifact_size_bytes=(
            sum(path.stat().st_size for path in Path(args.adapter).rglob("*") if path.is_file())
            if args.adapter
            else None
        ),
        hardware_inventory=asdict(detect_hardware_inventory()),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def checkpoint(partial):
        path = args.output.with_suffix(".partial.json")
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({**partial, **metadata}, indent=2, default=str) + "\n", encoding="utf-8"
        )
        temporary.replace(path)

    report = benchmark(
        session,
        count=args.count,
        runs=args.runs,
        progress=lambda run, count: print(
            f"Benchmark run {run}: {count} requests", file=sys.stderr
        ),
        checkpoint=checkpoint,
    )
    report.update(metadata)
    args.output.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "runs": [
                    {key: value for key, value in run.items() if key != "samples"}
                    for run in report["runs"]
                ],
            },
            indent=2,
        )
    )
    return 0


def _qualify_command(args):
    from edge_delegate.data.review import SPLITS
    from edge_delegate.evaluation.qualification import qualify

    from .review_workspace import verify_policy_document

    manifest = _load_json_object(args.manifest)
    splits = None
    if args.review_directory is not None:
        workspace_manifest = _load_json_object(args.review_directory / "manifest.json")
        if workspace_manifest != manifest:
            raise ValueError("qualification manifest differs from reviewed workspace")
        verify_policy_document(args.review_directory, manifest)
        splits = {name: _load_jsonl(args.review_directory / f"{name}.jsonl") for name in SPLITS}

    report = qualify(
        *(
            _load_json_object(path, max_bytes=64 * 1024 * 1024)
            for path in (args.test_report, args.safety_report, args.benchmark)
        ),
        manifest,
        review_splits=splits,
    )
    print(json.dumps(report, indent=2))
    return 0 if report["qualified"] else 2


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
    # Plugin-owned training reports need not pretend every model uses a GPU/LoRA.
    print(json.dumps(report, indent=2, sort_keys=True))
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
    manifest.verify_files(root, descriptor=plugin.descriptor)
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


def _artifact_export_command(args):
    from .artifact_bundle import export_candidate

    print(json.dumps(export_candidate(args.artifact, args.output), indent=2))
    return 0


def _plan_command(args: argparse.Namespace) -> int:
    client = _query_client(args)
    result = client.query(args.text, include_raw_output=not args.omit_raw_output)
    print(render_query(result, output_format=args.format))
    return 0 if result["valid"] else 2


def _interactive_command(args: argparse.Namespace) -> int:
    client = _query_client(args)
    include_raw_output = not args.omit_raw_output
    output_format = args.format
    model_id = client.model_info.get("model_id", args.plugin)
    print(f"Loaded {model_id}")
    print(f"Profile: {client.profile.root}")
    print(interactive_help())

    def run_query(text: str) -> None:
        try:
            result = client.query(text, include_raw_output=include_raw_output)
        except ValueError as exc:
            print(f"Invalid query: {exc}")
            return
        print(render_query(result, output_format=output_format))

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
        if text.startswith("/format"):
            parts = text.split()
            if len(parts) != 2 or parts[1] not in {"text", "json"}:
                print("usage: /format text|json")
                continue
            output_format = parts[1]
            print(f"output format: {output_format}")
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


def _profile_check_command(args: argparse.Namespace) -> int:
    report = ClientProfile.load(args.profile).inspect()
    print(render_profile(report, output_format=args.format))
    return 0


def _simulate_command(args: argparse.Namespace) -> int:
    request = PlanningRequest.from_dict(
        {
            "request_id": "simulation-query",
            "text": args.text,
            "locale": args.locale,
        }
    )
    plugin = available_model_plugins().get(args.plugin)
    planner = plugin.create_planner(artifact_path=args.adapter, settings=_plugin_settings(args))
    result = run_simulation(planner, request)
    result["planner_plugin"] = args.plugin
    print(render_simulation(result, output_format=args.format))
    return 0 if result["status"] == "executed" else 2


def _device_from_args(args):
    from edge_delegate.adapters.registry import load_device_adapter

    settings = {} if args.device_settings is None else _load_json_object(args.device_settings)
    if args.socket is not None:
        if "socket" in settings:
            raise ValueError("specify socket only once, in settings or --socket")
        settings["socket"] = str(args.socket)
    return load_device_adapter(args.device_adapter, settings=settings)


def _add_device_arguments(command):
    command.add_argument("--device-adapter", default="unix", help="installed device adapter ID")
    command.add_argument("--device-settings", type=Path, help="adapter settings JSON; never Python")
    command.add_argument(
        "--socket", type=Path, help="Unix emulator socket (required by unix adapter)"
    )


def _init_example_command(args):
    from edge_delegate.simulator.examples import local_display

    target = args.output
    # Refuse an existing directory rather than partially overwrite user profiles.
    target.mkdir(parents=True, exist_ok=False)
    world, policy = local_display()
    for name, value in {
        "capabilities": [card.to_dict() for card in world.capability_cards],
        "state": world.snapshot().to_dict(),
        "policy": policy.to_dict(),
    }.items():
        (target / f"{name}.json").write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(f"Created simulator profile: {target}. Saved state is not live device state.")
    return 0


def _run_command(args: argparse.Namespace) -> int:
    from edge_delegate.contracts import Policy

    from .emulator import managed_emulator

    if args.request_id is not None and args.text is None:
        raise ValueError("--request-id requires --text; interactive requests get independent IDs")
    if args.emulator_dir is not None:
        if (
            args.socket is not None
            or args.device_settings is not None
            or args.device_adapter != "unix"
        ):
            raise ValueError(
                "--emulator-dir cannot be combined with a socket or external device adapter"
            )
        if args.journal is not None:
            raise ValueError("managed sessions keep gateway.sqlite inside --emulator-dir")
        from edge_delegate.simulator.examples import local_display

        policy = (
            Policy.from_dict(_load_json_object(args.policy)) if args.policy else local_display()[1]
        )
        print(
            "Starting managed software emulator (no physical hardware)...",
            file=sys.stderr,
            flush=True,
        )
        try:
            with managed_emulator(args.emulator_dir) as (device, journal):
                print(
                    f"READY: {device.device_id}. State and journal: {args.emulator_dir}",
                    file=sys.stderr,
                    flush=True,
                )
                return _run_session(
                    args, device, policy, journal, output_format=args.format or "text"
                )
        except KeyboardInterrupt:
            print(
                "Session interrupted. An in-flight action may have completed; retain the journal and reconcile before new work.",
                file=sys.stderr,
                flush=True,
            )
            return 130
    if args.journal is None or args.policy is None:
        raise ValueError(
            "external adapter sessions require --journal and --policy; or use --emulator-dir"
        )
    policy = Policy.from_dict(_load_json_object(args.policy))
    print("Connecting to device...", file=sys.stderr, flush=True)
    try:
        device = _device_from_args(args)
    except (FileNotFoundError, ConnectionRefusedError) as exc:
        raise ValueError(
            "device socket unavailable: start the emulator and leave it running, check --socket, or use --emulator-dir"
        ) from exc
    print(f"CONNECTED: {device.device_id}", file=sys.stderr, flush=True)
    try:
        return _run_session(args, device, policy, args.journal, output_format=args.format or "json")
    except KeyboardInterrupt:
        print(
            "Client interrupted. The external device process was not stopped; an in-flight action may have completed. Retain the journal and reconcile.",
            file=sys.stderr,
            flush=True,
        )
        return 130


def _run_session(args, device, policy, journal, *, output_format):
    import uuid

    from .gateway import GatewaySession
    from .presentation import render_gateway

    print(
        f"Loading planner: {args.plugin} (first load may take time)...", file=sys.stderr, flush=True
    )
    plugin = available_model_plugins().get(args.plugin)
    diagnostic = plugin.create_diagnostic_session(
        artifact_path=args.adapter, settings=_plugin_settings(args)
    )
    from edge_delegate.model_plugins.api import WarmableModelSession

    if isinstance(diagnostic, WarmableModelSession):
        print(
            "Preparing inference; compilation can take a minute on first use. No device actions.",
            file=sys.stderr,
            flush=True,
        )
        preparation = diagnostic.warmup()
        if preparation.get("performed"):
            print(
                f"Inference prepared in {preparation['latency_ms'] / 1000:.1f}s (startup only).",
                file=sys.stderr,
                flush=True,
            )
    session = GatewaySession(
        diagnostic.planner, device, policy, journal_path=journal, diagnostics=diagnostic
    )
    print(
        "READY: planner loaded. Valid requests can execute device actions.",
        file=sys.stderr,
        flush=True,
    )

    def execute(text, request_id=None):
        request = PlanningRequest.from_dict(
            {"request_id": request_id or str(uuid.uuid4()), "text": text, "locale": "en"}
        )
        print(f"Processing request {request.request_id!r}...", file=sys.stderr, flush=True)
        result = session.handle(request)
        print(render_gateway(result, output_format=output_format), flush=True)
        return 0 if result["result"]["status"] == "executed" else 2

    if args.text is not None:
        return execute(args.text, args.request_id)
    print(
        f"EXECUTION session: {args.device_adapter} / {device.device_id}. /help lists commands; /quit exits.\n"
        "Each request is independent, not a chat conversation. Reuse an ID only for the same request.",
        file=sys.stderr,
    )
    while True:
        try:
            if sys.stdin.isatty():
                print("edge-delegate> ", file=sys.stderr, end="", flush=True)
            text = input()
        except EOFError:
            return 0
        if text.strip() == "/quit":
            return 0
        if text.strip() == "/help":
            print(
                "Enter a complete request to execute.\n/reconcile REQUEST_ID checks receipts only.\n/cancel REQUEST_ID asks the device to fence unresolved operations; it never undoes completed actions.\n/quit exits; durable state is retained.",
                file=sys.stderr,
                flush=True,
            )
            continue
        if text.startswith("/"):
            command, _, request_id = text.strip().partition(" ")
            if command not in {"/reconcile", "/cancel"} or not request_id.strip():
                print("Unknown/incomplete command. Use /help.", file=sys.stderr, flush=True)
                continue
            from edge_delegate.runtime.recovery import reconcile_operations

            report = reconcile_operations(
                session.journal,
                device,
                request_id=request_id.strip(),
                cancel_unknown=command == "/cancel",
            )
            print(json.dumps(report, indent=2), flush=True)
            continue
        if text.strip():
            execute(text)


def _reconcile_command(args: argparse.Namespace) -> int:
    from edge_delegate.runtime.journal import OperationJournal
    from edge_delegate.runtime.recovery import reconcile_operations

    if not args.journal.is_file():
        raise ValueError("reconciliation requires an existing journal")
    result = reconcile_operations(
        OperationJournal(args.journal),
        _device_from_args(args),
        request_id=args.request_id,
        operation_id=args.operation_id,
        cancel_unknown=args.cancel_unknown,
    )
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "reconciled" else 2


def _add_model_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--plugin", default="functiongemma", help="installed model plugin ID")
    command.add_argument(
        "--plugin-settings", type=Path, help="JSON settings for the selected plugin"
    )
    command.add_argument("--model-id", help="override the plugin's base model (not the adapter)")
    command.add_argument("--adapter", help="saved adapter directory; omit to test the base model")
    command.add_argument(
        "--retrieval-limit", type=int, help="maximum capability cards in the prompt"
    )
    command.add_argument(
        "--max-new-tokens", type=int, help="output tokens reserved within the context budget"
    )


def _add_query_arguments(
    command: argparse.ArgumentParser,
    *,
    text_required: bool,
) -> None:
    _add_model_arguments(command)
    command.add_argument(
        "--profile",
        required=True,
        type=Path,
        help="directory containing capabilities.json, state.json, and policy.json",
    )
    command.add_argument("--locale", default="en")
    command.add_argument("--text", required=text_required)
    command.add_argument(
        "--format",
        choices=("text", "json"),
        default="json" if text_required else "text",
        help="output format (plan: json; interactive: text)",
    )
    raw = command.add_mutually_exclusive_group()
    raw.add_argument("--omit-raw-output", action="store_true", help="hide raw generation")
    raw.add_argument(
        "--raw-output",
        dest="omit_raw_output",
        action="store_false",
        help="include raw generation for debugging",
    )
    command.set_defaults(omit_raw_output=not text_required)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edge-delegate-lab",
        description="Build, train, and evaluate Edge Delegate model plugins.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    generate = commands.add_parser("generate-data", help="build canonical and model exports")
    generate.add_argument("--dataset-version", choices=("v0", "v1"), default="v0")
    generate.add_argument("--output", required=True, type=Path)
    generate.add_argument("--seed", type=int, default=17)
    generate.add_argument(
        "--export-plugin",
        action="append",
        help="model plugin training export to create; repeat for multiple plugins",
    )
    generate.set_defaults(handler=_generate_data_command)

    review = commands.add_parser(
        "review-data", help="check a v2 draft review workspace; never train, freeze, or approve"
    )
    review.add_argument("--directory", required=True, type=Path)
    review.add_argument("--format", choices=("text", "json"), default="json")
    review.add_argument(
        "--allow-pending",
        action="store_true",
        help="inspect a partial draft; do not require accepted reviews or pilot coverage",
    )
    review.set_defaults(handler=_review_data_command)

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

    audit = commands.add_parser(
        "audit-validation", help="triage validation failures and compare batch/single planning"
    )
    _add_model_arguments(audit)
    audit.add_argument(
        "--dataset",
        required=True,
        type=Path,
        help="canonical validation JSONL beside manifest.json",
    )
    audit.add_argument(
        "--output", required=True, type=Path, help="new audit directory; never overwritten"
    )
    audit.add_argument(
        "--include-sensitive",
        action="store_true",
        help="include request text, expected values, and exception messages",
    )
    audit.set_defaults(handler=_audit_validation_command)

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

    profile = commands.add_parser(
        "profile-check", help="check saved device context without loading a model"
    )
    profile.add_argument("--profile", required=True, type=Path)
    profile.add_argument("--format", choices=("text", "json"), default="text")
    profile.set_defaults(handler=_profile_check_command)

    simulate = commands.add_parser(
        "simulate",
        help="run a model query through the real runtime against a simulated display",
        description="Execute valid local model proposals in a fresh local-display simulator only. "
        "No physical device or external model is contacted. Exit 0 means local execution "
        "succeeded, not that the model understood the request.",
    )
    _add_model_arguments(simulate)
    simulate.add_argument("--text", required=True)
    simulate.add_argument("--locale", default="en")
    simulate.add_argument("--format", choices=("text", "json"), default="text")
    simulate.set_defaults(handler=_simulate_command)

    export = commands.add_parser(
        "artifact-export", help="export verified candidate files, not a qualified release"
    )
    export.add_argument("--artifact", required=True, type=Path)
    export.add_argument("--output", required=True, type=Path)
    export.set_defaults(handler=_artifact_export_command)

    example = commands.add_parser("init-example", help="create a local-display simulator profile")
    example.add_argument("--output", required=True, type=Path)
    example.set_defaults(handler=_init_example_command)

    run = commands.add_parser(
        "run", help="explicit persistent execution using an installed adapter"
    )
    _add_model_arguments(run)
    _add_device_arguments(run)
    run.add_argument("--journal", type=Path)
    run.add_argument("--policy", type=Path)
    run.add_argument(
        "--emulator-dir",
        type=Path,
        help="manage a software emulator and persistent journal in a private Linux directory",
    )
    run.add_argument(
        "--format",
        choices=("text", "json"),
        help="managed default: text; external adapter default: JSON",
    )
    run.add_argument("--text")
    run.add_argument("--request-id", help="reuse only to reconcile/replay the same request")
    run.set_defaults(handler=_run_command)

    recovery = commands.add_parser(
        "reconcile", help="check recorded device receipts without planning or executing actions"
    )
    _add_device_arguments(recovery)
    recovery.add_argument("--journal", required=True, type=Path)
    recovery.add_argument(
        "--cancel-unknown",
        action="store_true",
        help="ask the device to permanently fence unresolved operations; does not undo actions",
    )
    selector = recovery.add_mutually_exclusive_group(required=True)
    selector.add_argument("--request-id", help="original request ID recorded at dispatch")
    selector.add_argument("--operation-id", help="operation ID, including older journal entries")
    recovery.set_defaults(handler=_reconcile_command)

    timing = commands.add_parser(
        "benchmark", help="measure persistent gateway latency, including failures"
    )
    _add_model_arguments(timing)
    timing.add_argument("--socket", required=True, type=Path)
    timing.add_argument("--journal", required=True, type=Path)
    timing.add_argument("--policy", required=True, type=Path)
    timing.add_argument("--output", required=True, type=Path)
    timing.add_argument("--count", type=int, default=200)
    timing.add_argument("--runs", type=int, default=3)
    timing.set_defaults(handler=_benchmark_command)
    qualification = commands.add_parser(
        "qualify", help="check evidence; never silently promote a model"
    )
    for flag in ("test-report", "safety-report", "benchmark", "manifest"):
        qualification.add_argument(f"--{flag}", required=True, type=Path)
    qualification.add_argument(
        "--review-directory",
        type=Path,
        help="actual reviewed records; omission fails the review gate",
    )
    qualification.set_defaults(handler=_qualify_command)
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
