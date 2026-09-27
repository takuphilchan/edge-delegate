"""Sequential validation + end-to-end comparison; never trains or promotes models.

Run from the checkout with --artifact, --candidate-settings, --validation and a NEW --output.
The frozen test/safety sets must not be passed as validation. Reports retain all failures.
"""

import argparse
import gc
import json
import os
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

from edge_delegate.data import build_record_world, validate_records
from edge_delegate.data.fingerprint import dataset_fingerprint
from edge_delegate.evaluation import EvaluationRunner
from edge_delegate.model_plugins import available_model_plugins
from edge_delegate.model_plugins.api import WarmableModelSession
from edge_delegate.simulator.examples import local_display
from edge_delegate_lab.benchmark import benchmark
from edge_delegate_lab.compute import detect_hardware_inventory
from edge_delegate_lab.emulator import managed_emulator
from edge_delegate_lab.evidence import model_identity
from edge_delegate_lab.gateway import GatewaySession
from edge_delegate_lab.jsonio import load_jsonl
from edge_delegate_lab.latency_profile import storage_info


def load_validation_records(path):
    manifest = json.loads((path.parent / "manifest.json").read_text())
    records = load_jsonl(path)
    if dataset_fingerprint(records) != manifest["split_sha256"]["validation"]:
        raise ValueError(
            "comparison requires the manifest's validation split, not frozen test/safety data"
        )
    validate_records(records)
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin", default="functiongemma-tasks")
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--candidate-settings", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=200)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument(
        "--state-root", type=Path, default=Path.home() / ".local/state/edge-delegate-profiles"
    )
    args = parser.parse_args()
    if not 1 <= args.count <= 10000 or not 1 <= args.runs <= 10:
        raise ValueError("count must be 1..10000 and runs 1..10")
    records = load_validation_records(args.validation)
    candidate_settings = json.loads(args.candidate_settings.read_text())
    args.output.mkdir(parents=True, exist_ok=False)
    args.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.environ["HF_HUB_OFFLINE"] = "1"
    plugin = available_model_plugins().get(args.plugin)
    summaries = {}

    def write(name, value):
        (args.output / name).write_text(
            json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8"
        )

    for name, settings in (("baseline", {}), ("candidate", candidate_settings)):
        print(f"{name}: loading", flush=True)
        started = time.perf_counter()
        model = plugin.create_diagnostic_session(artifact_path=args.artifact, settings=settings)
        load_ms = (time.perf_counter() - started) * 1000
        preparation = model.warmup() if isinstance(model, WarmableModelSession) else None
        metadata = {
            "model_load_ms": load_ms,
            "preparation": preparation,
            "model_info": dict(model.model_info),
            "settings": settings,
            "model_identity": model_identity(args.plugin, args.artifact, settings),
            "hardware_inventory": asdict(detect_hardware_inventory()),
            "artifact_size_bytes": sum(
                p.stat().st_size for p in Path(args.artifact).rglob("*") if p.is_file()
            ),
            "compiler_cache_state": "may contain previous runs; not a first-install cold-start claim",
        }
        print(f"{name}: validation ({len(records)} cases)", flush=True)
        quality = EvaluationRunner(model.planner, execution_harness=build_record_world).evaluate(
            records
        )
        quality.update(metadata)
        write(f"{name}-validation.json", quality)
        print(f"{name}: validation metrics {quality['metrics']}", flush=True)
        # Distinct private emulator state per configuration. No physical devices.
        with tempfile.TemporaryDirectory(prefix="ed-perf-", dir=args.state_root) as directory:
            metadata["storage"] = storage_info(directory)
            with managed_emulator(directory) as (device, journal):
                gateway = GatewaySession(
                    model.planner,
                    device,
                    local_display()[1],
                    journal_path=journal,
                    diagnostics=model,
                )
                timing = benchmark(
                    gateway,
                    count=args.count,
                    runs=args.runs,
                    progress=lambda run, count, label=name: print(
                        f"{label}: run {run}, request {count}", flush=True
                    ),
                    checkpoint=lambda report, label=name, info=metadata: write(
                        f"{label}-benchmark.partial.json", {**report, **info}
                    ),
                )
        timing.update(metadata)
        write(f"{name}-benchmark.json", timing)
        summaries[name] = {
            "validation_metrics": quality["metrics"],
            "warm_p95_ms": [run["p95_ms"] for run in timing["runs"]],
            "model_load_ms": load_ms,
            "preparation": preparation,
        }
        del gateway, device, model
        gc.collect()
        import torch

        torch.cuda.empty_cache()
    summary = {
        "schema_version": "edge-inference-comparison.v1",
        "complete": True,
        "qualified": False,
        "scope": "validation compatibility and six-phrase emulator performance only",
        "candidates": summaries,
    }
    write("comparison.json", summary)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
