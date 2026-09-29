import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from edge_delegate.application import (
    ControlSession,
    DeviceRegistration,
    DeviceRegistry,
    TargetResolutionError,
)
from edge_delegate.cli import main
from edge_delegate.contracts import PlanIR
from edge_delegate.contracts.capability import ValueKind, ValueSpec
from edge_delegate.contracts.control import ControlRequest, ControlTarget
from edge_delegate.contracts.policy import ApprovalGrant
from edge_delegate.ir import plan_fingerprint
from edge_delegate.planner.control import ControlInputError, light_catalog, parse_light_command
from edge_delegate.planner.control_catalog import ControlAction, ControlCatalog
from edge_delegate.simulator.control_demo import open_light_demo
from edge_delegate.simulator.lights import LightEmulator, light_policy


def request(session, request_id="set-1", target="inspection light", value=40):
    return session.request(
        request_id=request_id,
        target=target,
        action="light.brightness.set",
        parameters={"percent": value},
    )


def outcome(response):
    return response["gateway"]["result"]["status"]


def values(session, name):
    return session.registry.entry(session.registry.resolve(name)).device.snapshot().values


def receipt_count(path):
    with sqlite3.connect(path) as db:
        return db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]


def test_preview_and_targeted_execution_do_not_touch_other_light(tmp_path):
    with open_light_demo(tmp_path) as session:
        control = request(session)
        assert ControlRequest.from_dict(control.to_dict()) == control
        preview = session.preview(control)
        assert preview["gateway"]["execution_attempted"] is False
        assert preview["gateway"]["validation"]["issues"] == ()
        assert receipt_count(tmp_path / "inspection.sqlite") == 0
        with sqlite3.connect(tmp_path / "gateway.sqlite") as db:
            assert db.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 0
        assert outcome(session.execute(control)) == "executed"
        assert values(session, "inspection light")["light.brightness_percent"] == 40
        assert values(session, "inspection light")["light.power"] is False
        assert values(session, "workbench light")["light.brightness_percent"] == 100
        assert receipt_count(tmp_path / "workbench.sqlite") == 0


def test_ambiguous_and_unknown_targets_do_not_resolve_by_action_or_order(tmp_path):
    with open_light_demo(tmp_path) as session:
        response = session.command("Set the light to 40 percent.", request_id="amb", execute=True)
        assert response["status"] == "clarification_required"
        assert response["choices"] == ["inspection light", "workbench light"]
        assert response["execution_attempted"] is False
        response = session.command("Turn the absent light off.", request_id="missing", execute=True)
        assert response["status"] == "clarification_required"
        assert receipt_count(tmp_path / "inspection.sqlite") == 0
        assert receipt_count(tmp_path / "workbench.sqlite") == 0


@pytest.mark.parametrize(
    "text",
    [
        "Turn the inspection light on then turn the workbench light off.",
        "Do not turn the inspection light on.",
        'Say "Turn the inspection light on."',
        "Set the inspection light to 40 percent and upload its state.",
        "Set the inspection light to .5 percent.",
        "Set the inspection light to 4e1 percent.",
        "Toggle the inspection light.",
    ],
)
def test_unsupported_phrases_never_partially_execute(tmp_path, text):
    with open_light_demo(tmp_path) as session:
        response = session.command(text, request_id="bad", execute=True)
        assert response["execution_attempted"] is False
        assert receipt_count(tmp_path / "inspection.sqlite") == 0


@pytest.mark.parametrize("value", [-1, 101, True, 40.5, float("nan"), "40", None])
def test_invalid_parameters_fail_before_dispatch(tmp_path, value):
    with open_light_demo(tmp_path) as session:
        with pytest.raises(ValueError):
            request(session, value=value)
        assert receipt_count(tmp_path / "inspection.sqlite") == 0


@pytest.mark.parametrize("value", [0, 40, 100])
def test_brightness_boundaries(tmp_path, value):
    with open_light_demo(tmp_path) as session:
        assert outcome(session.execute(request(session, value=value))) == "executed"
        assert values(session, "inspection light")["light.brightness_percent"] == value


