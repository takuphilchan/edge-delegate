"""Keep the human documentation navigable and tied to the implemented command surface."""

from __future__ import annotations

from pathlib import Path

from edge_delegate.cli import build_parser as build_edge_parser
from edge_delegate_lab.cli import build_parser as build_lab_parser
from scripts.documentation_checks import broken_links, documents
from scripts.generate_cli_reference import DESTINATION, render

REPOSITORY_ROOT = Path(__file__).parents[2]
DOCUMENTS = documents(REPOSITORY_ROOT)


def _subcommands(parser) -> set[str]:
    action = next(action for action in parser._actions if action.dest == "command")
    return set(action.choices)


def test_documentation_local_links_resolve() -> None:
    missing = broken_links(DOCUMENTS)
    assert not missing, "documentation links do not resolve:\n" + "\n".join(missing)


def test_generated_command_reference_matches_parsers() -> None:
    assert DESTINATION.read_text(encoding="utf-8") == render()


def test_runbook_names_every_implemented_command() -> None:
    runbook = (REPOSITORY_ROOT / "docs" / "development-runbook.md").read_text(encoding="utf-8")
    expected = {
        *(f"edge-delegate {name}" for name in _subcommands(build_edge_parser())),
        *(f"edge-delegate-lab {name}" for name in _subcommands(build_lab_parser())),
    }
    missing = sorted(command for command in expected if command not in runbook)
    assert not missing, f"runbook is missing implemented commands: {', '.join(missing)}"


def test_human_guides_do_not_contain_common_encoding_damage() -> None:
    damaged: list[str] = []
    for document in DOCUMENTS:
        text = document.read_text(encoding="utf-8")
        if "\ufffd" in text or "â€" in text:
            damaged.append(str(document.relative_to(REPOSITORY_ROOT)))
    assert not damaged, f"documentation contains encoding damage: {', '.join(damaged)}"
