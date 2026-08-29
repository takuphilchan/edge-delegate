"""Minimal, policy-filtered external-model handoff contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from ._validation import (
    expect_datetime,
    expect_enum,
    expect_mapping,
    expect_sequence,
    expect_str,
    fail,
    format_datetime,
    json_value,
    reject_unknown,
    require,
)
from .policy import PrivacyClass
from .state import JsonValue


@dataclass(frozen=True, slots=True)
class ExternalHandoff:
    request_id: str
    reason: str
    task: str
    context: Mapping[str, JsonValue]
    questions: tuple[str, ...]
    included_privacy_classes: frozenset[PrivacyClass]
    removed_fields: tuple[str, ...]
    expires_at: datetime
    schema_version: str = field(default="handoff.v0", init=False)

    @classmethod
    def from_dict(cls, raw: object, path: str = "$") -> ExternalHandoff:
        data = expect_mapping(raw, path)
        reject_unknown(
            data,
            {
                "schema_version",
                "request_id",
                "reason",
                "task",
                "context",
                "questions",
                "included_privacy_classes",
                "removed_fields",
                "expires_at",
            },
            path,
        )
        version = expect_str(require(data, "schema_version", path), f"{path}.schema_version")
        if version != "handoff.v0":
            fail(f"{path}.schema_version", "version", "unsupported handoff version")
        context_raw = expect_mapping(require(data, "context", path), f"{path}.context")
        questions_raw = expect_sequence(require(data, "questions", path), f"{path}.questions")
        if not questions_raw:
            fail(f"{path}.questions", "min_items", "at least one external question is required")
        privacy_raw = expect_sequence(
            require(data, "included_privacy_classes", path),
            f"{path}.included_privacy_classes",
        )
        removed_raw = expect_sequence(data.get("removed_fields", []), f"{path}.removed_fields")
        return cls(
            request_id=expect_str(
                require(data, "request_id", path), f"{path}.request_id", max_length=128
            ),
            reason=expect_str(require(data, "reason", path), f"{path}.reason", max_length=256),
            task=expect_str(require(data, "task", path), f"{path}.task", max_length=8_000),
            context={
                key: json_value(value, f"{path}.context.{key}")
                for key, value in context_raw.items()
            },
            questions=tuple(
                expect_str(item, f"{path}.questions[{index}]", max_length=1000)
                for index, item in enumerate(questions_raw)
            ),
            included_privacy_classes=frozenset(
                expect_enum(item, f"{path}.included_privacy_classes[{index}]", PrivacyClass)
                for index, item in enumerate(privacy_raw)
            ),
            removed_fields=tuple(
                expect_str(item, f"{path}.removed_fields[{index}]", max_length=256)
                for index, item in enumerate(removed_raw)
            ),
            expires_at=expect_datetime(require(data, "expires_at", path), f"{path}.expires_at"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "reason": self.reason,
            "task": self.task,
            "context": dict(self.context),
            "questions": list(self.questions),
            "included_privacy_classes": sorted(
                item.value for item in self.included_privacy_classes
            ),
            "removed_fields": list(self.removed_fields),
            "expires_at": format_datetime(self.expires_at),
        }