def test_power_and_read_controls(tmp_path):
    with open_light_demo(tmp_path) as session:
        assert (
            outcome(
                session.command(
                    "Turn the workbench light on.",
                    request_id="on",
                    execute=True,
                )
            )
            == "executed"
        )
        read = session.command("Read the workbench light power.", request_id="read", execute=True)
        assert read["gateway"]["result"]["execution"]["final_output"] is True
        assert values(session, "inspection light")["light.power"] is False
        assert (
            outcome(
                session.command(
                    "Turn the workbench light off.",
                    request_id="off",
                    execute=True,
                )
            )
            == "executed"
        )
        read = session.command(
            "Read the workbench light brightness.",
            request_id="brightness",
            execute=True,
        )
        assert read["gateway"]["result"]["execution"]["final_output"] == 100


def test_changed_request_id_payload_or_target_is_rejected(tmp_path):
    with open_light_demo(tmp_path) as session:
        control = request(session)
        assert outcome(session.execute(control)) == "executed"
        assert outcome(session.execute(request(session, value=50))) == "request_conflict"
        assert (
            outcome(session.execute(request(session, target="workbench light")))
            == "request_conflict"
        )
        assert receipt_count(tmp_path / "workbench.sqlite") == 0
        assert values(session, "inspection light")["light.brightness_percent"] == 40


def test_restart_retry_returns_old_receipt_not_current_state(tmp_path):
    with open_light_demo(tmp_path) as session:
        original = request(session)
        assert outcome(session.execute(original)) == "executed"
        assert outcome(session.execute(request(session, "new-value", value=60))) == "executed"
    with open_light_demo(tmp_path) as session:
        result = session.execute(ControlRequest.from_dict(original.to_dict()))
        assert outcome(result) == "executed"
        execution = result["gateway"]["result"]["execution"]
        assert execution["steps"][0]["status"] == "replayed"
        assert execution["final_output"] == 40
        assert values(session, "inspection light")["light.brightness_percent"] == 60
        assert receipt_count(tmp_path / "inspection.sqlite") == 2


def test_lost_ack_blocks_new_work_until_reconciliation_without_replay(tmp_path):
    with open_light_demo(tmp_path) as session:
        original = request(session)
        session.registry.entry(original.target).device.lose_ack = True
        assert outcome(session.execute(original)) == "execution_unknown"
        assert values(session, "inspection light")["light.brightness_percent"] == 40
    with open_light_demo(tmp_path) as session:
        assert (
            outcome(session.execute(request(session, "blocked", value=60))) == "execution_unknown"
        )
        assert receipt_count(tmp_path / "inspection.sqlite") == 1
        report = session.reconcile(target=original.target, request_id=original.request_id)
        assert report["device_actions_dispatched"] == 0
        assert outcome(session.execute(original)) == "executed"
        assert receipt_count(tmp_path / "inspection.sqlite") == 1


def test_replacement_device_cannot_receive_old_request(tmp_path):
    with open_light_demo(tmp_path / "old") as old:
        original = request(old)
    with open_light_demo(tmp_path / "new") as replacement:
        with pytest.raises(ValueError, match="identity or configuration"):
            replacement.execute(original)
        assert receipt_count(tmp_path / "new" / "inspection.sqlite") == 0


def test_configuration_drift_is_fenced_before_execute(tmp_path):
    with open_light_demo(tmp_path) as session:
        original = request(session)
        device = session.registry.entry(original.target).device
        device.capability_cards = device.capability_cards[:-1]
        with pytest.raises(ValueError, match="identity or configuration"):
            session.execute(original)
        assert receipt_count(tmp_path / "inspection.sqlite") == 0


def test_permission_rejection_still_uses_runtime_validator(tmp_path):
    light = LightEmulator(tmp_path / "light.db")
    policy = replace(light_policy(), granted_permissions=frozenset())
    registry = DeviceRegistry([DeviceRegistration("light", light, policy)])
    with ControlSession(
        registry, catalog=light_catalog(), journal_path=tmp_path / "journal.db"
    ) as session:
        control = request(session, target="light")
        assert session.preview(control)["gateway"]["validation"]["issues"]
        assert outcome(session.execute(control)) == "invalid_plan"
        assert receipt_count(tmp_path / "light.db") == 0


