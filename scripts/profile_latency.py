"""Reproduce burst versus idle-separated latency with an isolated software emulator.

No training, physical devices, or qualification. Reports retain every outcome.
"""

import argparse
import json
import os
import sqlite3
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

from edge_delegate.model_plugins import available_model_plugins
from edge_delegate.model_plugins.api import WarmableModelSession
from edge_delegate.simulator.examples import local_display
from edge_delegate_lab.compute import detect_hardware_inventory
from edge_delegate_lab.emulator import managed_emulator
from edge_delegate_lab.evidence import model_identity
from edge_delegate_lab.gateway import GatewaySession
from edge_delegate_lab.latency_profile import TracedDevice, iter_samples, storage_info, summarize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin", default="functiongemma-tasks")
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--settings", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--idle-seconds", type=float, default=3)
    parser.add_argument(
        "--state-root",
        type=Path,
        default=Path.home() / ".local/state/edge-delegate-profiles",
        help="parent for isolated emulator/journal; default uses home storage, not RAM-backed /tmp",
    )
    args = parser.parse_args()
    if not 6 <= args.count <= 200 or not 0 <= args.idle_seconds <= 60:
        parser.error("count must be 6..200; idle-seconds must be 0..60")
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ["HF_HUB_OFFLINE"] = "1"
    settings = json.loads(args.settings.read_text(encoding="utf-8"))
    report = {
        "schema_version": "edge-latency-profile.v1",
        "complete": False,
        "qualified": False,
        "sqlite_version": sqlite3.sqlite_version,
        "identity": model_identity(args.plugin, args.artifact, settings),
        "settings": settings,
        "samples": [],
        "requested_count_per_phase": args.count,
        "requested_idle_seconds": args.idle_seconds,
        "hardware_inventory": asdict(detect_hardware_inventory()),
        "scope": "six fixed requests; no intent-accuracy or physical-device qualification",
    }

    def save():
        target = args.output / "report.json"
        pending = args.output / "report.pending.json"
        pending.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
        pending.replace(target)

    save()
    try:
        print("Loading diagnostic model (no device writes during preparation)...", flush=True)
        started = time.perf_counter()
        model = (
            available_model_plugins()
            .get(args.plugin)
            .create_diagnostic_session(artifact_path=args.artifact, settings=settings)
        )
        report["model_load_ms"] = (time.perf_counter() - started) * 1000
        report["model_info"] = dict(model.model_info)
        print("Preparing inference; initial compilation may take a few minutes...", flush=True)
        report["preparation"] = model.warmup() if isinstance(model, WarmableModelSession) else None
        args.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(prefix="ed-latency-", dir=args.state_root) as directory:
            report["storage"] = storage_info(directory)
            save()
            with managed_emulator(directory) as (device, journal):
                device = TracedDevice(device)
                session = GatewaySession(
                    model.planner,
                    device,
                    local_display()[1],
                    journal_path=journal,
                    diagnostics=model,
                )
                for sample in iter_samples(
                    session, device, count=args.count, idle_seconds=args.idle_seconds
                ):
                    report["samples"].append(sample)
                    save()
                    verdict = "PASS" if sample["passed"] else "FAIL"
                    print(
                        f"{sample['phase']} {sample['index'] + 1}/{args.count}: "
                        f"{sample['total_ms']:.1f} ms; {sample['status']}; {verdict}",
                        flush=True,
                    )
        report["summary"] = summarize(report["samples"])
        report["passed"] = all(s["passed"] for s in report["samples"])
        report["complete"] = True
        save()
        print(json.dumps(report["summary"], indent=2), flush=True)
        print(f"Report: {(args.output / 'report.json').resolve()}", flush=True)
        return 0 if report["passed"] else 1
    except BaseException as exc:
        report["error_type"] = type(exc).__name__
        save()
        raise


if __name__ == "__main__":
    raise SystemExit(main())
