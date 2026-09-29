"""Keep the handwritten Rust reference complete without treating prose as a schema."""

import re
from pathlib import Path

ROOT = Path(__file__).parents[2]


def enum_wire_names(source: str, name: str) -> set[str]:
    body = source.split(f"pub enum {name} {{", 1)[1].split("\n}", 1)[0]
    variants = re.findall(r"^    ([A-Z][A-Za-z0-9]+)(?:\s*\{|,)", body, re.MULTILINE)
    assert variants, f"no variants parsed for {name}"
    return {re.sub(r"(?<!^)(?=[A-Z])", "_", item).lower() for item in variants}


def test_execution_reference_covers_every_command_and_error():
    source = (ROOT / "crates/edge-protocol/src/execution.rs").read_text(encoding="utf-8")
    reference = (ROOT / "docs/reference/execution-service.md").read_text(encoding="utf-8")
    for enum_name, heading in (("Command", "Methods"), ("ErrorCode", "Errors")):
        section = reference.split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]
        documented = set(re.findall(r"^\| `([a-z_]+)` \|", section, re.MULTILINE))
        assert documented == enum_wire_names(source, enum_name)


def test_execution_reference_covers_progress_and_cancellation():
    source = (ROOT / "crates/edge-protocol/src/execution.rs").read_text(encoding="utf-8")
    reference = (ROOT / "docs/reference/execution-service.md").read_text(encoding="utf-8")
    for enum_name in ("Progress", "Cancellation"):
        for value in enum_wire_names(source, enum_name):
            assert f"`{value}`" in reference
