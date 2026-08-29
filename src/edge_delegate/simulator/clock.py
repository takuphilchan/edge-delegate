"""Deterministic clock for repeatable execution tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass(slots=True)
class ManualClock:
    current: datetime

    def __post_init__(self) -> None:
        if self.current.tzinfo is None:
            raise ValueError("manual clock requires a timezone-aware date-time")
        self.current = self.current.astimezone(UTC)

    @classmethod
    def at_epoch(cls) -> ManualClock:
        return cls(datetime(2025, 1, 1, tzinfo=UTC))

    def now(self) -> datetime:
        return self.current

    def advance(self, *, seconds: float) -> datetime:
        if seconds < 0:
            raise ValueError("cannot move the clock backward")
        self.current += timedelta(seconds=seconds)
        return self.current

