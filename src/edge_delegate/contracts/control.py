"""Versioned, explicitly targeted immediate controls; not a model protocol.

These envelopes bind a single endpoint before compiling an ordinary Plan IR.
They do not extend legacy plans to multi-device execution.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from ._validation import expect_mapping, expect_str, reject_unknown, require
from .capability import CAPABILITY_ID_PATTERN


@dataclass(frozen=True, slots=True)
class ControlTarget:
    device_id: str
    endpoint_id: str
    binding_sha256: str

    def __post_init__(self):
        for key in ("device_id", "endpoint_id"):
            expect_str(getattr(self, key), f"$.target.{key}", max_length=128)
        expect_str(self.binding_sha256, "$.target.binding_sha256", pattern=r"[a-f0-9]{64}")

    def to_dict(self):
        return {
            "device_id": self.device_id,
            "endpoint_id": self.endpoint_id,
            "binding_sha256": self.binding_sha256,
        }

    @classmethod
    def from_dict(cls, value):
        value = expect_mapping(value, "$.target")
        keys = {"device_id", "endpoint_id", "binding_sha256"}
        reject_unknown(value, keys, "$.target")
        return cls(**{key: require(value, key, "$.target") for key in keys})


@dataclass(frozen=True, slots=True)
class ControlRequest:
    request_id: str
    target: ControlTarget
    action: str
    parameters: Mapping[str, bool | int]
    catalog_sha256: str

    def __post_init__(self):
        expect_str(self.request_id, "$.request_id", max_length=128)
        if not isinstance(self.target, ControlTarget):
            raise ValueError("control request requires a typed target")
        expect_str(self.action, "$.action", max_length=128, pattern=CAPABILITY_ID_PATTERN)
        expect_str(self.catalog_sha256, "$.catalog_sha256", pattern=r"[a-f0-9]{64}")
        parameters = expect_mapping(self.parameters, "$.parameters")
        # v1 deliberately permits only the light contract's scalar types.
        if len(parameters) > 8 or any(type(v) not in {bool, int} for v in parameters.values()):
            raise ValueError("control.v1 parameters must be bounded boolean/integer fields")
        for key, value in parameters.items():
            expect_str(key, "$.parameters.<key>", max_length=64)
            if type(value) is int and not -(2**63) <= value < 2**63:
                raise ValueError("control integer exceeds signed 64-bit range")
        object.__setattr__(self, "parameters", MappingProxyType(dict(parameters)))

    def to_dict(self):
        return {
            "schema_version": "edge-control-request.v1",
            "request_id": self.request_id,
            "target": self.target.to_dict(),
            "action": self.action,
            "parameters": dict(self.parameters),
            "catalog_sha256": self.catalog_sha256,
        }

    @classmethod
    def from_dict(cls, value):
        value = expect_mapping(value, "$")
        keys = {"schema_version", "request_id", "target", "action", "parameters", "catalog_sha256"}
        reject_unknown(value, keys, "$")
        for key in keys:
            require(value, key, "$")
        if value["schema_version"] != "edge-control-request.v1":
            raise ValueError("unsupported control request version")
        return cls(
            value["request_id"],
            ControlTarget.from_dict(value["target"]),
            value["action"],
            value["parameters"],
            value["catalog_sha256"],
        )
