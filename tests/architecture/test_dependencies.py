"""Enforce dependency direction that keeps the edge runtime deployable."""

from __future__ import annotations

import ast
from pathlib import Path

RUNTIME_ROOT = Path(__file__).parents[2] / "src" / "edge_delegate" / "runtime"
FORBIDDEN_RUNTIME_PACKAGES = {
    "edge_delegate.connectors",
    "edge_delegate.data",
    "edge_delegate.evaluation",
    "edge_delegate.model_plugins",
    "edge_delegate.planner.functiongemma",
    "edge_delegate.simulator",
    "edge_delegate_lab",
}


def test_runtime_does_not_import_adapters_or_lab_packages() -> None:
    violations: list[str] = []
    for path in sorted(RUNTIME_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported: list[str] = []
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = [node.module]
            for name in imported:
                if any(
                    name == forbidden or name.startswith(f"{forbidden}.")
                    for forbidden in FORBIDDEN_RUNTIME_PACKAGES
                ):
                    violations.append(f"{path.name}:{node.lineno} imports {name}")
    assert not violations, "runtime dependency violations:\n" + "\n".join(violations)


def test_public_application_never_imports_the_lab_or_a_model_family():
    root = RUNTIME_ROOT.parent / "application"
    forbidden = (
        "edge_delegate_lab",
        "torch",
        "transformers",
        "peft",
        "edge_delegate.model_plugins.functiongemma",
        "edge_delegate.model_plugins.task_classifier",
    )
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else ([node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            )
            assert not any(
                name == prefix or name.startswith(prefix + ".")
                for name in names
                for prefix in forbidden
            ), path
