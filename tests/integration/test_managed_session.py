import io
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from edge_delegate.planner.tasks import BoundedPlanner, TaskDecision
from edge_delegate_lab import cli
from edge_delegate_lab.emulator import managed_emulator

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="managed Linux emulator")


@pytest.fixture
def directory():
    # Keep socket names below the Unix pathname limit, regardless of pytest's test name.
    with tempfile.TemporaryDirectory(prefix="ed-managed-") as root:
        yield Path(root)


@pytest.fixture
def planner_plugin(monkeypatch):
    def create(**_):
        return SimpleNamespace(
            planner=BoundedPlanner(lambda *_: TaskDecision("show_temperature")),
            last_generation=lambda **_: {"latency_ms": 1.0},
        )

    monkeypatch.setattr(
        cli,
        "available_model_plugins",
        lambda: SimpleNamespace(get=lambda _: SimpleNamespace(create_diagnostic_session=create)),
    )


def test_one_command_executes_then_replays_after_restart(directory, planner_plugin, capsys):
    args = [
        "run",
        "--emulator-dir",
        str(directory),
        "--plugin",
        "fixture",
        "--text",
        "Show temperature",
        "--request-id",
        "one",
        "--format",
        "json",
    ]
    assert cli.main(args) == 0
    captured = capsys.readouterr()
    first = json.loads(captured.out)
    assert first["result"]["status"] == "executed"
    assert first["timing"]["generation_ms"] == 1.0
    assert "READY:" in captured.err and "Loading planner" in captured.err
    assert not list(directory.glob("*.sock"))
    assert (directory / "device.sqlite").exists() and (directory / "gateway.sqlite").exists()
    assert cli.main(args) == 0
    retry = json.loads(capsys.readouterr().out)
    assert all(step["status"] == "replayed" for step in retry["result"]["execution"]["steps"])
    assert retry["timing"]["generation_ms"] is None


def test_managed_default_is_readable_and_interactive_recovery_does_not_dispatch(
    directory, planner_plugin, monkeypatch, capsys
):
    monkeypatch.setattr(sys, "stdin", io.StringIO("/help\n/reconcile missing\n/quit\n"))
    assert cli.main(["run", "--emulator-dir", str(directory), "--plugin", "fixture"]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["status"] == "not_found"
    assert "not a chat" in output.err
    assert (
        cli.main(
            [
                "run",
                "--emulator-dir",
                str(directory),
                "--plugin",
                "fixture",
                "--text",
                "Show temperature",
            ]
        )
        == 0
    )
    assert "Outcome: executed" in capsys.readouterr().out


def test_model_load_failure_stops_child_but_keeps_database(directory, monkeypatch, capsys):
    def fail(**_):
        raise ValueError("artifact unavailable")

    monkeypatch.setattr(
        cli,
        "available_model_plugins",
        lambda: SimpleNamespace(get=lambda _: SimpleNamespace(create_diagnostic_session=fail)),
    )
    assert cli.main(["run", "--emulator-dir", str(directory), "--text", "request"]) == 1
    assert "artifact unavailable" in capsys.readouterr().err
    assert not list(directory.glob("*.sock"))
    with managed_emulator(directory) as (device, _):
        assert device.snapshot().values["display.last_value"] is None


def test_one_owner_and_restricted_directory(directory):
    with managed_emulator(directory):
        with pytest.raises(ValueError, match="another managed session"):
            with managed_emulator(directory):
                pytest.fail("second emulator must not start")
    directory.chmod(0o755)
    with pytest.raises(ValueError, match="mode 700"):
        with managed_emulator(directory):
            pytest.fail("shared directory must not be used")


def test_managed_mode_rejects_ambiguous_device_or_journal_before_start(directory, capsys):
    for flags in (
        ["--socket", "/tmp/other.sock"],
        ["--journal", "other.sqlite"],
        ["--request-id", "no-text"],
    ):
        assert cli.main(["run", "--emulator-dir", str(directory), *flags]) == 1
    assert not (directory / "device.sqlite").exists()
    capsys.readouterr()


@pytest.mark.parametrize("preparation_fails", [False, True])
def test_warmup_precedes_readiness_and_failure_never_dispatches(
    directory, monkeypatch, capsys, preparation_fails
):
    events = []

    def warmup():
        assert "READY: planner loaded" not in capsys.readouterr().err
        events.append("warmup")
        if preparation_fails:
            raise ValueError("compilation unavailable")
        return {"performed": True, "device_actions": 0, "latency_ms": 20.0}

    def decide(*_):
        assert events == ["warmup"]
        assert "READY: planner loaded" in capsys.readouterr().err
        events.append("plan")
        return TaskDecision("show_temperature")

    diagnostic = SimpleNamespace(
        planner=BoundedPlanner(decide), warmup=warmup, last_generation=lambda **_: None
    )
    monkeypatch.setattr(
        cli,
        "available_model_plugins",
        lambda: SimpleNamespace(
            get=lambda _: SimpleNamespace(create_diagnostic_session=lambda **_: diagnostic)
        ),
    )
    result = cli.main(["run", "--emulator-dir", str(directory), "--text", "Show temperature"])
    assert result == (1 if preparation_fails else 0)
    assert events == (["warmup"] if preparation_fails else ["warmup", "plan"])
    assert not list(directory.glob("*.sock"))
    with managed_emulator(directory) as (device, _):
        expected = None if preparation_fails else 24.5
        assert device.snapshot().values["display.last_value"] == expected
