"""Model-free loading and inspection of saved query context."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from edge_delegate.contracts import CapabilityCard, DeviceState, Policy
from edge_delegate.policy.permissions import capability_allowed, missing_permissions

MAX_PROFILE_FILE_BYTES = 1024 * 1024


def _reject_constant(value: str):
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def _without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> object:
    try:
        with path.open("rb") as handle:
            payload = handle.read(MAX_PROFILE_FILE_BYTES + 1)
    except FileNotFoundError as exc:
        raise ValueError(f"profile is missing {path.name}: {path}") from exc
    if len(payload) > MAX_PROFILE_FILE_BYTES:
        raise ValueError(f"profile file exceeds {MAX_PROFILE_FILE_BYTES} bytes: {path}")
    return json.loads(
        payload.decode("utf-8"),
        object_pairs_hook=_without_duplicates,
        parse_constant=_reject_constant,
    )


@dataclass(frozen=True, slots=True)
class ClientProfile:
    """Saved context, not a device driver or authorization to execute."""

    root: Path
    capabilities: tuple[CapabilityCard, ...]
    state: DeviceState
    policy: Policy

    @classmethod
    def load(cls, root: Path) -> ClientProfile:
        resolved = root.resolve()
        if not resolved.is_dir():
            raise ValueError(f"profile directory does not exist: {root}")
        raw_cards = _load_json(resolved / "capabilities.json")
        if not isinstance(raw_cards, list):
            raise ValueError("profile capabilities.json must contain a JSON array")
        cards = tuple(
            CapabilityCard.from_dict(card, f"$[{index}]") for index, card in enumerate(raw_cards)
        )
        seen: set[str] = set()
        for card in cards:
            if card.capability_id in seen:
                raise ValueError(f"duplicate capability card: {card.capability_id}")
            seen.add(card.capability_id)
        return cls(
            root=resolved,
            capabilities=cards,
            state=DeviceState.from_dict(_load_json(resolved / "state.json")),
            policy=Policy.from_dict(_load_json(resolved / "policy.json")),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "root": str(self.root),
            "capability_ids": [card.capability_id for card in self.capabilities],
            "state": self.state.to_dict(),
            "policy": self.policy.to_dict(),
        }

    def inspect(self, *, now: datetime | None = None) -> dict[str, object]:
        current = now or datetime.now(UTC)
        age = self.state.age_seconds(current)
        warnings: list[str] = []
        if self.state.observed_at > current + timedelta(seconds=5):
            warnings.append("Snapshot is in the future; plans will fail timestamp validation.")
        if age > self.policy.max_state_age_seconds:
            warnings.append(
                "Snapshot is stale under this policy; plans with steps will be rejected."
            )
        if self.policy.max_state_age_seconds > 86400:
            warnings.append(
                "Policy allows state older than one day. Review this before using live devices."
            )
        if not self.capabilities:
            warnings.append("No capabilities are declared; no local action can be planned.")
        return {
            "schema_version": "edge-delegate-profile-report.v1",
            "root": str(self.root),
            "contracts_valid": True,
            "model_loaded": False,
            "execution_checked": False,
            "capabilities": [
                {
                    "id": card.capability_id,
                    "description": card.description,
                    "side_effect": card.side_effect.value,
                    "policy_allowed": capability_allowed(card, self.policy),
                    "missing_permissions": sorted(missing_permissions(card, self.policy)),
                }
                for card in self.capabilities
            ],
            "snapshot": {
                "id": self.state.snapshot_id,
                "observed_at": self.state.to_dict()["observed_at"],
                "age_seconds": age,
                "max_age_seconds": self.policy.max_state_age_seconds,
                "connectivity": self.state.connectivity.value,
            },
            "policy_id": self.policy.policy_id,
            "external_allowed": self.policy.external_allowed,
            "warnings": warnings,
            "note": "Saved context only. Capability availability and permissions do not authorize a plan. "
            "Approvals, preconditions, budgets, and each proposed plan still require validation.",
        }
