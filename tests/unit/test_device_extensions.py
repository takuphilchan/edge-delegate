import importlib.util
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from edge_delegate.adapters import registry
from edge_delegate.contracts import PlanningRequest, Policy
from edge_delegate.runtime.ports import CapabilityExecutionError
from edge_delegate_lab.cli import main
from edge_delegate_lab.gateway import GatewaySession


@pytest.fixture
def counter():
    path = Path(__file__).parents[2] / "examples/plugins/counter/edge_counter.py"
    spec = importlib.util.spec_from_file_location("test_counter_extension", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_installed_device_selection_is_explicit_and_checks_contract(monkeypatch, counter, tmp_path):
    entry = SimpleNamespace(name="counter-demo", load=lambda: counter.device_adapter)
    monkeypatch.setattr(registry, "entry_points", lambda **_: [entry])
    device = registry.load_device_adapter(
        "counter-demo", settings={"database": str(tmp_path / "counter")}
    )
    assert device.device_id.startswith("counter-")
    with pytest.raises(ValueError, match="not installed"):
        registry.load_device_adapter("arbitrary.module:run", settings={})
    monkeypatch.setattr(registry, "entry_points", lambda **_: [entry, entry])
    with pytest.raises(ValueError, match="duplicate"):
        registry.load_device_adapter("counter-demo", settings={})
    monkeypatch.setattr(
        registry,
        "entry_points",
        lambda **_: [SimpleNamespace(name="bad", load=lambda: lambda **_: object())],
    )
    with pytest.raises(ValueError, match="contracts"):
        registry.load_device_adapter("bad", settings={})


def test_independent_catalog_and_adapter_execute_replay_and_obey_policy(counter, tmp_path):
    path = tmp_path / "device"
    device = counter.Counter(str(path))
    policy = Policy("test", granted_permissions=frozenset({"counter.write"}))
    planner = counter.plugin.create_planner(artifact_path=None, settings={})
    session = GatewaySession(planner, device, policy, journal_path=tmp_path / "journal")
    assert planner.catalog.version == "counter-demo.v1"
    request = PlanningRequest("increment", "increment counter")
    assert session.handle(request)["result"]["execution"]["final_output"] == 1
    restarted = counter.Counter(str(path))
    assert restarted.device_id == device.device_id
    session = GatewaySession(planner, restarted, policy, journal_path=tmp_path / "journal")
    assert session.handle(request)["result"]["execution"]["steps"][0]["status"] == "replayed"
    assert restarted.snapshot().values["counter.value"] == 1
    assert session.handle(PlanningRequest("other", "open door"))["result"]["status"] == "denied"
    denied = GatewaySession(
        planner, restarted, Policy("denied"), journal_path=tmp_path / "other-journal"
    )
    assert (
        denied.handle(PlanningRequest("no-permission", "increment counter"))["result"]["status"]
        == "denied"
    )
    assert restarted.snapshot().values["counter.value"] == 1


def test_counter_fence_and_expired_deadline_do_not_increment(counter, tmp_path):
    device = counter.Counter(str(tmp_path / "device"))
    assert device.cancel_operation("fenced", deadline=time.monotonic() + 1).status == "failed"
    with pytest.raises(CapabilityExecutionError):
        device.invoke_bounded(
            "counter.increment", {}, operation_id="fenced", deadline=time.monotonic() + 1
        )
    with pytest.raises(TimeoutError):
        device.invoke_bounded(
            "counter.increment", {}, operation_id="expired", deadline=time.monotonic() - 1
        )
    assert device.snapshot().values["counter.value"] == 0


def test_example_generation_requires_new_directory(tmp_path):
    output = tmp_path / "profile"
    assert main(["init-example", "--output", str(output)]) == 0
    assert main(["profile-check", "--profile", str(output)]) == 0
    before = (output / "state.json").read_bytes()
    assert main(["init-example", "--output", str(output)]) == 1
    assert (output / "state.json").read_bytes() == before
