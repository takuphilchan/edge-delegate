"""Receipt recovery and optional device fences; never dispatch or resume task actions."""

import time
from datetime import UTC, datetime

from edge_delegate.contracts._validation import json_value
from edge_delegate.contracts.capability import ValueSpec

from .ports import CancellationGateway, DeadlineGateway


def reconcile_operations(
    journal, device, *, request_id=None, operation_id=None, timeout_ms=500, cancel_unknown=False
):
    if not isinstance(device, DeadlineGateway) or device.api_version != "edge-delegate-gateway.v2":
        raise ValueError("reconciliation requires a deadline-aware gateway")
    if type(timeout_ms) is not int or not 1 <= timeout_ms <= 5000:
        raise ValueError("reconciliation timeout must be 1..5000 ms")
    if cancel_unknown and not isinstance(device, CancellationGateway):
        raise ValueError("adapter does not support durable operation cancellation")
    rows = journal.recorded_operations(
        device.device_id, request_id=request_id, operation_id=operation_id
    )
    deadline = time.monotonic() + timeout_ms / 1000
    results = []
    for row in rows:
        if row["status"] not in {"unknown", "succeeded", "failed"}:
            raise ValueError("unrecognized journal status; recovery stopped")
        item = {key: row[key] for key in ("operation_id", "request_id", "status")}
        if row["status"] == "unknown":
            try:
                if time.monotonic() >= deadline:
                    raise TimeoutError("reconciliation deadline exhausted")
                receipt = device.reconcile(row["operation_id"], deadline=deadline)
                if receipt.status == "unknown" and cancel_unknown:
                    # The device must serialize fencing with dispatch. A missing receipt
                    # does not authorize us to mark failure on the host alone.
                    receipt = device.cancel_operation(row["operation_id"], deadline=deadline)
                if receipt.status not in {"succeeded", "failed", "unknown"}:
                    raise ValueError("invalid reconciliation status")
                result = None
                if receipt.status == "succeeded":
                    result = json_value(receipt.result, "$.receipt.result")
                    metadata = row["metadata"]
                    if metadata is not None:
                        raw_spec = metadata["result_spec"]
                        spec = (
                            None
                            if raw_spec is None
                            else ValueSpec.from_dict(raw_spec, "$.result_spec")
                        )
                        if (spec is None and result is not None) or (
                            spec is not None and not spec.matches(result)
                        ):
                            raise ValueError("receipt violates recorded result contract")
                if receipt.status in {"succeeded", "failed"}:
                    journal.finish(row["operation_id"], receipt.status, result)
                    item["status"] = receipt.status
            except Exception as exc:
                # Transport or decoding failure is not proof of physical failure.
                item["error"] = f"reconciliation unavailable: {type(exc).__name__}"
        results.append(item)
        journal.append(
            request_id=row["request_id"] or row["operation_id"],
            event_type="cancellation" if cancel_unknown else "reconciliation",
            outcome=item["status"],
            details={"operation_id": row["operation_id"]},
            timestamp=datetime.now(UTC),
        )
    return {
        "schema_version": "edge-gateway-reconciliation.v1",
        "status": "not_found"
        if not results
        else ("unknown" if any(row["status"] == "unknown" for row in results) else "reconciled"),
        "operations": results,
        "device_actions_dispatched": 0,
        "task_completion_verified": False,
    }
