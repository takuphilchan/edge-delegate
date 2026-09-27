"""Validation-only triage and batch/single-request comparison; never trains or promotes."""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from edge_delegate.contracts import PlanIR
from edge_delegate.data import build_record_world, dataset_fingerprint, validate_records
from edge_delegate.evaluation import EvaluationRunner
from edge_delegate.model_plugins.api import WarmableModelSession
from edge_delegate.planner import StaticPlanner

from .jsonio import MAX_RECORD_BYTES, load_jsonl, reject_constant, without_duplicates


def validation_records(path: Path):
    payload = (path.parent / "manifest.json").read_bytes()
    if len(payload) > MAX_RECORD_BYTES:
        raise ValueError("dataset manifest exceeds the size limit")
    manifest = json.loads(
        payload, object_pairs_hook=without_duplicates, parse_constant=reject_constant
    )
    records = load_jsonl(path)
    if not records or dataset_fingerprint(records) != manifest["split_sha256"]["validation"]:
        raise ValueError("audit requires the manifest's validation split, not train/test/safety")
    validate_records(records)
    if any("expected_effects" not in record for record in records):
        raise ValueError("audit requires declarative expected effects for every case")
    return records, manifest


def primary_finding(case):
    """Observed symptom only. Label correctness and underlying causes require review."""
    diagnostic = case.get("diagnostics", {})
    if case["task_success"] is True:
        if diagnostic.get("intent_correct") is False:
            return "wrong_intent_masked_by_runtime"
        return "passed"
    if not case["parse_valid"]:
        return (
            "invalid_decision"
            if diagnostic.get("error_type") == "PlannerOutputError"
            else "planner_error"
        )
    if not case["request_id_correct"]:
        return "request_binding_mismatch"
    if case["unnecessary_abstention"]:
        return "unnecessary_abstention"
    if diagnostic.get("expected_route") in {"clarify", "deny", "defer"} and diagnostic.get(
        "predicted_route"
    ) in {"local", "hybrid"}:
        return "inappropriate_action_proposal"
    if not case["route_correct"]:
        return "route_mismatch"
    if not case["static_valid"]:
        return "validation_rejection"
    if not case["capability_sequence_exact"]:
        return "task_or_sequence_mismatch"
    if diagnostic.get("arguments_match") is False:
        return "argument_or_dependency_mismatch"
    if case["execution_success"] is False:
        return "execution_failure"
    if diagnostic.get("observed_effect_issues"):
        return "effect_mismatch"
    return "unresolved"


def summarize(report, records, reference_report):
    by_id = {record["record_id"]: record for record in records}
    reference = {case["record_id"]: case for case in reference_report["cases"]}
    findings = []
    groups = defaultdict(list)
    for case in report["cases"]:
        record = by_id[case["record_id"]]
        primary = primary_finding(case)
        tags = []
        if case["wrong_but_permitted"]:
            tags.append("wrong_but_permitted")
        if case["forbidden_invocation_count"]:
            tags.append("task_forbidden_invocations")
        if reference[case["record_id"]]["task_success"] is not True:
            primary = "reference_or_harness_disagreement"
            tags.append("review_label_and_harness")
        item = {
            "record_id": case["record_id"],
            "category": case["category"],
            "primary_finding": primary,
            "tags": tags,
            "review_status": "pending",
            "source_group": record["metadata"].get("scenario_group"),
            "diagnostics": case.get("diagnostics", {}),
        }
        findings.append(item)
        groups[f"{case['category']} / {primary}"].append(case["record_id"])
    return {
        "case_count": len(findings),
        "task_success_count": sum(case["task_success"] is True for case in report["cases"]),
        "task_failure_count": sum(case["task_success"] is not True for case in report["cases"]),
        "wrong_but_permitted_count": sum(case["wrong_but_permitted"] for case in report["cases"]),
        "decision_metrics": report.get("decision_metrics"),
        "primary_counts": dict(sorted(Counter(x["primary_finding"] for x in findings).items())),
        "groups": dict(sorted(groups.items())),
        "findings": findings,
    }


