"""Repository documentation checks; stdlib only, no model or physical-device access."""

from __future__ import annotations

import html
import json
import re
import shlex
import sqlite3
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlsplit

LINK = re.compile(r"(?<!!)\[[^]\n]+\]\((<[^>]+>|[^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE = re.compile(r"^ {0,3}(\x60{3,}|~{3,})(.*)$")
TUTORIAL_STEPS = ("preview", "execute", "power", "ambiguous", "replay")


def prose_lines(text: str):
    """Yield non-fenced Markdown lines (both backtick and tilde fences)."""
    fence = None
    for line in text.splitlines():
        match = FENCE.match(line)
        if fence:
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence):
                if not match[2].strip():
                    fence = None
            continue
        if match:
            fence = match[1]
            continue
        yield line


def heading_anchors(text: str) -> set[str]:
    """GitHub-style slugs for our ATX/inline-Markdown heading convention."""
    used: set[str] = set()
    for line in prose_lines(text):
        match = re.match(r"^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if not match:
            continue
        title = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", match[1])
        title = html.unescape(re.sub(r"<[^>]*>", "", title)).lower()
        title = title.replace("\x60", "").replace("*", "")
        slug = "".join(
            char for char in title if char in "_- " or unicodedata.category(char)[0] in "LN"
        ).replace(" ", "-")
        anchor, suffix = slug, 0
        while anchor in used:
            suffix += 1
            anchor = f"{slug}-{suffix}"
        used.add(anchor)
    return used


def documents(root: Path) -> tuple[Path, ...]:
    return (
        root / "README.md",
        *sorted((root / "docs").rglob("*.md")),
        *sorted((root / "specs").rglob("*.md")),
        *sorted((root / "data" / "fixtures" / "pilot-v2").glob("*.md")),
    )


def broken_links(paths) -> list[str]:
    missing = []
    anchor_cache = {}
    for document in paths:
        source = "\n".join(prose_lines(document.read_text(encoding="utf-8")))
        for raw in LINK.findall(source):
            target = raw.strip("<>")
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc:
                continue
            destination = (
                (document.parent / unquote(parsed.path)).resolve()
                if parsed.path
                else document.resolve()
            )
            if not destination.exists():
                missing.append(f"{document}: missing file {target}")
            elif parsed.fragment and destination.suffix.lower() == ".md":
                if destination not in anchor_cache:
                    anchor_cache[destination] = heading_anchors(
                        destination.read_text(encoding="utf-8")
                    )
                if unquote(parsed.fragment) not in anchor_cache[destination]:
                    missing.append(f"{document}: missing heading {target}")
    return missing


def marked_block(text: str, marker: str, language: str) -> str:
    pattern = re.compile(
        rf"<!-- {re.escape(marker)} -->\s*\n(?P<fence>\x60{{3,}}|~{{3,}}){language}\n"
        rf"(?P<body>.*?)\n(?P=fence)\s*(?:\n|$)",
        re.DOTALL,
    )
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {marker} {language} block")
    return matches[0]["body"]


def tutorial_commands(document: Path, directory: Path):
    text = document.read_text(encoding="utf-8")
    markers = re.findall(r"<!-- tutorial: ([a-z_-]+) -->", text)
    if tuple(markers) != TUTORIAL_STEPS:
        raise ValueError("tutorial markers changed; update assertions deliberately")
    for name in TUTORIAL_STEPS:
        block = marked_block(text, f"tutorial: {name}", "bash")
        tokens = shlex.split(block.replace("\\\n", " "))
        if tokens[:2] != ["edge-delegate", "control-demo"]:
            raise ValueError("tutorial runner accepts only edge-delegate control-demo")
        if tokens.count("$EDGE_LIGHT_DIR") != 1:
            raise ValueError("tutorial must use exactly one state-directory placeholder")
        if tokens.count("--directory") != 1 or tokens[
            tokens.index("--directory") + 1 : tokens.index("--directory") + 2
        ] != ["$EDGE_LIGHT_DIR"]:
            raise ValueError("tutorial directory must be the isolated state placeholder")
        if any("$" in token and token != "$EDGE_LIGHT_DIR" for token in tokens):
            raise ValueError("unexpected shell expansion")
        if any(token in {";", "&&", "||", "|", ">", "<", "&"} for token in tokens):
            raise ValueError("shell operators are not supported")
        yield name, [str(directory) if token == "$EDGE_LIGHT_DIR" else token for token in tokens]


def _database_rows(directory: Path):
    """Observe deduplication records as well as state; no implementation imports."""

    def rows(filename, table, columns):
        with sqlite3.connect(f"{(directory / filename).as_uri()}?mode=ro", uri=True) as db:
            return db.execute(f"SELECT {columns} FROM {table} ORDER BY 1").fetchall()

    return {
        "workbench": rows("workbench.sqlite", "receipts", "*"),
        "inspection": rows("inspection.sqlite", "receipts", "*"),
        "requests": rows("gateway.sqlite", "requests", "*"),
        "operations": rows("gateway.sqlite", "operations", "*"),
    }


def check_tutorial(document: Path, directory: Path, run) -> None:
    """Execute the actual documented commands through a caller-supplied installed CLI."""
    if directory.exists():
        raise ValueError("tutorial acceptance requires a fresh directory")
    previous = None
    for name, command in tutorial_commands(document, directory):
        result = json.loads(run(*command, expected=2 if name == "ambiguous" else 0))
        assert result["software_only"] is True and result["trained_model"] is False
        assert result["mode"] == ("preview" if name == "preview" else "execute")
        expected_state = {
            "workbench light": {"light.power": False, "light.brightness_percent": 100},
            "inspection light": {
                "light.power": name in {"power", "ambiguous", "replay"},
                "light.brightness_percent": 100 if name == "preview" else 40,
            },
        }
        assert result["state"] == expected_state, f"{name}: incorrect effects"
        response = result["response"]
        if name == "preview":
            assert response["schema_version"] == "edge-control-preview.v1"
            assert response["gateway"]["execution_attempted"] is False
            assert response["gateway"]["validation"]["issues"] == []
        elif name == "ambiguous":
            assert response["status"] == "clarification_required"
            assert response["execution_attempted"] is False
            assert len(response["choices"]) == 2
        else:
            assert response["schema_version"] == "edge-control-result.v1"
            execution = response["gateway"]["result"]
            assert execution["status"] == "executed"
            steps = execution["execution"]["steps"]
            assert len(steps) == 1
            assert steps[0]["status"] == ("replayed" if name == "replay" else "succeeded")
            assert steps[0]["capability_id"] == (
                "light.power.set" if name == "power" else "light.brightness.set"
            )
            assert steps[0]["result"] == (True if name == "power" else 40)
        records = _database_rows(directory)
        assert not records["workbench"], f"{name}: wrong device invoked"
        count = {"preview": 0, "execute": 1, "power": 2, "ambiguous": 2, "replay": 2}[name]
        assert len(records["inspection"]) == count
        assert len(records["requests"]) == count
        assert len(records["operations"]) == count
        if name in {"ambiguous", "replay"}:
            assert records == previous, f"{name}: durable invocation/request records changed"
        previous = records
