import hashlib
import json
import zipfile
from types import SimpleNamespace

import pytest

from edge_delegate_lab import artifact_bundle
from tests.unit.test_model_plugins import FakeModelPlugin, _manifest


@pytest.fixture
def artifact(tmp_path, monkeypatch):
    root = tmp_path / "artifact"
    (root / "adapter").mkdir(parents=True)
    (root / "adapter/model.bin").write_bytes(b"test weights")
    (root / "tokenizer.json").write_text("{}")
    (root / "private.env").write_text("must not be exported")
    _manifest(
        adapter_digest=hashlib.sha256(b"test weights").hexdigest(),
        tokenizer_digest=hashlib.sha256(b"{}").hexdigest(),
    ).write(root / "edge-delegate-artifact.json")
    monkeypatch.setattr(
        artifact_bundle,
        "available_model_plugins",
        lambda: SimpleNamespace(get=lambda _: FakeModelPlugin()),
    )
    return root


def test_export_is_allowlisted_reproducible_and_never_overwrites(artifact, tmp_path):
    first, second = tmp_path / "v1.zip", tmp_path / "v1-copy.zip"
    result = artifact_bundle.export_candidate(artifact, first)
    assert result["sha256"] == artifact_bundle.export_candidate(artifact, second)["sha256"]
    with zipfile.ZipFile(first) as archive:
        assert set(archive.namelist()) == {
            "adapter/model.bin",
            "tokenizer.json",
            "edge-delegate-artifact.json",
            "bundle-info.json",
        }
        assert (
            json.loads(archive.read("bundle-info.json"))["qualification"]
            == "not-established-by-export"
        )
    before = first.read_bytes()
    with pytest.raises(FileExistsError):
        artifact_bundle.export_candidate(artifact, first)
    assert first.read_bytes() == before


def test_tampered_artifact_is_not_exported(artifact, tmp_path):
    (artifact / "adapter/model.bin").write_bytes(b"changed")
    output = tmp_path / "bad.zip"
    with pytest.raises(ValueError, match="digest"):
        artifact_bundle.export_candidate(artifact, output)
    assert not output.exists()