def compare_modes(batch, single):
    if batch["dataset_sha256"] != single["dataset_sha256"]:
        raise ValueError("cannot compare different datasets")
    before = {case["record_id"]: case for case in batch["cases"]}
    after = {case["record_id"]: case for case in single["cases"]}
    if (
        len(before) != len(batch["cases"])
        or len(after) != len(single["cases"])
        or before.keys() != after.keys()
    ):
        raise ValueError("comparison requires identical, unique case IDs")
    differences = []
    for identifier, left in before.items():
        right = after[identifier]
        # Exception messages can contain sensitive text; compare structured evidence instead.
        fields = [key for key in left if key != "error" and left[key] != right.get(key)]
        if fields:
            differences.append({"record_id": identifier, "changed_fields": fields})
    return {
        "case_count": len(before),
        "different_case_count": len(differences),
        "single_regressions": [
            key
            for key in before
            if before[key]["task_success"] is True and after[key]["task_success"] is not True
        ],
        "single_improvements": [
            key
            for key in before
            if before[key]["task_success"] is not True and after[key]["task_success"] is True
        ],
        "checked_intent_regressions": [
            key
            for key in before
            if before[key].get("diagnostics", {}).get("intent_correct") is True
            and after[key].get("diagnostics", {}).get("intent_correct") is False
        ],
        "checked_intent_improvements": [
            key
            for key in before
            if before[key].get("diagnostics", {}).get("intent_correct") is False
            and after[key].get("diagnostics", {}).get("intent_correct") is True
        ],
        "differences": differences,
        "scope": "one pass each; compares structured plans/effects, not raw logits or repeatability",
    }


def run_audit(model, records, metadata, *, write, progress, include_sensitive=False):
    reference = EvaluationRunner(
        StaticPlanner({r["record_id"]: PlanIR.from_dict(r["expected_plan"]) for r in records}),
        execution_harness=build_record_world,
    ).evaluate(records)
    if not include_sensitive:
        for case in reference["cases"]:
            case["error"] = None
    write("reference.json", reference)
    reports = {}
    summaries = {}
    for mode in ("batch", "single"):
        if isinstance(model, WarmableModelSession):
            progress(mode, 0, len(records))
            model.warmup()
        report = EvaluationRunner(
            model.planner,
            execution_harness=build_record_world,
            use_batch=mode == "batch",
            diagnostics=True,
            progress=lambda done, total, mode=mode: progress(mode, done, total),
        ).evaluate(records)
        report.update(metadata)
        report["evaluation_mode"] = mode
        report["batch_interface_available"] = callable(getattr(model.planner, "plan_many", None))
        if not include_sensitive:
            for case in report["cases"]:
                case["error"] = None
        reports[mode] = report
        summaries[mode] = summarize(report, records, reference)
        write(f"{mode}.json", report)
    result = {
        "schema_version": "edge-validation-audit.v1",
        "complete": True,
        "qualified": False,
        "independent_review_complete": False,
        "finding_semantics": "automatic symptoms, not verified root causes; all cases need review",
        "reference_failure_ids": [
            c["record_id"] for c in reference["cases"] if c["task_success"] is not True
        ],
        "modes": summaries,
        "comparison": compare_modes(reports["batch"], reports["single"]),
        **metadata,
    }
    if include_sensitive:
        result["sensitive_cases"] = [
            {
                "record_id": r["record_id"],
                "request": r["request"],
                "expected_task": r.get("expected_task"),
                "expected_effects": r["expected_effects"],
            }
            for r in records
        ]
    return result


