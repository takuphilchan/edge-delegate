"""Guard the additive migration and independently verify wire hash fixtures."""

import hashlib
import json
import tomllib
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).parents[2]


def test_rust_dependency_direction():
    workspace = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))
    allowed = {
        "edge-contracts": set(),
        "edge-core": {"edge-contracts"},
        "edge-cli": {"edge-contracts", "edge-core", "edge-client"},
        "edge-protocol": {"edge-contracts"},
        "edge-storage": {"edge-contracts", "edge-core"},
        "edge-simulator": {"edge-contracts", "edge-core", "edge-protocol"},
        "edge-host": {"edge-contracts", "edge-core", "edge-protocol", "edge-storage"},
        "edge-client": {"edge-contracts", "edge-protocol"},
    }
    names = set(allowed)
    for member in workspace["workspace"]["members"]:
        manifest = tomllib.loads((ROOT / member / "Cargo.toml").read_text(encoding="utf-8"))
        name = manifest["package"]["name"]
        dependencies = set(manifest.get("dependencies", {}))
        for target in manifest.get("target", {}).values():
            dependencies.update(target.get("dependencies", {}))
        assert dependencies & names <= allowed[name], name
        assert not dependencies & {"pyo3", "tch", "reqwest", "tokio"}, name
        assert manifest["package"]["publish"] == {"workspace": True}


def test_rust_golden_hashes_match_python():
    root = ROOT / "conformance" / "contracts" / "preview-v2"
    request = json.loads((root / "request.json").read_text(encoding="utf-8"))
    context = json.loads((root / "context.json").read_text(encoding="utf-8"))
    golden = json.loads((root / "canonical.json").read_text(encoding="utf-8"))

    def canonical(value):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    assert canonical(request) == golden["canonical_utf8"]
    assert hashlib.sha256(canonical(request).encode()).hexdigest() == golden["sha256"]
    endpoint = context["endpoints"][0]
    assert hashlib.sha256(canonical(endpoint["actions"]).encode()).hexdigest() == (
        endpoint["binding"]["catalog_sha256"]
    )


def test_existing_python_entrypoints_are_preserved():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert metadata["project"]["scripts"] == {
        "edge-delegate": "edge_delegate.cli:main",
        "edge-delegate-lab": "edge_delegate_lab.cli:main",
        "edge-delegate-device": "edge_delegate.simulator.server:main",
    }


def test_v2_schema_accepts_fixture_and_rejects_legacy_and_extra_fields():
    schema = json.loads(
        (ROOT / "schemas/v2/control-request.v2.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    request = json.loads(
        (ROOT / "conformance/contracts/preview-v2/request.json").read_text(encoding="utf-8")
    )
    validator.validate(request)
    for change in (
        {"schema_version": "edge-control-request.v1"},
        {"budget_ms": 0},
        {"budget_ms": 5001},
        {"execute": True},
    ):
        assert list(validator.iter_errors({**request, **change}))


def test_pure_rust_layers_have_no_io_imports():
    for crate in ("edge-contracts", "edge-core"):
        for path in (ROOT / "crates" / crate / "src").glob("*.rs"):
            text = path.read_text(encoding="utf-8")
            for forbidden in ("std::fs", "std::net", "std::process", "edge_delegate_lab"):
                assert forbidden not in text, (path, forbidden)
