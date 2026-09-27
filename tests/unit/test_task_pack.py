import hashlib
import json

import pytest

from edge_delegate.application.task_pack import inspect_task_pack
from edge_delegate.simulator.examples import local_display
from tests.unit.test_task_plugins import classifier_artifact  # noqa: F401


@pytest.fixture
def pack(classifier_artifact):  # noqa: F811
    root = classifier_artifact
    parts = {
        "settings": {"numeric_policy": "decimal.v1"},
        "runtime_policy": local_display()[1].to_dict(),
        "catalog": {
            "version": "local-display.v1",
            "parameter_semantics": "decimal.v1",
            "tasks": ["read_temperature", "display_number", "show_temperature", "clarify", "deny"],
        },
        "evidence": {"schema_version": "edge-gateway-qualification.v2", "qualified": False},
    }
    files = {}
    for name, value in parts.items():
        path = root / f"{name}.json"
        path.write_text(json.dumps(value))
        files[name] = {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    artifact = root / "edge-delegate-artifact.json"
    files["artifact_manifest"] = {
        "path": artifact.name,
        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
    }
    value = {
        "schema_version": "edge-task-pack.v1",
        "pack_id": "fixture-only.v1",
        "catalog_version": "local-display.v1",
        "decision_protocol": "bounded-task.v1",
        "numeric_policy": "decimal.v1",
        "plugin_id": "task-classifier",
        "files": files,
        "compatibility": {
            "adapter_id": "unix",
            "adapter_api": "edge-delegate-gateway.v2",
            "firmware_id": "software-emulator",
            "hardware_id": "fixture-only",
        },
    }
    target = root / "pack.json"
    target.write_text(json.dumps(value))
    return target, value


def test_pack_verifies_without_loading_or_qualifying(pack):
    report = inspect_task_pack(pack[0])
    assert report["integrity_verified"]
    assert not report["qualified"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.pop("numeric_policy"),
        lambda p: p.update(numeric_policy="legacy.v1"),
        lambda p: p["files"]["settings"].update(sha256="0" * 64),
        lambda p: p["files"]["settings"].update(path="../settings.json"),
        lambda p: p["compatibility"].update(adapter_api="legacy"),
        lambda p: p.update(plugin_id="functiongemma-tasks"),
        lambda p: p.update(python="arbitrary.py"),
    ],
)
def test_pack_rejects_drift_and_implicit_or_executable_configuration(pack, mutation):
    path, value = pack
    mutation(value)
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        inspect_task_pack(path)


def test_pack_settings_policy_must_agree_even_with_valid_hash(pack):
    path, value = pack
    settings = path.parent / "settings.json"
    settings.write_text("{}")
    value["files"]["settings"]["sha256"] = hashlib.sha256(settings.read_bytes()).hexdigest()
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="numeric policy"):
        inspect_task_pack(path)
