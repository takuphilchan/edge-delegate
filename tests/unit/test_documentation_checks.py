"""Check documentation checks themselves, and execute the actual tutorial examples."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.documentation_checks import (
    broken_links,
    check_tutorial,
    documents,
    heading_anchors,
    marked_block,
    tutorial_commands,
)

ROOT = Path(__file__).resolve().parents[2]


def test_heading_slugs_duplicate_inline_and_fenced():
    text = "# Same\n## Same\n## Same-1\n## **API**: \x60start()\x60\n## Café & tea\n"
    text += "~~~python\n# Not a heading\n~~~\n\x60\x60\x60text\n# Also hidden\n\x60\x60\x60\n"
    assert heading_anchors(text) == {"same", "same-1", "same-1-1", "api-start", "café--tea"}


def test_links_check_same_file_encoded_paths_and_missing_anchors(tmp_path):
    target = tmp_path / "other page.md"
    target.write_text("# Other\n## Child\n", encoding="utf-8")
    source = tmp_path / "source.md"
    source.write_text(
        "# Here\n[local](#here)\n[other](other%20page.md#child)\n"
        "[missing heading](other%20page.md#absent)\n[missing file](absent.md)\n"
        "[missing self](#absent)\n[web](https://example.org/missing)\n"
        "~~~text\n[fenced](missing-too.md)\n~~~\n",
        encoding="utf-8",
    )
    failures = broken_links([source, target])
    assert len(failures) == 3
    assert sum("missing heading" in failure for failure in failures) == 2
    assert any("missing file absent.md" in failure for failure in failures)


def test_nested_documents_are_discovered(tmp_path):
    nested = tmp_path / "docs" / "reference" / "nested.md"
    nested.parent.mkdir(parents=True)
    nested.write_text("# Nested\n", encoding="utf-8")
    spec = tmp_path / "specs" / "deep" / "contract.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# Contract\n", encoding="utf-8")
    assert nested in documents(tmp_path) and spec in documents(tmp_path)


def test_marked_block_requires_exactly_one():
    block = "<!-- example -->\n~~~python\nprint(1)\n~~~\n"
    assert marked_block(block, "example", "python") == "print(1)"
    with pytest.raises(ValueError, match="exactly one"):
        marked_block(block + block, "example", "python")
    with pytest.raises(ValueError, match="exactly one"):
        marked_block("", "example", "python")


@pytest.mark.parametrize("replacement", ["other-cli control-demo", "edge-delegate demo"])
def test_tutorial_rejects_other_executables(tmp_path, replacement):
    source = (ROOT / "docs" / "try-it.md").read_text(encoding="utf-8")
    path = tmp_path / "modified.md"
    path.write_text(source.replace("edge-delegate control-demo", replacement), encoding="utf-8")
    with pytest.raises(ValueError, match="accepts only"):
        list(tutorial_commands(path, tmp_path / "state"))


def test_tutorial_rejects_unknown_shell_expansion(tmp_path):
    source = (ROOT / "docs" / "try-it.md").read_text(encoding="utf-8")
    path = tmp_path / "modified.md"
    path.write_text(source.replace("tutorial-brightness", "$UNEXPECTED"), encoding="utf-8")
    with pytest.raises(ValueError, match="shell expansion"):
        list(tutorial_commands(path, tmp_path / "state"))


def _run_cli(tmp_path, *, mutate=None):
    def run(command, *arguments, expected=0):
        assert command == "edge-delegate"
        result = subprocess.run(
            [sys.executable, "-m", "edge_delegate.cli", *arguments],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == expected, result.stdout + result.stderr
        return mutate(result.stdout) if mutate else result.stdout

    return run


def test_tutorial_rejects_directory_outside_isolated_state(tmp_path):
    source = (ROOT / "docs" / "try-it.md").read_text(encoding="utf-8")
    path = tmp_path / "modified.md"
    source = source.replace('--directory "$EDGE_LIGHT_DIR"', "--directory /unrelated")
    source = source.replace("tutorial-brightness", "$EDGE_LIGHT_DIR")
    path.write_text(source, encoding="utf-8")
    with pytest.raises(ValueError, match="isolated state placeholder"):
        list(tutorial_commands(path, tmp_path / "state"))


def test_documented_tutorial_effects_nonactions_and_replay(tmp_path):
    check_tutorial(ROOT / "docs" / "try-it.md", tmp_path / "lights", _run_cli(tmp_path))


def test_tutorial_assertions_reject_wrong_effect_despite_success(tmp_path):
    def mutate(stdout):
        output = json.loads(stdout)
        output["state"]["inspection light"]["light.brightness_percent"] = 99
        return json.dumps(output)

    with pytest.raises(AssertionError, match="incorrect effects"):
        check_tutorial(
            ROOT / "docs" / "try-it.md",
            tmp_path / "lights",
            _run_cli(tmp_path, mutate=mutate),
        )


def test_tutorial_requires_fresh_state(tmp_path):
    with pytest.raises(ValueError, match="fresh"):
        check_tutorial(ROOT / "docs" / "try-it.md", tmp_path, None)


def test_documented_sdk_example(tmp_path):
    source = (ROOT / "docs" / "reference" / "control-sdk.md").read_text(encoding="utf-8")
    example = marked_block(source, "sdk-example", "python")
    result = subprocess.run(
        [sys.executable, "-c", example], cwd=tmp_path, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stdout + result.stderr
