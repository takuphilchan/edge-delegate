import multiprocessing
import os
import sqlite3

import pytest

from edge_delegate.adapters.unix import UnixGateway
from edge_delegate.contracts import PlanningRequest
from edge_delegate.planner.tasks import BoundedPlanner, TaskDecision
from edge_delegate.runtime.journal import OperationJournal
from edge_delegate.runtime.ports import UnknownPhysicalOutcome
from edge_delegate.simulator.examples import local_display
from edge_delegate.simulator.server import serve
from edge_delegate_lab.gateway import GatewaySession

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Unix socket reference adapter")


@pytest.fixture
def emulator(tmp_path):
    processes = []
    tmp_path.chmod(0o700)

    def start(fault="none", *, database=None):
        # WSL sockets must live in the Linux filesystem, pytest tmp_path does.
        socket = tmp_path / f"{len(processes)}.sock"
        ready = multiprocessing.Event()
        process = multiprocessing.Process(
            target=serve,
            args=(str(socket), str(tmp_path / "device.db" if database is None else database)),
            kwargs={"fault": fault, "ready": ready},
        )
        process.start()
        processes.append(process)
        assert ready.wait(20), "emulator did not start"
        return UnixGateway(socket), process

    yield start
    for process in processes:
        process.terminate()
        process.join(5)


def session(device, tmp_path):
    _, policy = local_display()
    return GatewaySession(
        BoundedPlanner(lambda *_: TaskDecision("display_number", {"value": 12})),
        device,
        policy,
        journal_path=tmp_path / "journal.db",
    )


def test_execution_replays_after_session_restart(emulator, tmp_path):
    device, _ = emulator()
    request = PlanningRequest("same", "display 12")
    assert session(device, tmp_path).handle(request)["result"]["status"] == "executed"
    replay = session(device, tmp_path).handle(request)
    assert replay["result"]["execution"]["steps"][0]["status"] == "replayed"
    with sqlite3.connect(tmp_path / "device.db") as db:
        assert db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 1


@pytest.mark.parametrize("fault", ["lost_ack", "malformed"])
def test_lost_ack_reconciles_without_reissuing_write(emulator, tmp_path, fault):
    device, process = emulator(fault)
    request = PlanningRequest("uncertain", "display 12")
    assert session(device, tmp_path).handle(request)["result"]["status"] == "execution_unknown"
    process.terminate()
    process.join(5)
    recovered, _ = emulator()
    result = session(recovered, tmp_path).handle(request)
    assert result["result"]["status"] == "executed"
    assert result["result"]["execution"]["steps"][0]["status"] == "replayed"
    assert recovered.snapshot().values["display.last_value"] == 12


@pytest.mark.parametrize("fault", ["delay", "disconnect"])
def test_timeout_or_disconnect_never_claims_success(emulator, tmp_path, fault):
    device, _ = emulator(fault)
    result = session(device, tmp_path).handle(PlanningRequest("timeout", "display 12"))
    assert result["result"]["status"] == "execution_unknown"


def test_atomic_claim_blocks_other_operations_and_detects_conflicts(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from edge_delegate.runtime.idempotency import IdempotencyConflict

    journal = OperationJournal(tmp_path / "ops.db")
    with ThreadPoolExecutor(8) as pool:
        results = list(
            pool.map(lambda _: journal.claim("same", "device", "fingerprint"), range(20))
        )
    assert sum(status == "claimed" for status, _ in results) == 1
    with pytest.raises(UnknownPhysicalOutcome):
        journal.claim("different", "device", "new")
    with pytest.raises(IdempotencyConflict):
        journal.claim("same", "device", "different")
    with pytest.raises(IdempotencyConflict):
        journal.claim("same", "other-device", "fingerprint")


def test_concurrent_duplicate_requests_invoke_the_device_once(emulator, tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    device, _ = emulator()
    sessions = [session(device, tmp_path), session(device, tmp_path)]
    request = PlanningRequest("concurrent", "Display 12")
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda item: item.handle(request), sessions))
    assert any(result["result"]["status"] == "executed" for result in results)
    with sqlite3.connect(tmp_path / "device.db") as db:
        assert db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 1


def test_stale_observation_blocks_device_invocation(emulator, tmp_path):
    device, _ = emulator("stale")
    result = session(device, tmp_path).handle(PlanningRequest("stale", "Display 12"))
    assert result["result"]["status"] == "invalid_plan"
    with sqlite3.connect(tmp_path / "device.db") as db:
        assert db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 0


