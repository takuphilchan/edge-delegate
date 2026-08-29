"""Internal request contract presented to planner implementations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from ._validation import expect_mapping, expect_str, json_value, reject_unknown, require
from .state import JsonValue


@dataclass(frozen=True, slots=True)
class PlanningRequest:
    request_id: str
    text: str
    locale: str = "en"
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: object, path: str = "$") -> PlanningRequest:
        data = expect_mapping(raw, path)
        reject_unknown(data, {"request_id", "text", "locale", "metadata"}, path)
        metadata = expect_mapping(data.get("metadata", {}), f"{path}.metadata")
        return cls(
            request_id=expect_str(
                require(data, "request_id", path), f"{path}.request_id", max_length=128
            ),
            text=expect_str(require(data, "text", path), f"{path}.text", max_length=8_000),
            locale=expect_str(data.get("locale", "en"), f"{path}.locale", max_length=35),
            metadata={
                key: json_value(value, f"{path}.metadata.{key}")
                for key, value in metadata.items()
            },
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "text": self.text,
            "locale": self.locale,
            "metadata": dict(self.metadata),
        }

