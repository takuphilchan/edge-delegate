"""Bounded JSON dataset loading shared by trainers and command adapters."""

import json
from pathlib import Path

MAX_RECORD_BYTES = 1024 * 1024


def reject_constant(value: str):
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def load_jsonl(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    with path.open("rb") as handle:
        line_number = 0
        while line := handle.readline(MAX_RECORD_BYTES + 1):
            line_number += 1
            if len(line) > MAX_RECORD_BYTES:
                raise ValueError(f"JSONL line {line_number} exceeds the size limit")
            if not line.strip():
                continue
            value = json.loads(
                line.decode("utf-8"),
                object_pairs_hook=without_duplicates,
                parse_constant=reject_constant,
            )
            if not isinstance(value, dict):
                raise ValueError(f"JSONL line {line_number} must be an object")
            records.append(value)
    return records
