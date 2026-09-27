import json
from hashlib import sha256
from pathlib import Path

import pytest

from edge_delegate_lab.cli import main
from edge_delegate_lab.pilot import write_pilot
from edge_delegate_lab.review_workspace import verify_policy_document

SOURCE = Path(__file__).parents[2] / "data/fixtures/pilot-v2/source.json"


def test_policy_binding_detects_changed_and_missing_document_without_rewriting(tmp_path, capsys):
    directory = tmp_path / "pilot"
    write_pilot(SOURCE, directory)
    command = ["review-data", "--directory", str(directory), "--allow-pending"]
    assert main(command) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["policy_document"]["status"] == "verified"
    assert report["accepted_count"] == 0
    manifest_before = (directory / "manifest.json").read_bytes()
    policy = directory / "POLICY.md"
    policy.write_text(policy.read_text(encoding="utf-8") + "Changed rule.\n", encoding="utf-8")
    assert main(command) == 1
    assert "policy document fingerprint mismatch" in capsys.readouterr().err
    assert (directory / "manifest.json").read_bytes() == manifest_before
    # Even pending mode must enforce a claimed policy binding.
    policy.unlink()
    assert main(command) == 1
    assert "POLICY.md" in capsys.readouterr().err


def test_policy_newline_normalization_matches_writer(tmp_path):
    text = "# Policy\n\nDo nothing without permission.\n"
    (tmp_path / "POLICY.md").write_bytes(text.replace("\n", "\r\n").encode())
    fingerprint = sha256(text.encode()).hexdigest()
    assert verify_policy_document(tmp_path, {"policy_document_sha256": fingerprint}) == {
        "status": "verified",
        "sha256": fingerprint,
    }


@pytest.mark.parametrize("fingerprint", [None, "", "x" * 64, 10, "A" * 64])
def test_malformed_policy_binding_is_not_treated_as_absent(tmp_path, fingerprint):
    with pytest.raises(ValueError, match="invalid policy"):
        verify_policy_document(tmp_path, {"policy_document_sha256": fingerprint})


def test_legacy_workspace_without_policy_is_explicitly_unverified(tmp_path):
    assert verify_policy_document(tmp_path, {})["status"] == "not_provided"
    (tmp_path / "POLICY.md").write_text("Unbound document")
    with pytest.raises(ValueError, match="no policy document fingerprint"):
        verify_policy_document(tmp_path, {})


def test_oversized_policy_is_rejected_before_decoding(tmp_path, monkeypatch):
    monkeypatch.setattr("edge_delegate_lab.review_workspace.MAX_RECORD_BYTES", 8)
    (tmp_path / "POLICY.md").write_bytes(b"a" * 9)
    with pytest.raises(ValueError, match="size limit"):
        verify_policy_document(tmp_path, {"policy_document_sha256": "a" * 64})


def test_readable_status_does_not_imply_review_approval(tmp_path, capsys):
    directory = tmp_path / "pilot"
    write_pilot(SOURCE, directory)
    assert (
        main(["review-data", "--directory", str(directory), "--allow-pending", "--format", "text"])
        == 0
    )
    text = capsys.readouterr().out
    assert "Accepted label reviews: 0/80" in text
    assert "Training eligible: no" in text
    assert "Policy document: verified (integrity only)" in text
    assert "test: 0 cases" in text
