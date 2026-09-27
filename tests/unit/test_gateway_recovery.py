import sqlite3
from dataclasses import replace
from datetime import timedelta

import pytest

from edge_delegate.contracts import (
    ApprovalGrant,
    PlanIR,
    PlanStep,
    PredicateOperator,
    Route,
    StatePredicate,
)
from edge_delegate.ir import plan_fingerprint, validate_plan
from edge_delegate.runtime import Executor
from edge_delegate.runtime.journal import OperationJournal
from edge_delegate.runtime.ports import (
    CapabilityExecutionError,
    Reconciliation,
    UnknownPhysicalOutcome,
)
from edge_delegate.runtime.recovery import reconcile_operations
from edge_delegate.simulator.examples import local_display


class Device:
    api_version = "edge-delegate-gateway.v2"
    device_id = "guarded-test-device"

    def __init__(self, *, lost_ack=False, guarded_read=False):
        self.world, self.policy = local_display()
        self.clock = self.world.clock
        self.lost_ack = lost_ack
        self.receipts = {}
        self.reconciliation_calls = 0
        self.capability_cards = tuple(
            replace(
                card,
                preconditions=(StatePredicate("display.last_value", PredicateOperator.EQ, None),),
            )
            if card.capability_id == "display.value.show" or guarded_read
            else card
            for card in self.world.capability_cards
        )

    def snapshot(self):
        return self.world.snapshot()

    def invoke(self, *_):
        raise AssertionError("legacy invocation is not permitted")

    def invoke_bounded(self, capability, arguments, *, operation_id, deadline):
        value = self.world.invoke(capability, arguments)
        self.receipts[operation_id] = value
        if self.lost_ack:
            raise UnknownPhysicalOutcome("lost acknowledgement")
        return value

    def reconcile(self, operation_id, *, deadline):
        self.reconciliation_calls += 1
        return Reconciliation("succeeded", self.receipts[operation_id])


def prepare(device, *, read_after=False):
    steps = (
        PlanStep(
            "display", "display.value.show", {"value": 12}, timeout_ms=500, idempotency_key="write"
        ),
    )
    if read_after:
        steps += (PlanStep("read", "sensor.temperature.read", timeout_ms=500),)
    plan = PlanIR("guarded-request", Route.LOCAL, steps=steps)
    return validate_plan(
        plan, device.capability_cards, device.snapshot(), device.policy, now=device.clock.now()
    )


def test_lost_ack_reconciles_after_its_precondition_changes_and_executor_restarts(tmp_path):
    device = Device(lost_ack=True)
    plan = prepare(device)
    path = tmp_path / "journal.sqlite"
    assert (
        Executor(journal=OperationJournal(path)).execute(plan, device, device.policy).status
        == "unknown"
    )
    assert device.snapshot().values["display.last_value"] == 12
    retry = Executor(journal=OperationJournal(path)).execute(plan, device, device.policy)
    assert retry.status == "succeeded"
    assert retry.steps[0].status == "replayed"
    assert device.reconciliation_calls == 1
    assert len(device.world.invocations) == 1


def test_completed_step_guard_does_not_block_a_different_valid_step(tmp_path):
    device = Device()
    result = Executor(journal=OperationJournal(tmp_path / "journal")).execute(
        prepare(device, read_after=True), device, device.policy
    )
    assert result.status == "succeeded"
    assert result.final_output == 24.5
    assert len(device.world.invocations) == 2


def test_current_step_guard_still_blocks_dispatch(tmp_path):
    device = Device(guarded_read=True)
    result = Executor(journal=OperationJournal(tmp_path / "journal")).execute(
        prepare(device, read_after=True), device, device.policy
    )
    assert result.status == "failed"
    assert len(device.world.invocations) == 1


def test_new_dispatch_still_rejects_a_changed_state(tmp_path):
    device = Device()
    plan = prepare(device)
    device.world.write("display.last_value", 99)
    result = Executor(journal=OperationJournal(tmp_path / "journal")).execute(
        plan, device, device.policy
    )
    assert result.status == "failed"
    assert not device.world.invocations