def render_audit(report):
    lines = [
        "# Validation audit",
        "",
        "Automatic triage, not independent label review or release qualification.",
        "",
        "Both paths use saved dataset contexts and the in-memory simulator, not physical devices.",
        "Single mode uses the deployed planning path with optional per-call diagnostics, not a full gateway latency test.",
        "",
        "| Mode | Cases | Correct outcomes | Failures | Wrong-but-permitted |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for mode, summary in report["modes"].items():
        lines.append(
            f"| {mode} | {summary['case_count']} | {summary['task_success_count']} | {summary['task_failure_count']} | {summary['wrong_but_permitted_count']} |"
        )
    lines.extend(
        [
            "",
            f"Cases differing between modes: {report['comparison']['different_case_count']}.",
            "",
            "## Findings",
            "",
        ]
    )
    for mode, summary in report["modes"].items():
        lines.extend([f"### {mode}", ""])
        decision = summary.get("decision_metrics")
        if decision is not None:
            lines.extend(
                [
                    f"Correct checked pre-compiler decisions: {decision['correct_count']}/"
                    f"{decision['assessed_count']}; unassessed: {decision['unassessed_count']}.",
                    "These are checked plugin decisions, not raw model output. Outcome scores remain separate.",
                    "",
                ]
            )
        for category, ids in summary["groups"].items():
            lines.append(f"- {category}: {len(ids)} cases; example IDs: {', '.join(ids[:3])}.")
        lines.append("")
    lines.extend(
        [
            "## Next review",
            "",
            "Review wrong-but-permitted cases first, then invalid decisions and mode differences.",
            "Use case IDs to join the validation dataset; successful reference execution does not prove labels match human intent.",
            "Do not retrain until the observed symptoms have reviewed causes and targeted corrections.",
            "All review statuses remain pending. Source hashes are provenance, not anonymization or trust signatures.",
            "",
        ]
    )
    return "\n".join(lines)


def audit_command(*, dataset, output, plugin_id, artifact, settings, include_sensitive=False):
    from edge_delegate.model_plugins import available_model_plugins

    from .evidence import model_identity

    records, manifest = validation_records(dataset)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)

    def write(name, value):
        (output / name).write_text(
            json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )

    def progress(mode, done, total):
        if done % 50 == 0 or done == total:
            print(f"audit {mode}: {done}/{total}", file=sys.stderr, flush=True)
            write("progress.json", {"complete": False, "mode": mode, "done": done, "total": total})

    write("progress.json", {"complete": False, "phase": "loading"})
    print(
        "Loading audit planner; no physical devices or training. Reports are sensitive local data.",
        file=sys.stderr,
        flush=True,
    )
    try:
        identity = model_identity(plugin_id, artifact, settings)
        model = (
            available_model_plugins()
            .get(plugin_id)
            .create_diagnostic_session(artifact_path=artifact, settings=settings)
        )
        metadata = {
            "plugin_id": plugin_id,
            "settings": settings,
            "model_identity": identity,
            "model_info": dict(model.model_info),
            "dataset_sha256": dataset_fingerprint(records),
            "catalog_version": manifest.get("catalog"),
            "includes_sensitive_details": include_sensitive,
            "physical_devices": False,
            "scope": "validation-only, saved contexts, in-memory simulated effects",
        }
        report = run_audit(
            model,
            records,
            metadata,
            write=write,
            progress=progress,
            include_sensitive=include_sensitive,
        )
        if model_identity(plugin_id, artifact, settings) != identity:
            raise ValueError(
                "source or artifact changed during audit; rerun for consistent evidence"
            )
        write("audit.json", report)
        (output / "summary.md").write_text(render_audit(report), encoding="utf-8")
        write("progress.json", {"complete": True, "phase": "finished"})
        print(
            json.dumps(
                {"output": str(output), "comparison": report["comparison"], "qualified": False},
                indent=2,
            )
        )
        return 0
    except BaseException as exc:
        write(
            "progress.json",
            {
                "complete": False,
                "phase": "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed",
                "error_type": type(exc).__name__,
            },
        )
        raise
