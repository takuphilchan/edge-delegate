from copy import deepcopy

import pytest

from edge_delegate.evaluation.qualification import IDENTITY_FIELDS, qualify


def evidence():
    """Synthetic gate-test evidence; not a project qualification report."""
    identity = {key: "a" * 64 for key in IDENTITY_FIELDS}
    identity["numeric_policy"] = "decimal.v1"
    categories = [
        ("supported", task) for task in ("read_temperature", "display_number", "show_temperature")
    ]
    categories += [
        ("clarify", "clarify"),
        ("deny", "deny"),
        ("restricted", "display_number"),
        ("challenge", "clarify"),
    ]

    def case(identifier, category, task):
        return {
            "record_id": identifier,
            "category": category,
            "family": identifier,
            "expected_task": {"task": task, "parameters": {}},
            "task_success": True,
            "wrong_but_permitted": False,
            "forbidden_invocation_count": 0,
            "authorization_violation_count": 0,
            "invalid_literal_dispatch_count": 0,
            "invocation_count": 0 if category != "supported" else 1,
            "effect_issues": [],
        }

    def report(cases, digest):
        return {
            "schema_version": "edge-delegate-evaluation.v2",
            "evidence_version": "edge-outcome-evidence.v1",
            "complete": True,
            "case_count": len(cases),
            "cases": cases,
            "dataset_sha256": digest,
            "model_identity": "c" * 64,
            "deployment_identity": identity,
        }

    functional = report(
        [
            case(f"case-{group}-{i}", category, task)
            for group, (category, task) in enumerate(categories)
            for i in range(100)
        ],
        "d" * 64,
    )
    safety = report([case(f"safety-{i}", "adversarial", "deny") for i in range(200)], "e" * 64)
    runs = []
    for run in range(3):
        phases = {}
        for name, idle in (("burst", 0), ("idle_3s", 3), ("idle_15s", 15)):
            phases[name] = {
                "request_count": 200,
                "warmups": 5,
                "idle_seconds": idle,
                "samples": [
                    {
                        "request_id": f"{run}-{name}-{i}",
                        "latency_ms": 400,
                        "status": "executed",
                        "expected_status": "executed",
                        "checks": {
                            k: True
                            for k in (
                                "status",
                                "invocations_and_returns",
                                "final_state",
                                "execution",
                            )
                        },
                    }
                    for i in range(200)
                ],
            }
        runs.append({"phases": phases})
    benchmark = {
        "schema_version": "edge-release-benchmark.v1",
        "complete": True,
        "model_identity": "c" * 64,
        "deployment_identity": identity,
        "storage": {"fstype": "ext4"},
        "runs": runs,
        "workload_sha256": "f" * 64,
    }
    manifest = {
        "split_sha256": {"test": "d" * 64, "safety": "e" * 64},
        "deployment_identity": identity,
        "performance_workload_sha256": "f" * 64,
        "independent_review_complete": True,
    }
    return functional, safety, benchmark, manifest


def test_new_evidence_checks_can_pass_but_manifest_cannot_approve_review():
    report = qualify(*evidence())
    assert {name for name, passed in report["checks"].items() if not passed} == {
        "independent_review"
    }
    assert not report["evidence_gates_passed"]
    assert not report["qualified"]
    assert not report["developer_preview_qualified"]


@pytest.mark.parametrize(
    "mutation,failed",
    [
        (lambda t, s, b, m: b.pop("complete"), "benchmark_complete"),
        (lambda t, s, b, m: t.pop("complete"), "complete_outcome_evidence"),
        (lambda t, s, b, m: t["cases"].pop(), "complete_outcome_evidence"),
        (
            lambda t, s, b, m: t["cases"].__setitem__(0, deepcopy(t["cases"][1])),
            "complete_outcome_evidence",
        ),
        (
            lambda t, s, b, m: t["cases"][0].pop("authorization_violation_count"),
            "no_authorization_violations",
        ),
        (lambda t, s, b, m: t["cases"][0].update(wrong_but_permitted=True), "no_wrong_actions"),
        (lambda t, s, b, m: t["cases"][300].update(invocation_count=1), "nonexecuting_abstention"),
        (lambda t, s, b, m: t.update(deployment_identity={}), "matching_deployment_evidence"),
        (lambda t, s, b, m: t.update(dataset_sha256="x" * 64), "matching_dataset_evidence"),
        (lambda t, s, b, m: b["runs"][0]["phases"].pop("idle_15s"), "warm_p95"),
        (
            lambda t, s, b, m: b["runs"][0]["phases"]["burst"]["samples"][0]["checks"].update(
                final_state=False
            ),
            "benchmark_paths_complete",
        ),
        (
            lambda t, s, b, m: b["runs"][0]["phases"]["burst"]["samples"][0].update(
                latency_ms=float("nan")
            ),
            "warm_p95",
        ),
        (
            lambda t, s, b, m: b["runs"][0]["phases"]["burst"]["samples"][1].update(
                request_id="0-burst-0"
            ),
            "warm_p95",
        ),
        (lambda t, s, b, m: b["storage"].update(fstype="tmpfs"), "disk_backed_storage"),
    ],
)
def test_mutated_evidence_cannot_pass(mutation, failed):
    inputs = evidence()
    mutation(*inputs)
    result = qualify(*inputs)
    assert not result["checks"][failed]
    assert not result["qualified"]


def test_task_and_abstention_thresholds_are_not_averaged_together():
    inputs = evidence()
    for case in inputs[0]["cases"][300:306]:
        case["task_success"] = False
    result = qualify(*inputs)
    assert result["categories"]["deny"]["rate"] == 1
    assert result["categories"]["clarify"]["rate"] == 0.94
    assert not result["checks"]["separate_category_thresholds"]


def test_legacy_reports_are_readable_but_never_promoted():
    result = qualify({"cases": []}, {"cases": []}, {"runs": []}, {})
    assert result["schema_version"] == "edge-gateway-qualification.v2"
    assert not result["checks"]["complete_outcome_evidence"]


def test_null_legacy_task_and_contradictory_effect_evidence_fail():
    inputs = evidence()
    inputs[0]["cases"][0]["expected_task"] = None
    assert not qualify(*inputs)["checks"]["complete_outcome_evidence"]
    inputs = evidence()
    inputs[0]["cases"][0]["effect_issues"] = ["final_output"]
    assert not qualify(*inputs)["checks"]["complete_outcome_evidence"]
