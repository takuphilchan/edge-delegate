"""Immutable registry of explicitly installed, trusted device adapters."""

import hashlib
import json
from dataclasses import dataclass

from edge_delegate.contracts import Policy
from edge_delegate.contracts.control import ControlTarget
from edge_delegate.runtime.ports import DeadlineGateway, DeviceGateway


class TargetResolutionError(ValueError):
    def __init__(self, message, *, choices=()):
        super().__init__(message)
        self.choices = tuple(choices)


def _name(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise ValueError("device names must contain 1-128 characters")
    return " ".join(value.split()).casefold()


@dataclass(frozen=True)
class DeviceRegistration:
    name: str
    device: DeviceGateway
    policy: Policy
    aliases: tuple[str, ...] = ()
    endpoint_id: str = "main"

    def __post_init__(self):
        _name(self.name)
        if isinstance(self.aliases, str):
            raise ValueError("aliases must be a collection, not a string")
        object.__setattr__(self, "aliases", tuple(self.aliases))
        for alias in self.aliases:
            _name(alias)
        if (
            not isinstance(self.device, DeviceGateway)
            or not isinstance(self.device, DeadlineGateway)
            or self.device.api_version != "edge-delegate-gateway.v2"
        ):
            raise ValueError("control requires a deadline-aware device adapter")
        object.__setattr__(self, "policy", Policy.from_dict(self.policy.to_dict()))
        if self.policy.external_allowed:
            raise ValueError("control.v1 is local-only")
        self.target()

    def target(self):
        cards = sorted(self.device.capability_cards, key=lambda card: card.capability_id)
        if len({card.capability_id for card in cards}) != len(cards):
            raise ValueError("duplicate device capabilities")
        policy = self.policy.to_dict()
        # Grants bind to the compiled plan, which includes this target hash. Hashing
        # grants here would create a cycle and make approval impossible. All other
        # policy fields remain bound; the runtime validates current grants separately.
        policy.pop("approvals")
        binding = {
            "device_id": self.device.device_id,
            "endpoint_id": self.endpoint_id,
            "name": self.name,
            "aliases": self.aliases,
            "capabilities": [card.to_dict() for card in cards],
            "policy": policy,
        }
        digest = hashlib.sha256(
            json.dumps(binding, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
        return ControlTarget(self.device.device_id, self.endpoint_id, digest)


class DeviceRegistry:
    """One endpoint per adapter/device in this initial release.

    Shared aliases are allowed but always clarify. Canonical names must be unique;
    there is no 'first match wins', even when an alias equals another canonical name.
    """

    def __init__(self, registrations):
        self._entries = {}
        self._targets = {}
        self._names = {}
        canonical = set()
        for entry in registrations:
            if not isinstance(entry, DeviceRegistration):
                raise ValueError("registry requires DeviceRegistration objects")
            target = entry.target()
            if target.device_id in self._entries or _name(entry.name) in canonical:
                raise ValueError("duplicate device identity or canonical name")
            canonical.add(_name(entry.name))
            self._entries[target.device_id] = entry
            self._targets[target.device_id] = target
            for name in {_name(entry.name), *(_name(alias) for alias in entry.aliases)}:
                self._names.setdefault(name, []).append(target.device_id)
        if not self._entries:
            raise ValueError("device registry cannot be empty")

    def resolve(self, name):
        ids = self._names.get(_name(name), [])
        if len(ids) != 1:
            raise TargetResolutionError(
                "Specify a known device name." if not ids else "Which device do you mean?",
                choices=tuple(sorted(self._entries[i].name for i in ids)),
            )
        target = self._targets[ids[0]]
        self.entry(target)
        return target

    def entry(self, target):
        if not isinstance(target, ControlTarget):
            raise ValueError("typed target required")
        entry = self._entries.get(target.device_id)
        if entry is None or self._targets[target.device_id] != target or entry.target() != target:
            raise ValueError("target identity or configuration changed; do not dispatch")
        return entry

    def targets(self):
        return tuple(self._targets.values())
