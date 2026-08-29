"""Stable Plan-IR serialization for fingerprints, tests, and audit records."""

from __future__ import annotations

import hashlib
import json

from edge_delegate.contracts import PlanIR


def canonicalize_plan(plan: PlanIR) -> str:
    return json.dumps(
        plan.to_dict(),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def plan_fingerprint(plan: PlanIR) -> str:
    return hashlib.sha256(canonicalize_plan(plan).encode("utf-8")).hexdigest()
