"""Profiles can be checked without importing ML or granting execution authority."""

import json
import subprocess
import sys
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from edge_delegate_lab.cli import main
from edge_delegate_lab.profiles import MAX_PROFILE_FILE_BYTES, ClientProfile

EXAMPLE = Path(__file__).parents[2] / "examples" / "local-display"


def test_profile_check_does_not_load_a_model(monkeypatch, capsys):
    def no_plugins():
        pytest.fail("profile-check must not even discover model plugins")

    monkeypatch.setattr("edge_delegate_lab.cli.available_model_plugins", no_plugins)
    assert main(["profile-check", "--profile", str(EXAMPLE), "--format", "json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["contracts_valid"] is True
    assert report["model_loaded"] is False
    assert report["execution_checked"] is False
    assert len(report["capabilities"]) == 2
    assert report["warnings"]


def test_profile_check_imports_no_ml_libraries():
    script = """
import sys
from edge_delegate_lab.cli import main
assert main(['profile-check', '--profile', sys.argv[1]]) == 0
assert not {'torch', 'transformers', 'peft', 'trl'} & set(sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(EXAMPLE)], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr


def test_duplicate_capabilities_fail_before_loading_a_model(tmp_path, monkeypatch, capsys):
    cards = json.loads((EXAMPLE / "capabilities.json").read_text())
    (tmp_path / "capabilities.json").write_text(json.dumps([cards[0], cards[0]]))

    def no_plugins():
        pytest.fail("invalid profile must be rejected before loading a model")

    monkeypatch.setattr("edge_delegate_lab.cli.available_model_plugins", no_plugins)
    assert main(["plan", "--profile", str(tmp_path), "--text", "test"]) == 1
    assert "duplicate capability" in capsys.readouterr().err


@pytest.mark.parametrize(
    "content,match",
    [
        ('[{"capability_id":"a","capability_id":"b"}]', "duplicate JSON"),
        ("[NaN]", "non-finite"),
        (" " * (MAX_PROFILE_FILE_BYTES + 1), "exceeds"),
    ],
    ids=("duplicate-keys", "nonfinite", "oversize"),
)
def test_profile_strict_loading_survives_refactor(tmp_path, content, match):
    (tmp_path / "capabilities.json").write_text(content)
    with pytest.raises(ValueError, match=match):
        ClientProfile.load(tmp_path)


def test_profile_inspection_warns_but_does_not_rewrite_stale_state():
    profile = ClientProfile.load(EXAMPLE)
    profile = replace(profile, policy=replace(profile.policy, max_state_age_seconds=60))
    original = profile.state.to_dict()
    report = profile.inspect(now=profile.state.observed_at + timedelta(seconds=61))
    assert any("stale" in warning for warning in report["warnings"])
    assert profile.state.to_dict() == original
    assert report["execution_checked"] is False


def test_profile_inspection_reports_denied_capability_and_missing_permissions():
    profile = ClientProfile.load(EXAMPLE)
    profile = replace(
        profile,
        policy=replace(
            profile.policy,
            granted_permissions=frozenset(),
            denied_capabilities=frozenset({"display.value.show"}),
        ),
    )
    card = next(
        card for card in profile.inspect()["capabilities"] if card["id"] == "display.value.show"
    )
    assert card["policy_allowed"] is False
    assert card["missing_permissions"] == ["display.write"]
