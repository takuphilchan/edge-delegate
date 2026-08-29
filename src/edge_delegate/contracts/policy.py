"""Versioned permission, approval, privacy, and resource policy contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from ._validation import (
    expect_bool,
    expect_datetime,
    expect_enum,
    expect_int,
    expect_mapping,
    expect_number,
    expect_sequence,
    expect_str,
    expect_string_set,
    fail,
    format_datetime,
    reject_unknown,
    require,
)


class PrivacyClass(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    PERSONAL = "personal"
    SENSITIVE = "sensitive"
    SECRET = "secret"


@dataclass(frozen=True, slots=True)
class ApprovalGrant:
    grant_id: str
    request_id: str
    capability_id: str
    plan_sha256: str
    expires_at: datetime

    @classmethod
    def from_dict(cls, raw: object, path: str = "$.approvals[]") -> ApprovalGrant:
        data = expect_mapping(raw, path)
        reject_unknown(
            data,
            {"grant_id", "request_id", "capability_id", "plan_sha256", "expires_at"},
            path,
        )
        return cls(
            grant_id=expect_str(require(data, "grant_id", path), f"{path}.grant_id", max_length=128),
            request_id=expect_str(
                require(data, "request_id", path), f"{path}.request_id", max_length=128
            ),
            capability_id=expect_str(
                require(data, "capability_id", path), f"{path}.capability_id", max_length=128
            ),
            plan_sha256=expect_str(
                require(data, "plan_sha256", path),
                f"{path}.plan_sha256",
                min_length=64,
                max_length=64,
                pattern=r"^[a-f0-9]{64}$",
            ),
            expires_at=expect_datetime(require(data, "expires_at", path), f"{path}.expires_at"),
        )

    def is_valid_for(
        self, request_id: str, capability_id: str, plan_sha256: str, now: datetime
    ) -> bool:
        return (
            self.request_id == request_id
            and self.capability_id == capability_id
            and self.plan_sha256 == plan_sha256
            and self.expires_at.astimezone(UTC) > now.astimezone(UTC)
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "grant_id": self.grant_id,
            "request_id": self.request_id,
            "capability_id": self.capability_id,
            "plan_sha256": self.plan_sha256,
            "expires_at": format_datetime(self.expires_at),
        }


@dataclass(frozen=True, slots=True)
class ExecutionBudget:
    max_steps: int = 8
    max_step_timeout_ms: int = 30_000
    max_total_latency_ms: int = 60_000
    max_total_energy_mj: float = 10_000.0

    @classmethod
    def from_dict(cls, raw: object, path: str = "$.budget") -> ExecutionBudget:
        data = expect_mapping(raw, path)
        reject_unknown(
            data,
            {
                "max_steps",
                "max_step_timeout_ms",
                "max_total_latency_ms",
                "max_total_energy_mj",
            },
            path,
        )
        return cls(
            max_steps=expect_int(data.get("max_steps", 8), f"{path}.max_steps", minimum=1),
            max_step_timeout_ms=expect_int(
                data.get("max_step_timeout_ms", 30_000),
                f"{path}.max_step_timeout_ms",
                minimum=1,
            ),
            max_total_latency_ms=expect_int(
                data.get("max_total_latency_ms", 60_000),
                f"{path}.max_total_latency_ms",
                minimum=1,
            ),
            max_total_energy_mj=expect_number(
                data.get("max_total_energy_mj", 10_000.0),
                f"{path}.max_total_energy_mj",
                minimum=0,
            ),
        )

    def to_dict(self) -> dict[str, int | float]:
        return {
            "max_steps": self.max_steps,
            "max_step_timeout_ms": self.max_step_timeout_ms,
            "max_total_latency_ms": self.max_total_latency_ms,
            "max_total_energy_mj": self.max_total_energy_mj,
        }


@dataclass(frozen=True, slots=True)
class Policy:
    policy_id: str
    granted_permissions: frozenset[str] = field(default_factory=frozenset)
    allowed_capabilities: frozenset[str] | None = None
    denied_capabilities: frozenset[str] = field(default_factory=frozenset)
    approvals: tuple[ApprovalGrant, ...] = ()
    external_allowed: bool = False
    external_privacy_classes: frozenset[PrivacyClass] = field(
        default_factory=lambda: frozenset({PrivacyClass.PUBLIC})
    )
    require_approval_for_physical: bool = True
    max_state_age_seconds: int = 300
    budget: ExecutionBudget = field(default_factory=ExecutionBudget)
    schema_version: str = field(default="policy.v0", init=False)

    @classmethod
    def from_dict(cls, raw: object, path: str = "$") -> Policy:
        data = expect_mapping(raw, path)
        reject_unknown(
            data,
            {
                "schema_version",
                "policy_id",
                "granted_permissions",
                "allowed_capabilities",
                "denied_capabilities",
                "approvals",
                "external_allowed",
                "external_privacy_classes",
                "require_approval_for_physical",
                "max_state_age_seconds",
                "budget",
            },
            path,
        )
        version = expect_str(require(data, "schema_version", path), f"{path}.schema_version")
        if version != "policy.v0":
            fail(f"{path}.schema_version", "version", "unsupported policy version")

        allowed_raw = data.get("allowed_capabilities")
        approvals_raw = expect_sequence(data.get("approvals", []), f"{path}.approvals")
        privacy_raw = expect_sequence(
            data.get("external_privacy_classes", [PrivacyClass.PUBLIC.value]),
            f"{path}.external_privacy_classes",
        )
        privacy = frozenset(
            expect_enum(item, f"{path}.external_privacy_classes[{index}]", PrivacyClass)
            for index, item in enumerate(privacy_raw)
        )
        return cls(
            policy_id=expect_str(
                require(data, "policy_id", path), f"{path}.policy_id", max_length=128
            ),
            granted_permissions=expect_string_set(
                data.get("granted_permissions", []), f"{path}.granted_permissions"
            ),
            allowed_capabilities=(
                None
                if allowed_raw is None
                else expect_string_set(allowed_raw, f"{path}.allowed_capabilities")
            ),
            denied_capabilities=expect_string_set(
                data.get("denied_capabilities", []), f"{path}.denied_capabilities"
            ),
            approvals=tuple(
                ApprovalGrant.from_dict(item, f"{path}.approvals[{index}]")
                for index, item in enumerate(approvals_raw)
            ),
            external_allowed=expect_bool(
                data.get("external_allowed", False), f"{path}.external_allowed"
            ),
            external_privacy_classes=privacy,
            require_approval_for_physical=expect_bool(
                data.get("require_approval_for_physical", True),
                f"{path}.require_approval_for_physical",
            ),
            max_state_age_seconds=expect_int(
                data.get("max_state_age_seconds", 300),
                f"{path}.max_state_age_seconds",
                minimum=0,
            ),
            budget=ExecutionBudget.from_dict(data.get("budget", {}), f"{path}.budget"),
        )

    def approval_for(
        self,
        request_id: str,
        capability_id: str,
        plan_sha256: str,
        now: datetime | None = None,
    ) -> ApprovalGrant | None:
        current = now or datetime.now(UTC)
        return next(
            (
                grant
                for grant in self.approvals
                if grant.is_valid_for(request_id, capability_id, plan_sha256, current)
            ),
            None,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "granted_permissions": sorted(self.granted_permissions),
            "allowed_capabilities": (
                None if self.allowed_capabilities is None else sorted(self.allowed_capabilities)
            ),
            "denied_capabilities": sorted(self.denied_capabilities),
            "approvals": [grant.to_dict() for grant in self.approvals],
            "external_allowed": self.external_allowed,
            "external_privacy_classes": sorted(item.value for item in self.external_privacy_classes),
            "require_approval_for_physical": self.require_approval_for_physical,
            "max_state_age_seconds": self.max_state_age_seconds,
            "budget": self.budget.to_dict(),
        }
