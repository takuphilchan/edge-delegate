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
    # Device/value/policy counterfactuals must not split the same source template.
    source = metadata.get("scenario_group", metadata.get("template_id"))
    if not isinstance(source, str) or not source.strip():
        raise ValueError("scenario_group or template_id is required for isolated splitting")
    return (source, "", "")


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
    records = list(records)
    parent = {}

    def root(key):
        parent.setdefault(key, key)
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    aliases = {}
    for record in records:
        key = group_key(record)
        root(key)
        for field in ("template_id", "paraphrase_cluster", "scenario_group"):
            value = _metadata(record).get(field)
            if value:
                alias = (field, str(value))
                previous = aliases.setdefault(alias, key)
                a, b = root(key), root(previous)
                parent[max(a, b)] = min(a, b)
    grouped: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    safety_groups = set()
    for record in records:
        tags = _metadata(record).get("tags", [])
        if isinstance(tags, list) and "safety" in tags:
            result["safety"].append(record)
            safety_groups.add(root(group_key(record)))
        else:
            grouped[root(group_key(record))].append(record)
    if safety_groups & grouped.keys():
        raise ValueError("held-out safety sources overlap functional/training sources")

    ordered_groups = sorted(
        grouped.items(),
        key=lambda item: hashlib.sha256(f"{seed}:{'|'.join(item[0])}".encode()).hexdigest(),
    )
    count = len(ordered_groups)
    validation_count = max(1, round(count * 0.15)) if count >= 3 else 0
    test_count = max(1, round(count * 0.15)) if count >= 2 else 0
    train_count = count - validation_count - test_count
    boundaries = (train_count, train_count + validation_count)
    for index, (_, members) in enumerate(ordered_groups):
        split = "train" if index < boundaries[0] else "validation"
        if index >= boundaries[1]:
            split = "test"
        result[split].extend(sorted(members, key=lambda item: str(item["record_id"])))
    result["safety"].sort(key=lambda item: str(item["record_id"]))
    return result