def test_cli_reconciles_after_restart_even_when_replanning_is_no_longer_valid(
    emulator, tmp_path, capsys, monkeypatch
):
    import json
    from dataclasses import replace

    from edge_delegate.contracts import PredicateOperator, StatePredicate
    from edge_delegate_lab import cli

    device, process = emulator("lost_ack")
    device._cards = tuple(
        replace(
            card, preconditions=(StatePredicate("display.last_value", PredicateOperator.EQ, None),)
        )
        if card.capability_id == "display.value.show"
        else card
        for card in device.capability_cards
    )
    request = PlanningRequest("changed-guard", "Display 12")
    gateway = session(device, tmp_path)
    assert gateway.handle(request)["result"]["status"] == "execution_unknown"
    assert gateway.handle(request)["result"]["status"] == "invalid_plan"
    process.terminate()
    process.join(5)
    recovered, _ = emulator()

    def no_model():
        raise AssertionError("receipt recovery must not load a planner")

    monkeypatch.setattr(cli, "available_model_plugins", no_model)
    assert (
        cli.main(
            [
                "reconcile",
                "--socket",
                str(recovered.socket_path),
                "--journal",
                str(tmp_path / "journal.db"),
                "--request-id",
                request.request_id,
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "reconciled"
    assert result["device_actions_dispatched"] == 0
    assert result["task_completion_verified"] is False
    with sqlite3.connect(tmp_path / "device.db") as db:
        assert db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 1
    with sqlite3.connect(tmp_path / "journal.db") as db:
        assert (
            db.execute("SELECT COUNT(*) FROM operations WHERE status='unknown'").fetchone()[0] == 0
        )
        assert (
            db.execute("SELECT COUNT(*) FROM audit WHERE event_type='reconciliation'").fetchone()[0]
            == 1
        )


def test_state_is_rechecked_between_dependent_steps(emulator, tmp_path):
    device, _ = emulator("stale_after_read")
    _, policy = local_display()
    gateway = GatewaySession(
        BoundedPlanner(lambda *_: TaskDecision("show_temperature")),
        device,
        policy,
        journal_path=tmp_path / "journal.db",
    )
    result = gateway.handle(PlanningRequest("dependent", "Show temperature"))
    assert result["result"]["status"] == "execution_failed"
    with sqlite3.connect(tmp_path / "device.db") as db:
        assert db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 1


def test_cancel_pre_dispatch_claim_fences_late_invocation_across_restart(emulator, tmp_path):
    import time

    from edge_delegate.runtime.recovery import reconcile_operations

    device, process = emulator()
    journal = OperationJournal(tmp_path / "journal")
    operation = "a" * 64
    journal.claim(operation, device.device_id, "fingerprint", request_id="pre-send-crash")
    assert reconcile_operations(journal, device, request_id="pre-send-crash")["status"] == "unknown"
    result = reconcile_operations(journal, device, request_id="pre-send-crash", cancel_unknown=True)
    assert result["status"] == "reconciled"
    assert result["operations"][0]["status"] == "failed"
    process.terminate()
    process.join(5)
    device, _ = emulator()
    with pytest.raises(UnknownPhysicalOutcome):
        device.invoke_bounded(
            "display.value.show",
            {"value": 99},
            operation_id=operation,
            deadline=time.monotonic() + 1,
        )
    assert device.snapshot().values["display.last_value"] is None
    assert device.reconcile(operation, deadline=time.monotonic() + 1).status == "failed"
    assert journal.claim("new", device.device_id, "new-fingerprint")[0] == "claimed"


def test_cancel_preserves_completed_action_receipt(emulator, tmp_path):
    from edge_delegate.runtime.recovery import reconcile_operations

    device, _ = emulator("lost_ack")
    gateway = session(device, tmp_path)
    assert (
        gateway.handle(PlanningRequest("lost", "display 12"))["result"]["status"]
        == "execution_unknown"
    )
    result = reconcile_operations(gateway.journal, device, request_id="lost", cancel_unknown=True)
    assert result["operations"][0]["status"] == "succeeded"
    assert device.snapshot().values["display.last_value"] == 12


def test_device_identity_is_persisted_and_not_shared_by_new_databases(emulator, tmp_path):
    first, process = emulator()
    other, _ = emulator(database=tmp_path / "other.db")
    assert first.device_id != other.device_id
    process.terminate()
    process.join(5)
    restarted, _ = emulator()
    assert restarted.device_id == first.device_id


def test_legacy_device_receipts_keep_identity_during_upgrade(emulator, tmp_path):
    import time

    with sqlite3.connect(tmp_path / "device.db") as db:
        db.execute("CREATE TABLE receipts (id TEXT PRIMARY KEY, fingerprint TEXT, result TEXT)")
        db.execute("INSERT INTO receipts VALUES (?,?,?)", ("a" * 64, "fingerprint", "true"))
    device, _ = emulator()
    assert device.device_id == "reference-emulator"
    receipt = device.reconcile("a" * 64, deadline=time.monotonic() + 1)
    assert receipt.status == "succeeded" and receipt.result is True


def test_cancellation_racing_dispatch_has_one_durable_outcome(emulator):
    import time
    from concurrent.futures import ThreadPoolExecutor

    device, _ = emulator()
    operation = "b" * 64

    def invoke():
        try:
            return device.invoke_bounded(
                "display.value.show",
                {"value": 42},
                operation_id=operation,
                deadline=time.monotonic() + 2,
            )
        except UnknownPhysicalOutcome:
            return None

    with ThreadPoolExecutor(2) as pool:
        dispatch = pool.submit(invoke)
        cancel = pool.submit(device.cancel_operation, operation, deadline=time.monotonic() + 2)
        dispatch.result()
        fenced = cancel.result()
    receipt = device.reconcile(operation, deadline=time.monotonic() + 1)
    assert receipt.status == fenced.status
    assert device.snapshot().values["display.last_value"] == (
        42 if receipt.status == "succeeded" else None
    )
