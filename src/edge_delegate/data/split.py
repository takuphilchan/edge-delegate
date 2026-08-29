"""Leakage-resistant deterministic dataset splitting."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable


def _metadata(record: dict[str, object]) -> dict[str, object]:
    value = record.get("metadata")
    if not isinstance(value, dict):
        raise ValueError("dataset record metadata must be an object")
    return value


def group_key(record: dict[str, object]) -> tuple[str, str, str]:
    metadata = _metadata(record)
    return tuple(
        str(metadata.get(name, ""))
        for name in ("template_id", "paraphrase_cluster", "device_family")
    )


def split_records(
    records: Iterable[dict[str, object]],
    *,
    seed: int = 17,
) -> dict[str, list[dict[str, object]]]:
    """Keep related paraphrases together and isolate safety cases."""

    result: dict[str, list[dict[str, object]]] = {
        "train": [],
        "validation": [],
        "test": [],
        "safety": [],
    }
    grouped: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    for record in records:
        tags = _metadata(record).get("tags", [])
        if isinstance(tags, list) and "safety" in tags:
            result["safety"].append(record)
        else:
            grouped[group_key(record)].append(record)

    ordered_groups = sorted(
        grouped.items(),
        key=lambda item: hashlib.sha256(f"{seed}:{'|'.join(item[0])}".encode()).hexdigest(),
    )
    count = len(ordered_groups)
    validation_count = 1 if count >= 3 else 0
    test_count = 1 if count >= 2 else 0
    train_count = count - validation_count - test_count
    boundaries = (train_count, train_count + validation_count)
    for index, (_, members) in enumerate(ordered_groups):
        split = "train" if index < boundaries[0] else "validation"
        if index >= boundaries[1]:
            split = "test"
        result[split].extend(sorted(members, key=lambda item: str(item["record_id"])))
    result["safety"].sort(key=lambda item: str(item["record_id"]))
    return result
