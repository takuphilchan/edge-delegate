"""Installed immediate-action catalogs; no executable code is loaded from metadata."""

import hashlib
import json
from dataclasses import dataclass
from types import MappingProxyType

from edge_delegate.contracts._validation import expect_str
from edge_delegate.contracts.capability import CAPABILITY_ID_PATTERN, ValueSpec


@dataclass(frozen=True)
class ControlAction:
    action_id: str
    capability_id: str
    parameters: dict[str, ValueSpec]
    semantics: str

    def __post_init__(self):
        for field in ("action_id", "capability_id"):
            expect_str(getattr(self, field), field, max_length=128, pattern=CAPABILITY_ID_PATTERN)
        expect_str(self.semantics, "semantics", max_length=1000)
        copied = {}
        for name, spec in self.parameters.items():
            expect_str(name, "parameter", max_length=64)
            if not isinstance(spec, ValueSpec):
                raise ValueError("action parameters require typed ValueSpec constraints")
            copied[name] = ValueSpec.from_dict(spec.to_dict(), f"$.parameters.{name}")
        object.__setattr__(self, "parameters", MappingProxyType(copied))

    def to_dict(self):
        return {
            "action_id": self.action_id,
            "capability_id": self.capability_id,
            "parameters": {key: spec.to_dict() for key, spec in self.parameters.items()},
            "semantics": self.semantics,
        }


@dataclass(frozen=True)
class ControlCatalog:
    version: str
    actions: tuple[ControlAction, ...]

    def __post_init__(self):
        expect_str(self.version, "catalog.version", max_length=128)
        actions = tuple(self.actions)
        if not actions or any(not isinstance(action, ControlAction) for action in actions):
            raise ValueError("catalog requires typed installed actions")
        if len({action.action_id for action in actions}) != len(actions):
            raise ValueError("duplicate control action")
        object.__setattr__(self, "actions", actions)

    @property
    def fingerprint(self):
        payload = {
            "version": self.version,
            "actions": [a.to_dict() for a in sorted(self.actions, key=lambda a: a.action_id)],
        }
        return hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()

    def validate(self, action_id, parameters):
        action = next((a for a in self.actions if a.action_id == action_id), None)
        if action is None:
            raise ValueError("unsupported control action")
        if set(parameters) - set(action.parameters):
            raise ValueError("unknown control parameters")
        for name, spec in action.parameters.items():
            if name not in parameters:
                if spec.required:
                    raise ValueError("missing control parameter")
            elif not spec.matches(parameters[name]):
                raise ValueError("invalid control parameter")
        return action
