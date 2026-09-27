from concurrent.futures import ThreadPoolExecutor

import pytest

from edge_delegate.contracts import PlanIR, PlanningRequest, PlanStep, Route
from edge_delegate.planner.tasks import BoundedPlanner, TaskDecision
from edge_delegate.runtime.idempotency import IdempotencyConflict
from edge_delegate.runtime.journal import OperationJournal
from edge_delegate_lab.gateway import GatewaySession
from tests.unit.test_gateway_recovery import Device


def test_retry_recovers_plan_without_calling_changed_model(tmp_path):
    device = Device()
    device.capability_cards = device.world.capability_cards
    path = tmp_path / "journal"
    request = PlanningRequest("same", "Show temperature")
    first = GatewaySession(
        BoundedPlanner(lambda *_: TaskDecision("read_temperature")),
        device,
        device.policy,
        journal_path=path,
    )
    assert first.handle(request)["result"]["status"] == "executed"

    def no_replanning(*_):
        raise AssertionError("a retry must use the original proposal")

    restarted = GatewaySession(
        BoundedPlanner(no_replanning),
        device,
        device.policy,
        journal_path=path,
    )
    result = restarted.handle(request)["result"]
    assert result["status"] == "executed"
    assert len(result["execution"]["steps"]) == 1
    assert result["execution"]["steps"][0]["status"] == "replayed"
    assert device.snapshot().values["display.last_value"] is None
    assert len(device.world.invocations) == 1
    assert (
        restarted.handle(PlanningRequest("same", "Display 99"))["result"]["status"]
        == "request_conflict"
    )


def test_changed_plan_cannot_append_a_new_step(tmp_path):
    journal = OperationJournal(tmp_path / "journal")
    original = PlanIR("same", Route.LOCAL, steps=(PlanStep("read", "sensor.temperature.read"),))
    changed = PlanIR(
        "same",
        Route.LOCAL,
        steps=(*original.steps, PlanStep("write", "display.value.show", {"value": 12})),
    )
    journal.bind_plan("device", original)
    with pytest.raises(IdempotencyConflict):
        journal.bind_plan("device", changed)
    with pytest.raises(IdempotencyConflict):
        journal.bind_plan("different-device", original)


def test_identical_binding_does_not_rewrite_durable_plan(tmp_path):
    journal = OperationJournal(tmp_path / "journal")
    plan = PlanIR("same", Route.LOCAL, steps=(PlanStep("read", "sensor.temperature.read"),))
    journal.request_plan("device", PlanningRequest("same", "Read temperature"))
    journal.bind_plan("device", plan)
    with journal.connection() as db:
        db.execute("""CREATE TRIGGER no_rewrite BEFORE UPDATE ON requests
                      BEGIN SELECT RAISE(ABORT, 'redundant update'); END""")
    # This is the second binding performed by Executor, or after process restart.
    OperationJournal(tmp_path / "journal").bind_plan("device", plan)


def test_journal_timing_preserves_rollback_and_full_sync(tmp_path):
    journal = OperationJournal(tmp_path / "journal")
    before = journal.timing_snapshot()
    with pytest.raises(RuntimeError, match="abort"):
        with journal.connection() as db:
            assert db.execute("PRAGMA synchronous").fetchone()[0] == 2
            db.execute("INSERT INTO requests VALUES ('abort','device',NULL,NULL)")
            raise RuntimeError("abort")
    after = journal.timing_snapshot()
    assert after["transactions"] == before["transactions"] + 1
    assert all(value >= before[key] for key, value in after.items())
    with journal.connection() as db:
        assert db.execute("SELECT 1 FROM requests WHERE request_id='abort'").fetchone() is None


def test_competing_first_plans_have_one_winner(tmp_path):
    journal = OperationJournal(tmp_path / "journal")
    request = PlanningRequest("same", "request")
    journal.request_plan("device", request)

    def bind(value):
        plan = PlanIR(
            "same", Route.LOCAL, steps=(PlanStep("write", "display.value.show", {"value": value}),)
        )
        try:
            journal.bind_plan("device", plan)
            return True
        except IdempotencyConflict:
            return False

    with ThreadPoolExecutor(2) as pool:
        assert sum(pool.map(bind, [1, 2])) == 1
    assert journal.request_plan("device", request) is not None


def test_request_fingerprint_covers_locale_metadata_and_device(tmp_path):
    journal = OperationJournal(tmp_path / "journal")
    request = PlanningRequest("same", "text", metadata={"target": "one"})
    assert journal.request_plan("device", request) is None
    for device, changed in [
        ("other", request),
        ("device", PlanningRequest("same", "text", "fr", request.metadata)),
        ("device", PlanningRequest("same", "text", metadata={"target": "two"})),
    ]:
        with pytest.raises(IdempotencyConflict):
            journal.request_plan(device, changed)


def test_legacy_operations_require_receipt_recovery_not_replanning(tmp_path):
    journal = OperationJournal(tmp_path / "journal")
    journal.claim("operation", "device", "fingerprint", request_id="old")
    with pytest.raises(IdempotencyConflict, match="legacy"):
        journal.request_plan("device", PlanningRequest("old", "request"))


def test_direct_executor_cannot_extend_a_completed_request(tmp_path):
    from edge_delegate.ir import validate_plan
    from edge_delegate.runtime import Executor

    device = Device()
    journal = OperationJournal(tmp_path / "journal")
    executor = Executor(journal=journal)
    original = PlanIR("same", Route.LOCAL, steps=(PlanStep("read", "sensor.temperature.read"),))
    changed = PlanIR(
        "same",
        Route.LOCAL,
        steps=(
            *original.steps,
            PlanStep("display", "display.value.show", {"value": 12}, idempotency_key="write"),
        ),
    )

    def validate(plan):
        return validate_plan(
            plan, device.capability_cards, device.snapshot(), device.policy, now=device.clock.now()
        )

    assert executor.execute(validate(original), device, device.policy).status == "succeeded"
    assert executor.execute(validate(changed), device, device.policy).status == "failed"
    assert len(device.world.invocations) == 1
    assert device.snapshot().values["display.last_value"] is None


def test_cached_proposal_does_not_bypass_new_policy(tmp_path):
    from edge_delegate.contracts import Policy

    device = Device()
    device.capability_cards = device.world.capability_cards
    planner = BoundedPlanner(lambda *_: TaskDecision("display_number", {"value": 12}))
    path = tmp_path / "journal"
    request = PlanningRequest("same", "Display 12")
    first = GatewaySession(planner, device, device.policy, journal_path=path)
    assert first.handle(request)["result"]["status"] == "executed"
    restricted = GatewaySession(planner, device, Policy("revoked"), journal_path=path)
    assert restricted.handle(request)["result"]["status"] == "invalid_plan"
    assert len(device.world.invocations) == 1
