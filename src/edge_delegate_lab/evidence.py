"""Bind measured results to installed source, artifact bytes, and inference settings."""

import hashlib
import json
from pathlib import Path

import edge_delegate
from edge_delegate import __version__


def model_identity(plugin_id, artifact, settings=None):
    if artifact is None:
        return None
    root = Path(artifact)
    digest = hashlib.sha256(
        json.dumps(
            {"plugin": plugin_id, "package_version": __version__, "settings": settings or {}},
            sort_keys=True,
        ).encode()
    )
    for package, directory in (
        ("edge_delegate", Path(edge_delegate.__file__).parent),
        ("edge_delegate_lab", Path(__file__).parent),
    ):
        for source in sorted(directory.rglob("*.py")):
            digest.update(f"{package}/{source.relative_to(directory).as_posix()}".encode())
            digest.update(source.read_bytes())
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(root)).encode())
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
    return digest.hexdigest()
