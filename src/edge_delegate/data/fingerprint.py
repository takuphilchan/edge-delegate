"""Canonical content fingerprints for records, datasets, and manifests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def content_fingerprint(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def dataset_fingerprint(records: Iterable[Mapping[str, object]]) -> str:
    digests = sorted(content_fingerprint(record) for record in records)
    return content_fingerprint({"record_sha256": digests})