def test_approval_can_be_added_but_cannot_move_to_other_target(tmp_path):
    a, b = LightEmulator(tmp_path / "a.db"), LightEmulator(tmp_path / "b.db")
    for light in (a, b):
        light.capability_cards = tuple(
            replace(card, approval_required=True) for card in light.capability_cards
        )
    policy = light_policy()
    registry = DeviceRegistry([DeviceRegistration("a", a, policy)])
    with ControlSession(
        registry, catalog=light_catalog(), journal_path=tmp_path / "journal.db"
    ) as session:
        control = request(session, target="a")
        preview = session.preview(control)
        plan = PlanIR.from_dict(preview["gateway"]["plan"])
        assert outcome(session.execute(control)) == "invalid_plan"
    approved = replace(
        policy,
        approvals=(
            ApprovalGrant(
                "grant",
                control.request_id,
                control.action,
                plan_fingerprint(plan),
                datetime.now(UTC) + timedelta(minutes=1),
            ),
        ),
    )
    registry = DeviceRegistry([DeviceRegistration("a", a, approved)])
    with ControlSession(
        registry, catalog=light_catalog(), journal_path=tmp_path / "journal.db"
    ) as session:
        assert session.registry.resolve("a") == control.target
        assert outcome(session.execute(control)) == "executed"
    registry = DeviceRegistry([DeviceRegistration("b", b, approved)])
    with ControlSession(
        registry, catalog=light_catalog(), journal_path=tmp_path / "other-journal.db"
    ) as session:
        assert outcome(session.execute(request(session, target="b"))) == "invalid_plan"
        assert receipt_count(tmp_path / "b.db") == 0


def test_drift_between_snapshot_and_dispatch_still_fences_write(tmp_path):
    with open_light_demo(tmp_path) as session:
        control = request(session)
        light = session.registry.entry(control.target).device
        snapshot = light.snapshot
        calls = 0

        def changed():
            nonlocal calls
            state = snapshot()
            calls += 1
            if calls == 2:  # fresh per-step snapshot, after durable claim
                light.capability_cards = light.capability_cards[:-1]
            return state

        light.snapshot = changed
        assert outcome(session.execute(control)) in {"execution_failed", "execution_unknown"}
        assert receipt_count(tmp_path / "inspection.sqlite") == 0


def test_stale_state_is_rejected(tmp_path):
    with open_light_demo(tmp_path) as session:
        control = request(session)
        light = session.registry.entry(control.target).device
        state = replace(light.snapshot(), observed_at=datetime.now(UTC) - timedelta(minutes=1))
        light.snapshot = lambda: state
        assert outcome(session.execute(control)) == "invalid_plan"
        assert receipt_count(tmp_path / "inspection.sqlite") == 0


def test_concurrent_duplicate_sessions_only_dispatch_once(tmp_path):
    with open_light_demo(tmp_path) as first, open_light_demo(tmp_path) as second:
        control = request(first)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda session: session.execute(control), [first, second]))
        assert all(outcome(result) in {"executed", "execution_unknown"} for result in results)
        assert receipt_count(tmp_path / "inspection.sqlite") == 1
        assert outcome(first.execute(control)) == "executed"


def test_registry_collision_and_contract_mutations(tmp_path):
    a, b = LightEmulator(tmp_path / "a"), LightEmulator(tmp_path / "b")
    with pytest.raises(ValueError, match="duplicate"):
        DeviceRegistry(
            [
                DeviceRegistration("Light", a, light_policy()),
                DeviceRegistration("light", b, light_policy()),
            ]
        )
    registry = DeviceRegistry(
        [
            DeviceRegistration("a", a, light_policy(), aliases=("b",)),
            DeviceRegistration("b", b, light_policy()),
        ]
    )
    with pytest.raises(TargetResolutionError):
        registry.resolve("b")
    target = registry.resolve("a")
    with pytest.raises(ValueError):
        registry.entry(ControlTarget(target.device_id, "other", target.binding_sha256))
    with pytest.raises(ValueError):
        ControlRequest.from_dict({"schema_version": "edge-control-request.v9"})
    parameters = {"on": True}
    control = ControlRequest(
        "a", target, "light.power.set", parameters, light_catalog().fingerprint
    )
    parameters["on"] = False
    assert control.parameters["on"] is True
    with pytest.raises(TypeError):
        control.parameters["on"] = False
    wire = control.to_dict()
    wire["extra"] = True
    with pytest.raises(ValueError):
        ControlRequest.from_dict(wire)