@pytest.mark.parametrize("expire_after_write", [False, True])
def test_current_step_approval_keeps_full_plan_binding(tmp_path, expire_after_write):
    device = Device()
    device.capability_cards = tuple(
        replace(c, approval_required=True) if c.capability_id == "sensor.temperature.read" else c
        for c in device.capability_cards
    )
    plan = PlanIR(
        "approved",
        Route.LOCAL,
        steps=(
            PlanStep("display", "display.value.show", {"value": 12}, idempotency_key="write"),
            PlanStep("read", "sensor.temperature.read"),
        ),
    )
    device.policy = replace(
        device.policy,
        approvals=(
            ApprovalGrant(
                "grant",
                "approved",
                "sensor.temperature.read",
                plan_fingerprint(plan),
                device.clock.now() + timedelta(seconds=60),
            ),
        ),
    )
    validated = validate_plan(
        plan, device.capability_cards, device.snapshot(), device.policy, now=device.clock.now()
    )
    invoke = device.invoke_bounded

    def dispatch(*args, **kwargs):
        value = invoke(*args, **kwargs)
        if expire_after_write:
            device.clock.advance(seconds=120)
        return value

    device.invoke_bounded = dispatch
    result = Executor(journal=OperationJournal(tmp_path / "journal")).execute(
        validated, device, device.policy
    )
    assert result.status == ("failed" if expire_after_write else "succeeded")
    assert len(device.world.invocations) == (1 if expire_after_write else 2)


@pytest.mark.parametrize("receipt", ["transport_error", "bad_result", "unknown", "failed"])
def test_recovery_only_marks_failure_when_receipt_confirms_it(tmp_path, receipt):
    device = Device(lost_ack=True)
    journal = OperationJournal(tmp_path / "journal")
    plan = prepare(device)
    assert Executor(journal=journal).execute(plan, device, device.policy).status == "unknown"

    def recover(operation_id, *, deadline):
        if receipt == "transport_error":
            raise CapabilityExecutionError("offline")
        return (
            Reconciliation("succeeded", "not a boolean")
            if receipt == "bad_result"
            else Reconciliation(receipt)
        )

    device.reconcile = recover
    result = reconcile_operations(journal, device, request_id=plan.plan.request_id)
    assert result["operations"][0]["status"] == ("failed" if receipt == "failed" else "unknown")
    assert len(device.world.invocations) == 1


def test_status_only_recovery_ignores_snapshot_and_never_runs_unstarted_steps(tmp_path):
    device = Device(lost_ack=True)
    journal = OperationJournal(tmp_path / "journal")
    assert (
        Executor(journal=journal)
        .execute(prepare(device, read_after=True), device, device.policy)
        .status
        == "unknown"
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("recovery must not snapshot or dispatch")

    device.snapshot = forbidden
    device.invoke_bounded = forbidden
    result = reconcile_operations(journal, device, request_id="guarded-request")
    assert result["status"] == "reconciled"
    assert result["task_completion_verified"] is False
    assert result["device_actions_dispatched"] == 0
    assert len(device.world.invocations) == 1
    assert len(result["operations"]) == 1
    assert reconcile_operations(journal, device, request_id="unknown")["status"] == "not_found"


def test_old_journal_rows_are_preserved_and_recoverable_by_operation_id(tmp_path):
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE operations (operation_id TEXT PRIMARY KEY, device_id TEXT NOT NULL, fingerprint TEXT NOT NULL, status TEXT NOT NULL, result TEXT)"
        )
        db.execute(
            "INSERT INTO operations VALUES ('legacy','guarded-test-device','fingerprint','unknown',NULL)"
        )
    device = Device()
    device.receipts["legacy"] = True
    journal = OperationJournal(path)
    result = reconcile_operations(journal, device, operation_id="legacy")
    assert result["status"] == "reconciled"
    assert journal.claim("legacy", device.device_id, "fingerprint") == ("succeeded", True)
    assert journal.recorded_operations("other-device", operation_id="legacy") == []


def test_cancellation_requires_device_support_and_never_clears_unknown_locally(tmp_path):
    device = Device(lost_ack=True)
    journal = OperationJournal(tmp_path / "journal")
    Executor(journal=journal).execute(prepare(device), device, device.policy)
    with pytest.raises(ValueError, match="does not support"):
        reconcile_operations(journal, device, request_id="guarded-request", cancel_unknown=True)
    assert (
        journal.recorded_operations(device.device_id, request_id="guarded-request")[0]["status"]
        == "unknown"
    )


def test_lost_cancellation_acknowledgement_keeps_operation_unknown(tmp_path):
    device = Device()
    journal = OperationJournal(tmp_path / "journal")
    journal.claim("operation", device.device_id, "fingerprint", request_id="not-sent")
    device.reconcile = lambda *a, **k: Reconciliation("unknown")

    def lost(*args, **kwargs):
        raise TimeoutError("cancellation reply lost")

    device.cancel_operation = lost
    result = reconcile_operations(journal, device, request_id="not-sent", cancel_unknown=True)
    assert result["status"] == "unknown"
    assert (
        journal.recorded_operations(device.device_id, request_id="not-sent")[0]["status"]
        == "unknown"
    )
