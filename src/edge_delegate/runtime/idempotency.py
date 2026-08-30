"""Thread-safe duplicate-execution protection for side effects."""

from __future__ import annotations

from threading import RLock

from edge_delegate.contracts.state import JsonValue

from .ports import IdempotencyEntry


class IdempotencyConflict(RuntimeError):
    """A key was reused for a different capability invocation."""


class IdempotencyStore:
    def __init__(self) -> None:
        self._records: dict[str, IdempotencyEntry] = {}
        self._lock = RLock()

    def lookup(self, key: str, fingerprint: str) -> IdempotencyEntry | None:
        with self._lock:
            record = self._records.get(key)
            if record is not None and record.fingerprint != fingerprint:
                raise IdempotencyConflict(f"idempotency key was reused with different input: {key}")
            return record

    def record(self, key: str, fingerprint: str, result: JsonValue) -> None:
        with self._lock:
            existing = self._records.get(key)
            if existing is not None and existing.fingerprint != fingerprint:
                raise IdempotencyConflict(f"idempotency key was reused with different input: {key}")
            self._records[key] = IdempotencyEntry(fingerprint=fingerprint, result=result)
