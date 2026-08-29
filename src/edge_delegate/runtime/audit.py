"""Privacy-minimal in-memory audit events."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock

type AuditValue = bool | int | float | str | None


@dataclass(frozen=True, slots=True)
class AuditEvent:
    timestamp: datetime
    request_id: str
    event_type: str
    outcome: str
    details: Mapping[str, AuditValue] = field(default_factory=dict)


class InMemoryAuditLog:
    """Testable audit sink that deliberately excludes request text and arguments."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
        self._lock = RLock()

    def append(
        self,
        *,
        request_id: str,
        event_type: str,
        outcome: str,
        details: Mapping[str, AuditValue] | None = None,
        timestamp: datetime | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            timestamp=(timestamp or datetime.now(UTC)).astimezone(UTC),
            request_id=request_id,
            event_type=event_type,
            outcome=outcome,
            details=dict(details or {}),
        )
        with self._lock:
            self._events.append(event)
        return event

    @property
    def events(self) -> tuple[AuditEvent, ...]:
        with self._lock:
            return tuple(self._events)
