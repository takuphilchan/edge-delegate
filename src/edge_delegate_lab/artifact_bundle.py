"""Export only manifest-listed candidate files; never publish or qualify them."""

import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path

from edge_delegate.model_plugins import ModelArtifactManifest, available_model_plugins


def export_candidate(artifact, output):
    root, output = Path(artifact).resolve(), Path(output)
    manifest = ModelArtifactManifest.read(root / "edge-delegate-artifact.json")
    descriptor = available_model_plugins().get(manifest.plugin_id).descriptor
    manifest.verify_files(root, descriptor=descriptor)
    files = dict(manifest.adapter_files)
    for name, digest in manifest.tokenizer_files.items():
        if name in files and files[name] != digest:
            raise ValueError("conflicting artifact hashes")
        files[name] = digest
    if set(files) & {"edge-delegate-artifact.json", "bundle-info.json"}:
        raise ValueError("artifact files use reserved bundle names")
    metadata = {
        "schema_version": "edge-candidate-bundle.v1",
        "artifact_id": manifest.artifact_id,
        "plugin_id": manifest.plugin_id,
        "qualification": "not-established-by-export",
        "base_model_included": False,
        "license_notice": "Project MIT license does not grant model/tokenizer redistribution rights. Review upstream terms before sharing.",
    }
    # Same-directory staging plus an exclusive link never overwrites an existing bundle.
    with tempfile.TemporaryDirectory(prefix=".edge-bundle-", dir=output.parent) as stage:
        staged = Path(stage) / "candidate.zip"
        with zipfile.ZipFile(staged, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, value in {
                "edge-delegate-artifact.json": manifest.to_dict(),
                "bundle-info.json": metadata,
            }.items():
                info = zipfile.ZipInfo(name)
                info.external_attr = 0o100600 << 16
                archive.writestr(info, json.dumps(value, indent=2, sort_keys=True) + "\n")
            for name, expected in sorted(files.items()):
                path = (root / name).resolve()
                if not path.is_relative_to(root):
                    raise ValueError("artifact file escaped its root")
                info = zipfile.ZipInfo(name)
                info.external_attr = 0o100600 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                digest = hashlib.sha256()
                with path.open("rb") as source, archive.open(info, "w", force_zip64=True) as dest:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(chunk)
                        dest.write(chunk)
                if digest.hexdigest() != expected:
                    raise ValueError("artifact changed during export")
        os.chmod(staged, 0o600)
        with staged.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        os.link(staged, output)
    return {**metadata, "path": str(output), "sha256": digest, "file_count": len(files) + 2}
