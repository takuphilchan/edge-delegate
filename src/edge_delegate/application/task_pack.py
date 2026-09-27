"""Candidate task-pack integrity checks. Validation is not release qualification.

No executable paths, imports, model loading or device operations are taken from a pack.
Hashes detect drift; they are not signatures or proof of trustworthy provenance.
"""

import hashlib
import json
from pathlib import Path, PurePosixPath

from edge_delegate.contracts import Policy
from edge_delegate.model_plugins import ModelArtifactManifest, available_model_plugins

MAX_JSON_BYTES = 1024 * 1024


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("non-finite JSON is forbidden")


def _load(path):
    with path.open("rb") as stream:
        payload = stream.read(MAX_JSON_BYTES + 1)
    if len(payload) > MAX_JSON_BYTES:
        raise ValueError("task-pack JSON exceeds size limit")
    value = json.loads(payload.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
    if not isinstance(value, dict):
        raise ValueError("task-pack JSON must be an object")
    return value


def _fields(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError(f"expected exactly these fields: {', '.join(sorted(fields))}")


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError("bounded nonempty identifier required")
    return value


def _bound_file(root, reference):
    _fields(reference, {"path", "sha256"})
    name = _text(reference["path"])
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
        raise ValueError("pack file must be a relative path inside the pack")
    target = (root / name).resolve(strict=True)
    if not target.is_relative_to(root) or not target.is_file():
        raise ValueError("pack file escaped its root or is not a file")
    with target.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if reference["sha256"] != actual:
        raise ValueError("task-pack file fingerprint mismatch")
    return target


def inspect_task_pack(path, *, registry=None):
    """Verify a self-contained candidate without loading weights or running a plugin."""
    path = Path(path).resolve(strict=True)
    pack = _load(path)
    _fields(
        pack,
        {
            "schema_version",
            "pack_id",
            "catalog_version",
            "decision_protocol",
            "numeric_policy",
            "plugin_id",
            "files",
            "compatibility",
        },
    )
    if (
        pack["schema_version"] != "edge-task-pack.v1"
        or pack["decision_protocol"] != "bounded-task.v1"
    ):
        raise ValueError("unsupported task-pack/decision protocol")
    if pack["numeric_policy"] != "decimal.v1":
        raise ValueError("release-one task packs must explicitly select decimal.v1")
    for field in ("pack_id", "catalog_version", "plugin_id"):
        _text(pack[field])
    _fields(
        pack["files"], {"artifact_manifest", "settings", "runtime_policy", "catalog", "evidence"}
    )
    paths = {key: _bound_file(path.parent, ref) for key, ref in pack["files"].items()}
    if len(set(paths.values())) != len(paths):
        raise ValueError("task-pack components must be distinct files")
    settings = _load(paths["settings"])
    if settings.get("numeric_policy") != pack["numeric_policy"]:
        raise ValueError("inference settings numeric policy differs from task pack")
    policy = Policy.from_dict(_load(paths["runtime_policy"]))
    if policy.external_allowed:
        raise ValueError("release-one task pack must disable external delegation")
    catalog = _load(paths["catalog"])
    _fields(catalog, {"version", "tasks", "parameter_semantics"})
    if catalog["version"] != pack["catalog_version"] or not isinstance(catalog["tasks"], list):
        raise ValueError("catalog metadata does not match task pack")
    if (
        catalog["version"] != "local-display.v1"
        or set(catalog["tasks"])
        != {"read_temperature", "display_number", "show_temperature", "clarify", "deny"}
        or len(catalog["tasks"]) != 5
    ):
        raise ValueError("release-one pack requires the reference catalog")
    if catalog["parameter_semantics"] != "decimal.v1":
        raise ValueError("catalog parameter semantics do not match task pack")
    compatibility = pack["compatibility"]
    _fields(compatibility, {"adapter_id", "adapter_api", "firmware_id", "hardware_id"})
    for value in compatibility.values():
        _text(value)
    if compatibility["adapter_api"] != "edge-delegate-gateway.v2":
        raise ValueError("deadline-aware adapter contract required")
    artifact = ModelArtifactManifest.from_dict(_load(paths["artifact_manifest"]))
    if artifact.plugin_id != pack["plugin_id"]:
        raise ValueError("artifact plugin differs from task pack")
    registry = available_model_plugins() if registry is None else registry
    artifact.verify_files(
        paths["artifact_manifest"].parent, descriptor=registry.get(pack["plugin_id"]).descriptor
    )
    evidence = _load(paths["evidence"])
    # Candidate evidence is never a readiness/authorization grant. Promotion is a
    # separate future verifier, not a boolean supplied by an untrusted manifest.
    if evidence.get("schema_version") != "edge-gateway-qualification.v2":
        raise ValueError("task pack requires versioned qualification evidence, even if failed")
    return {
        "schema_version": "edge-task-pack-inspection.v1",
        "pack_id": pack["pack_id"],
        "pack_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "integrity_verified": True,
        "numeric_policy": pack["numeric_policy"],
        "compatibility": compatibility,
        "qualified": False,
        "limitations": [
            "Candidate integrity only; no readiness or release authorization.",
            "Installed plugins are trusted code, not sandboxed extensions.",
        ],
    }
