"""Repeatable end-to-end gateway timing; errors and abstentions remain in samples."""

import math
import platform
import time
import uuid
from collections import Counter

from edge_delegate.contracts import PlanningRequest

QUERIES = (
    "Read the temperature.",
    "Show the temperature.",
    "Display 12.",
    "Display -3.5.",
    "Show it.",
    "Open the door.",
)
EXPECTED_STATUSES = (
    "executed",
    "executed",
    "executed",
    "executed",
    "clarification_required",
    "denied",
)


def outcome_diagnostics(result):
    """Keep bounded failure evidence without persisting free-form exception messages."""
    execution = result.get("execution")
    validation = result.get("validation")
    if execution is not None:
        stage = "execution"
    elif validation is not None:
        stage = "validation_or_routing"
    elif result.get("plan") is not None:
        stage = "request_binding"
    elif result.get("status") in {"invalid_plan", "planner_failed", "request_conflict"}:
        stage = "planning"
    else:
        stage = "pre_plan_or_snapshot"
    return {
        "stage": stage,
        "validation_codes": [issue["code"] for issue in (validation or {}).get("issues", [])],
        "execution_status": None if execution is None else execution.get("status"),
        "step_statuses": [
            {"capability_id": step["capability_id"], "status": step["status"]}
            for step in (execution or {}).get("steps", [])
        ],
    }


def _summarize(samples, *, warmups=5):
    def latency_summary(selected):
        values = sorted(sample["latency_ms"] for sample in selected)
        return {
            "count": len(values),
            "p50_ms": values[math.ceil(len(values) * 0.5) - 1],
            "p95_ms": values[math.ceil(len(values) * 0.95) - 1],
        }

    return {
        "request_count": len(samples),
        "warmups": warmups,
        **{key: value for key, value in latency_summary(samples).items() if key != "count"},
        "status_counts": dict(Counter(sample["status"] for sample in samples)),
        "latency_by_status": {
            status: latency_summary([sample for sample in samples if sample["status"] == status])
            for status in sorted({sample["status"] for sample in samples})
        },
        "samples": list(samples),
    }


def benchmark(session, *, count=200, runs=3, progress=None, checkpoint=None):
    if not 1 <= count <= 10000 or not 1 <= runs <= 10:
        raise ValueError("benchmark limits: 1..10000 requests, 1..10 runs")
    records = []
    cold = None

    def report(*, complete, current=None):
        return {
            "schema_version": "edge-gateway-benchmark.v1",
            "complete": complete,
            "requested_runs": runs,
            "requested_count": count,
            "runs": [*records, *([] if current is None else [_summarize(current)])],
            "first_query_ms": cold,
            "platform": platform.platform(),
            "recorded_at_unix": time.time(),
            "physical_device_qualified": False,
            "workload": list(QUERIES),
            "includes_failed_requests": True,
        }

    for _run in range(runs):
        for index in range(5):
            result = session.handle(
                PlanningRequest(str(uuid.uuid4()), QUERIES[index % len(QUERIES)])
            )
            if cold is None:
                cold = result["total_latency_ms"]
        samples = []
        for index in range(count):
            from .latency_profile import check_effects

            device = getattr(session, "device", None)
            before = None
            if device is not None and hasattr(device, "invocations"):
                try:
                    before = dict(device.snapshot().values)
                    device.invocations.clear()
                except Exception:
                    before = None
            request = PlanningRequest(str(uuid.uuid4()), QUERIES[index % len(QUERIES)])
            result = session.handle(request)
            effects = {
                key: False
                for key in ("status", "invocations_and_returns", "final_state", "execution")
            }
            if before is not None:
                try:
                    effects = check_effects(
                        index,
                        result["result"],
                        before,
                        dict(device.snapshot().values),
                        device.invocations,
                    )
                except Exception:
                    pass  # Unobservable effects are failed evidence, never inferred success.
            samples.append(
                {
                    "request_id": request.request_id,
                    "checks": effects,
                    "latency_ms": result["total_latency_ms"],
                    "status": str(result["result"]["status"]),
                    "expected_status": EXPECTED_STATUSES[index % len(QUERIES)],
                    "timing": result["timing"],
                    "generation_resources": result["generation_resources"],
                    "outcome_diagnostics": outcome_diagnostics(result["result"]),
                }
            )
            if progress is not None and (index + 1) % 50 == 0:
                progress(_run + 1, index + 1)
            if checkpoint is not None and (index + 1) % 50 == 0:
                checkpoint(report(complete=False, current=samples))
        records.append(_summarize(samples))
        if checkpoint is not None:
            checkpoint(report(complete=False))
    return report(complete=True)
