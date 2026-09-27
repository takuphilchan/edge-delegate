"""Small automated latency smoke test, not a model qualification dataset."""

import json
import math
import subprocess
import time
import uuid

from edge_delegate.contracts import PlanningRequest
from edge_delegate.evaluation.outcomes import _equal

from .benchmark import EXPECTED_STATUSES, QUERIES

PHASES = ("burst", "idle", "burst_after_idle")


def storage_info(directory):
    """Record actual filesystem provenance; never silently call tmpfs durable storage."""
    try:
        result = subprocess.run(
            ["findmnt", "-J", "-T", str(directory), "-o", "TARGET,SOURCE,FSTYPE"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return {"unavailable": type(exc).__name__}


class TracedDevice:
    """Transparent transport wrapper recording attempted invocations for smoke assertions."""

    def __init__(self, device):
        self.device = device
        self.invocations = []

    @property
    def api_version(self):
        return self.device.api_version

    @property
    def device_id(self):
        return self.device.device_id

    @property
    def clock(self):
        return self.device.clock

    @property
    def capability_cards(self):
        return self.device.capability_cards

    @property
    def transport_ms(self):
        return self.device.transport_ms

    def snapshot(self):
        return self.device.snapshot()

    def reconcile(self, operation_id, *, deadline):
        return self.device.reconcile(operation_id, deadline=deadline)

    def invoke_bounded(self, capability_id, arguments, *, operation_id, deadline):
        call = {"capability_id": capability_id, "arguments": dict(arguments)}
        self.invocations.append(call)
        result = self.device.invoke_bounded(
            capability_id,
            arguments,
            operation_id=operation_id,
            deadline=deadline,
        )
        call["result"] = result
        return result


def check_effects(index, result, before, after, invocations):
    """Independently specified effects for the six fixed smoke requests."""
    index %= len(QUERIES)
    temperature = before["environment.temperature_c"]
    read = {"capability_id": "sensor.temperature.read", "arguments": {}, "result": temperature}

    def display(value):
        return {
            "capability_id": "display.value.show",
            "arguments": {"value": value},
            "result": True,
        }

    expected_calls = ([read], [read, display(temperature)], [display(12)], [display(-3.5)], [], [])[
        index
    ]
    expected_state = dict(before)
    if index in (1, 2, 3):
        expected_state["display.last_value"] = (temperature, 12, -3.5)[index - 1]
    expected_final = (temperature, True, True, True, None, None)[index]
    execution = result.get("execution")
    return {
        "status": result["status"] == EXPECTED_STATUSES[index],
        "invocations_and_returns": _equal(invocations, expected_calls),
        "final_state": _equal(after, expected_state),
        "execution": (
            execution is not None
            and execution["status"] == "succeeded"
            and _equal(execution["final_output"], expected_final)
        )
        if index < 4
        else execution is None,
    }


def iter_samples(session, device, *, count=12, idle_seconds=3, sleep=time.sleep):
    if not 6 <= count <= 200 or not 0 <= idle_seconds <= 60:
        raise ValueError("count must be 6..200; idle-seconds must be 0..60")
    for phase in PHASES:
        pause = idle_seconds if phase == "idle" else 0
        for index in range(count):
            before = dict(device.snapshot().values)
            device.invocations.clear()
            if pause:
                sleep(pause)
            request = PlanningRequest(str(uuid.uuid4()), QUERIES[index % len(QUERIES)])
            response = session.handle(request)
            # These independent observations are outside the timed handle(), not
            # subtracted from an end-to-end measurement after the fact.
            after = dict(device.snapshot().values)
            checks = check_effects(index, response["result"], before, after, device.invocations)
            yield {
                "phase": phase,
                "index": index,
                "request_id": request.request_id,
                "query": request.text,
                "idle_seconds": pause,
                "expected_status": EXPECTED_STATUSES[index % len(QUERIES)],
                "status": response["result"]["status"],
                "total_ms": response["total_latency_ms"],
                "timing": response["timing"],
                "resources": response["generation_resources"],
                "checks": checks,
                "passed": all(checks.values()),
                "before": before,
                "after": after,
                "invocations": list(device.invocations),
            }


def summarize(samples):
    summary = {}
    for phase in PHASES:
        selected = [sample for sample in samples if sample["phase"] == phase]
        values = sorted(sample["total_ms"] for sample in selected)
        if values:
            summary[phase] = {
                "count": len(values),
                "p50_ms": values[math.ceil(len(values) * 0.5) - 1],
                "p95_ms": values[math.ceil(len(values) * 0.95) - 1],
                "max_ms": max(values),
                "status_mismatches": sum(s["status"] != s["expected_status"] for s in selected),
                "failed_checks": sum(not s["passed"] for s in selected),
            }
    return summary
