import os
import sqlite3

import pytest

from edge_delegate.application import GatewaySession
from edge_delegate.contracts import PlanningRequest
from edge_delegate.planner.tasks import BoundedPlanner, TaskDecision
from edge_delegate.simulator.examples import local_display
from edge_delegate_lab.gateway import GatewaySession as LegacySession
from tests.integration.test_durable_gateway import emulator  # noqa: F401

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Unix reference adapter")


def test_public_session_preview_lifecycle_and_compatibility(emulator, tmp_path):  # noqa: F811
    device, _ = emulator()
    assert LegacySession is GatewaySession
    session = GatewaySession(
        BoundedPlanner(lambda *_: TaskDecision("display_number", {"value": 12})),
        device,
        local_display()[1],
        journal_path=tmp_path / "journal.db",
    )
    with session:
        assert session.status()["state"] == "ready"
        request = PlanningRequest("sdk-request", "Display 12")
        preview = session.preview(request)
        assert preview["execution_attempted"] is False
        with sqlite3.connect(tmp_path / "device.db") as db:
            assert db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 0
        with session._exclusive(), pytest.raises(RuntimeError, match="busy"):
            session.execute(request)
        assert session.execute(request)["schema_version"] == "edge-gateway-result.v1"
        assert session.reconcile(request_id=request.request_id)["device_actions_dispatched"] == 0
    assert session.status()["state"] == "closed"
    session.close()
    with pytest.raises(RuntimeError, match="closed"):
        session.handle(request)
    with pytest.raises(RuntimeError, match="closed"):
        session.preview(request)


def test_benchmark_checks_effects_not_just_executed_status(emulator, tmp_path):  # noqa: F811
    from edge_delegate_lab.benchmark import QUERIES, benchmark
    from edge_delegate_lab.latency_profile import TracedDevice

    decisions = dict(
        zip(
            QUERIES,
            (
                TaskDecision("read_temperature"),
                TaskDecision("show_temperature"),
                TaskDecision("display_number", {"value": 99}),  # deliberately wrong
                TaskDecision("display_number", {"value": -3.5}),
                TaskDecision("clarify"),
                TaskDecision("deny"),
            ),
            strict=True,
        )
    )
    device, _ = emulator()
    gateway = GatewaySession(
        BoundedPlanner(lambda request, _: decisions[request.text]),
        TracedDevice(device),
        local_display()[1],
        journal_path=tmp_path / "benchmark.db",
    )
    report = benchmark(gateway, count=6, runs=1)
    cases = report["runs"][0]["samples"]
    assert cases[2]["status"] == cases[2]["expected_status"] == "executed"
    assert cases[2]["checks"]["final_state"] is False
    assert cases[2]["checks"]["invocations_and_returns"] is False
    assert all(all(c["checks"].values()) for i, c in enumerate(cases) if i != 2)


def test_command_plugin_executes_zero_but_never_partial_compound(emulator, tmp_path):  # noqa: F811
    from edge_delegate.model_plugins.bounded_commands import plugin

    device, _ = emulator()
    model = plugin.create_diagnostic_session(
        artifact_path=None, settings={"numeric_policy": "decimal.v1"}
    )
    with GatewaySession(
        model.planner, device, local_display()[1], journal_path=tmp_path / "commands.db"
    ) as gateway:
        zero = gateway.execute(PlanningRequest("zero", "Display 0."))
        assert zero["result"]["status"] == "executed"
        result = gateway.execute(
            PlanningRequest("compound", "Display 12 then upload the temperature.")
        )
        assert result["result"]["status"] == "denied"
        assert result["result"]["execution"] is None
        assert device.snapshot().values["display.last_value"] == 0
        with sqlite3.connect(tmp_path / "device.db") as db:
            assert db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 1
