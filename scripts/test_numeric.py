"""Run the actual installed model against numeric and non-action development challenges."""

import argparse
import json
import os
from pathlib import Path

from edge_delegate.data.fingerprint import content_fingerprint
from edge_delegate.model_plugins import available_model_plugins
from edge_delegate.model_plugins.api import WarmableModelSession
from edge_delegate_lab.evidence import model_identity
from edge_delegate_lab.numeric_challenge import challenge_cases, run_challenges


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin", default="functiongemma-tasks")
    parser.add_argument(
        "--artifact", default="artifacts/training/functiongemma-tasks-v1-r2-b16/selected-adapter"
    )
    parser.add_argument(
        "--no-artifact",
        action="store_true",
        help="explicitly select a planner requiring no model weights",
    )
    parser.add_argument(
        "--include-raw-output",
        action="store_true",
        help="persist raw diagnostics for these public development cases only",
    )
    parser.add_argument(
        "--settings",
        type=Path,
        default=Path("configs/inference/functiongemma-tasks-compiled-decimal-v1.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.no_artifact:
        args.artifact = None
    settings = json.loads(args.settings.read_text(encoding="utf-8"))
    if settings.get("numeric_policy") != "decimal.v1":
        parser.error("this suite requires explicit decimal.v1 settings")
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ["HF_HUB_OFFLINE"] = "1"
    report = {
        "schema_version": "edge-numeric-challenge.v1",
        "complete": False,
        "qualified": False,
        "plugin_id": args.plugin,
        "scope": "exposed development cases; software simulation only",
        "model_identity": model_identity(args.plugin, args.artifact, settings),
        "settings": settings,
        "suite_sha256": content_fingerprint(challenge_cases()),
        "cases": [],
    }

    def save():
        pending = args.output / "report.pending.json"
        pending.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        pending.replace(args.output / "report.json")

    save()
    try:
        print(
            "Loading selected planner. Software simulation only; no physical actions or training.",
            flush=True,
        )
        model = (
            available_model_plugins()
            .get(args.plugin)
            .create_diagnostic_session(artifact_path=args.artifact, settings=settings)
        )
        report["planner_info"] = dict(model.model_info)
        if model.model_info.get("trained") is False:
            report["scope"] = (
                "deterministic baseline; exposed development cases; NOT model accuracy"
            )
            print(
                "Deterministic command grammar: no model inference. Results are NOT model accuracy.",
                flush=True,
            )
        if isinstance(model, WarmableModelSession):
            model.warmup()
        for case in run_challenges(
            model.planner, diagnostics=model, include_raw_output=args.include_raw_output
        ):
            report["cases"].append(case)
            save()
            print(
                f"{case['case_id']}: {'PASS' if case['passed'] else 'FAIL'}; {case['status']}",
                flush=True,
            )
            if not case["passed"]:
                print(
                    f"  Request: {case['text']!r}; expected {case['expected_status']}", flush=True
                )
                if case["failure_message"]:
                    print(f"  Detail: {case['failure_message']}", flush=True)
        report["complete"] = True
        report["passed_count"] = sum(c["passed"] for c in report["cases"])
        report["unexpected_action_cases"] = sum(c["unexpected_invocation"] for c in report["cases"])
        report["unexpected_invocation_count"] = sum(
            c["unexpected_invocation_count"] for c in report["cases"]
        )
        save()
        print(
            f"{report['passed_count']}/{len(report['cases'])} passed. Report: {args.output / 'report.json'}"
        )
        return 0 if all(c["passed"] for c in report["cases"]) else 1
    except BaseException as exc:
        report["error_type"] = type(exc).__name__
        save()
        raise


if __name__ == "__main__":
    raise SystemExit(main())