def test_adapter_deadlines_fingerprints_and_storage_identity(tmp_path):
    light = LightEmulator(tmp_path / "light.db")
    with pytest.raises(TimeoutError):
        light.invoke_bounded("light.power.set", {"on": True}, operation_id="expired", deadline=0)
    assert receipt_count(tmp_path / "light.db") == 0
    assert (
        light.invoke_bounded(
            "light.power.set",
            {"on": True},
            operation_id="x",
            deadline=time.monotonic() + 1,
        )
        is True
    )
    with pytest.raises(ValueError, match="invalid light"):
        light.invoke_bounded(
            "light.power.set", {"on": 1}, operation_id="bad", deadline=time.monotonic() + 1
        )
    with pytest.raises(Exception, match="arguments changed"):
        light.invoke_bounded(
            "light.power.set", {"on": False}, operation_id="x", deadline=time.monotonic() + 1
        )
    with sqlite3.connect(tmp_path / "light.db") as db:
        db.execute("UPDATE light SET id='replacement'")
    with pytest.raises(Exception, match="identity changed"):
        light.snapshot()


def test_lifecycle_and_parser_limits(tmp_path):
    session = open_light_demo(tmp_path)
    with pytest.raises(RuntimeError, match="start"):
        session.execute(request(session))
    session.start()
    with session._exclusive(), pytest.raises(RuntimeError, match="busy"):
        session.execute(request(session))
    session.close()
    session.close()
    with pytest.raises(RuntimeError, match="closed"):
        session.command("nonsense", request_id="closed")
    for text in (None, "", "a" * 8001):
        with pytest.raises(ControlInputError):
            parse_light_command(text)
    with pytest.raises(ControlInputError) as info:
        parse_light_command("Set the light to 101 percent")
    assert info.value.status == "clarification_required"


def test_cli_preview_requires_explicit_execute(tmp_path, capsys):
    args = [
        "control-demo",
        "--directory",
        str(tmp_path),
        "--text",
        "Set the inspection light to 40%.",
    ]
    assert main(args) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["state"]["inspection light"]["light.brightness_percent"] == 100
    assert main([*args, "--execute", "--request-id", "cli"]) == 0
    assert (
        json.loads(capsys.readouterr().out)["state"]["inspection light"]["light.brightness_percent"]
        == 40
    )
    assert (
        main(
            [
                "control-demo",
                "--directory",
                str(tmp_path),
                "--text",
                "Turn the light on",
                "--execute",
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().out)["response"]["status"] == "clarification_required"


def test_installed_catalog_mapping_without_application_family_conditionals(tmp_path):
    light = LightEmulator(tmp_path / "light.db")
    registry = DeviceRegistry([DeviceRegistration("indicator", light, light_policy())])
    action = ControlAction(
        "indicator.enable",
        "light.power.set",
        {"on": ValueSpec(ValueKind.BOOLEAN)},
        "Set explicit boolean indicator power.",
    )
    catalog = ControlCatalog("indicator.v1", (action,))
    with ControlSession(registry, catalog=catalog, journal_path=tmp_path / "journal.db") as session:
        control = session.request(
            request_id="custom",
            target="indicator",
            action="indicator.enable",
            parameters={"on": True},
        )
        assert outcome(session.execute(control)) == "executed"
        assert light.snapshot().values["light.power"] is True
        with pytest.raises(ValueError, match="no command parser"):
            session.command("turn on", request_id="not-configured")
    changed = ControlCatalog("indicator.v2", (action,))
    with ControlSession(registry, catalog=changed, journal_path=tmp_path / "journal.db") as session:
        with pytest.raises(ValueError, match="catalog changed"):
            session.execute(control)
    assert receipt_count(tmp_path / "light.db") == 1
    with pytest.raises(ValueError, match="duplicate"):
        ControlCatalog("bad", (action, action))
    with pytest.raises(ValueError, match="missing"):
        catalog.validate("indicator.enable", {})
    with pytest.raises(ValueError, match="unknown"):
        catalog.validate("indicator.enable", {"on": True, "extra": True})


def test_execute_flag_is_not_coerced_from_text(tmp_path):
    with open_light_demo(tmp_path) as session:
        with pytest.raises(ValueError, match="explicit boolean"):
            session.command("Turn the inspection light on.", request_id="flag", execute="false")
        assert receipt_count(tmp_path / "inspection.sqlite") == 0


def test_control_wire_schema_and_strict_runtime_parser(tmp_path):
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/control-request.v1.schema.json").read_text()
    )
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    with open_light_demo(tmp_path) as session:
        wire = request(session).to_dict()
        validator.validate(wire)
        for key in wire:
            bad = {k: v for k, v in wire.items() if k != key}
            assert not validator.is_valid(bad)
            with pytest.raises(ValueError):
                ControlRequest.from_dict(bad)
        bad = {**wire, "catalog_sha256": "wrong"}
        assert not validator.is_valid(bad)
        with pytest.raises(ValueError):
            ControlRequest.from_dict(bad)
