import copy
import json
import runpy
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from edge_delegate.planner.tasks import BoundedPlanner, TaskDecision
from edge_delegate.runtime.ports import DeadlineGateway
from edge_delegate_lab.gateway import GatewaySession
from edge_delegate_lab.latency_profile import (
    TracedDevice,
    check_effects,
    iter_samples,
    storage_info,
    summarize,
)
from tests.unit.test_gateway_recovery import Device


def session_fixture(tmp_path):
    decisions = {
        "Read the temperature.": TaskDecision("read_temperature"),
        "Show the temperature.": TaskDecision("show_temperature"),
        "Display 12.": TaskDecision("display_number", {"value": 12}),
        "Display -3.5.": TaskDecision("display_number", {"value": -3.5}),
        "Show it.": TaskDecision("clarify"),
        "Open the door.": TaskDecision("deny"),
    }
    device = Device()
    device.capability_cards = device.world.capability_cards
    device.transport_ms = {}
    traced = TracedDevice(device)
    session = GatewaySession(
        BoundedPlanner(lambda request, _: decisions[request.text]),
        traced,
        device.policy,
        journal_path=tmp_path / "journal",
    )
    return session, traced


def test_automatic_profile_checks_effects_uses_unique_ids_and_pauses(tmp_path):
    session, traced = session_fixture(tmp_path)
    assert isinstance(traced, DeadlineGateway)
    pauses = []
    samples = list(iter_samples(session, traced, count=6, idle_seconds=3, sleep=pauses.append))
    assert len(samples) == 18
    assert pauses == [3] * 6
    assert len({sample["request_id"] for sample in samples}) == 18
    assert all(sample["passed"] for sample in samples)
    assert all(row["failed_checks"] == 0 for row in summarize(samples).values())
    assert samples[0]["after"]["display.last_value"] is None
    assert samples[1]["after"]["display.last_value"] == 24.5
    assert samples[3]["after"]["display.last_value"] == -3.5
    assert samples[4]["invocations"] == samples[5]["invocations"] == []
    # Trace lists retained in earlier samples must not be cleared by later requests.
    assert len(samples[1]["invocations"]) == 2


def test_status_success_cannot_hide_wrong_effect_or_extra_action():
    state = {"environment.temperature_c": 24.5, "display.last_value": None}
    result = {"status": "executed", "execution": {"status": "succeeded", "final_output": True}}
    checks = check_effects(2, result, state, state, [])
    assert checks["status"]
    assert not checks["final_state"]
    assert not checks["invocations_and_returns"]
    denied = {"status": "denied", "execution": None}
    assert not check_effects(5, denied, state, state, [{"unexpected": True}])[
        "invocations_and_returns"
    ]


def test_failed_requests_remain_in_latency_summary(tmp_path):
    session, traced = session_fixture(tmp_path)
    samples = list(iter_samples(session, traced, count=6, idle_seconds=0))
    samples = copy.deepcopy(samples)
    samples[0].update(status="planner_failed", total_ms=5000, passed=False)
    summary = summarize(samples)["burst"]
    assert summary["count"] == 6
    assert summary["p95_ms"] == 5000
    assert summary["status_mismatches"] == summary["failed_checks"] == 1


def test_missing_filesystem_probe_is_explicit(monkeypatch, tmp_path):
    def unavailable(*args, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", unavailable)
    assert storage_info(tmp_path) == {"unavailable": "FileNotFoundError"}


@pytest.mark.parametrize("count,idle", [(5, 0), (201, 0), (6, -1), (6, 61)])
def test_invalid_profile_limits_fail_before_execution(count, idle):
    with pytest.raises(ValueError):
        list(iter_samples(None, None, count=count, idle_seconds=idle))


@pytest.mark.parametrize("failure", [None, "wrong_effect", "interrupted"])
def test_script_checkpoints_returns_failure_and_preserves_existing_reports(
    tmp_path, monkeypatch, failure
):
    main = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/profile_latency.py"))[
        "main"
    ]
    namespace = main.__globals__
    settings = tmp_path / "settings.json"
    settings.write_text("{}")
    output = tmp_path / "report"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "profile_latency.py",
            "--artifact",
            "fixture",
            "--settings",
            str(settings),
            "--output",
            str(output),
            "--state-root",
            str(tmp_path / "state"),
            "--count",
            "6",
        ],
    )
    model = SimpleNamespace(model_info={}, planner=object())
    plugin = SimpleNamespace(create_diagnostic_session=lambda **kwargs: model)
    monkeypatch.setitem(
        namespace, "available_model_plugins", lambda: SimpleNamespace(get=lambda _: plugin)
    )
    monkeypatch.setitem(namespace, "model_identity", lambda *args: "fixture")
    monkeypatch.setitem(namespace, "detect_hardware_inventory", lambda: None)
    monkeypatch.setitem(namespace, "asdict", lambda _: {})
    monkeypatch.setitem(namespace, "storage_info", lambda _: {"fixture": True})
    monkeypatch.setitem(namespace, "GatewaySession", lambda *args, **kwargs: object())

    @contextmanager
    def emulator(directory):
        yield object(), Path(directory) / "journal"

    monkeypatch.setitem(namespace, "managed_emulator", emulator)

    def samples(*args, **kwargs):
        yield {
            "phase": "burst",
            "index": 0,
            "total_ms": 10,
            "status": "executed",
            "expected_status": "executed",
            "passed": failure != "wrong_effect",
        }
        if failure == "interrupted":
            raise KeyboardInterrupt()

    monkeypatch.setitem(namespace, "iter_samples", samples)
    if failure == "interrupted":
        with pytest.raises(KeyboardInterrupt):
            main()
    else:
        assert main() == (1 if failure == "wrong_effect" else 0)
    report_path = output / "report.json"
    report = json.loads(report_path.read_text())
    assert len(report["samples"]) == 1
    assert report["complete"] is (failure != "interrupted")
    assert report["qualified"] is False
    if failure == "interrupted":
        assert report["error_type"] == "KeyboardInterrupt"
    original = report_path.read_bytes()
    with pytest.raises(FileExistsError):
        main()
    assert report_path.read_bytes() == original
