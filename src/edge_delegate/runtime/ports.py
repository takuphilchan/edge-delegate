"""Runtime-owned ports implemented by device and persistence adapters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from edge_delegate.contracts import CapabilityCard, DeviceState
from edge_delegate.contracts.state import JsonValue

type AuditValue = bool | int | float | str | None


class CapabilityExecutionError(RuntimeError):
    """A device adapter could not safely complete a capability invocation."""


class UnknownPhysicalOutcome(CapabilityExecutionError):
    """The action may have happened; callers must not blindly retry it."""


@dataclass(frozen=True, slots=True)
class Reconciliation:
    status: str  # succeeded, failed, or unknown
    result: JsonValue = None


@runtime_checkable
class DeadlineGateway(Protocol):
    """v2 extension; deadline is an absolute host monotonic-clock timestamp."""

    @property
    def api_version(self) -> str: ...

    @property
    def device_id(self) -> str: ...

    def invoke_bounded(
        self,
        capability_id: str,
        arguments: Mapping[str, JsonValue],
        *,
        operation_id: str,
        deadline: float,
    ) -> JsonValue: ...

    def reconcile(self, operation_id: str, *, deadline: float) -> Reconciliation: ...


@runtime_checkable
class CancellationGateway(Protocol):
    """Optional durable fence, not rollback or deletion of operation history.

    Atomically return an existing receipt, or persist a tombstone that prevents
    this operation ID from ever dispatching. No receipt alone is not cancellation.
    """

    def cancel_operation(self, operation_id: str, *, deadline: float) -> Reconciliation: ...


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime:
        """Return the current timezone-aware time."""
        ...


@runtime_checkable
class DeviceGateway(Protocol):
    """Minimal device boundary required by coordination and execution."""

    @property
    def clock(self) -> Clock: ...

    @property
    def capability_cards(self) -> tuple[CapabilityCard, ...]: ...

    def snapshot(self) -> DeviceState: ...

    def invoke(self, capability_id: str, arguments: Mapping[str, JsonValue]) -> JsonValue: ...


@runtime_checkable
class AuditSink(Protocol):
    def append(
        self,
        *,
        request_id: str,
        event_type: str,
        outcome: str,
        details: Mapping[str, AuditValue] | None = None,
        timestamp: datetime | None = None,
    ) -> object:
        """Append a privacy-minimal audit event."""
        ...


@dataclass(frozen=True, slots=True)
class IdempotencyEntry:
    fingerprint: str
    result: JsonValue


@runtime_checkable
class IdempotencyRepository(Protocol):
    def lookup(self, key: str, fingerprint: str) -> IdempotencyEntry | None: ...

    def record(self, key: str, fingerprint: str, result: JsonValue) -> None: ...
