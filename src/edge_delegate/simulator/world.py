"""Thread-safe deterministic world and capability registry."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import RLock

from edge_delegate.contracts import CapabilityCard, Connectivity, DeviceState
from edge_delegate.contracts._validation import json_value
from edge_delegate.contracts.state import JsonValue

from .clock import ManualClock

type CapabilityHandler = Callable[[Mapping[str, JsonValue], SimulatedWorld], JsonValue]


class CapabilityInvocationError(RuntimeError):
    """Raised when a simulated capability cannot be invoked safely."""


@dataclass(frozen=True, slots=True)
class Invocation:
    capability_id: str
    arguments: Mapping[str, JsonValue]
    result: JsonValue


@dataclass(frozen=True, slots=True)
class RegisteredCapability:
    card: CapabilityCard
    handler: CapabilityHandler


class SimulatedWorld:
    def __init__(
        self,
        *,
        values: Mapping[str, JsonValue] | None = None,
        connectivity: Connectivity = Connectivity.OFFLINE,
        battery_percent: float | None = None,
        available_memory_bytes: int | None = None,
        clock: ManualClock | None = None,
    ) -> None:
        if not all(isinstance(key, str) for key in (values or {})):
            raise ValueError("simulated state keys must be strings")
        self._values = {
            key: json_value(value, f"$.values.{key}") for key, value in (values or {}).items()
        }
        self._connectivity = connectivity
        self._battery_percent = battery_percent
        self._available_memory_bytes = available_memory_bytes
        self._clock = clock or ManualClock.at_epoch()
        self._registry: dict[str, RegisteredCapability] = {}
        self._invocations: list[Invocation] = []
        self._snapshot_counter = 0
        self._lock = RLock()

    @property
    def clock(self) -> ManualClock:
        return self._clock

    @property
    def capability_cards(self) -> tuple[CapabilityCard, ...]:
        with self._lock:
            return tuple(item.card for _, item in sorted(self._registry.items()))

    @property
    def invocations(self) -> tuple[Invocation, ...]:
        with self._lock:
            return tuple(self._invocations)

    def register(self, card: CapabilityCard, handler: CapabilityHandler) -> None:
        with self._lock:
            if card.capability_id in self._registry:
                raise ValueError(f"capability already registered: {card.capability_id}")
            self._registry[card.capability_id] = RegisteredCapability(card=card, handler=handler)

    def card(self, capability_id: str) -> CapabilityCard:
        try:
            return self._registry[capability_id].card
        except KeyError as exc:
            raise CapabilityInvocationError(f"unknown capability: {capability_id}") from exc

    def snapshot(self) -> DeviceState:
        with self._lock:
            self._snapshot_counter += 1
            return DeviceState(
                snapshot_id=f"sim-{self._snapshot_counter}",
                observed_at=self._clock.now(),
                values=dict(self._values),
                connectivity=self._connectivity,
                battery_percent=self._battery_percent,
                available_memory_bytes=self._available_memory_bytes,
            )

    def read(self, key: str) -> JsonValue:
        with self._lock:
            if key not in self._values:
                raise CapabilityInvocationError(f"state value is unavailable: {key}")
            return json_value(self._values[key], f"$.values.{key}")

    def write(self, key: str, value: JsonValue) -> None:
        if not isinstance(key, str):
            raise TypeError("simulated state keys must be strings")
        with self._lock:
            self._values[key] = json_value(value, f"$.values.{key}")

    def set_connectivity(self, connectivity: Connectivity) -> None:
        with self._lock:
            self._connectivity = connectivity

    def invoke(self, capability_id: str, arguments: Mapping[str, JsonValue]) -> JsonValue:
        with self._lock:
            try:
                registered = self._registry[capability_id]
            except KeyError as exc:
                raise CapabilityInvocationError(f"unknown capability: {capability_id}") from exc

            card = registered.card
            expected = set(card.arguments)
            supplied = set(arguments)
            missing = sorted(
                name for name, spec in card.arguments.items() if spec.required and name not in supplied
            )
            if missing:
                raise CapabilityInvocationError(f"missing argument(s): {', '.join(missing)}")
            unknown = sorted(supplied - expected)
            if unknown:
                raise CapabilityInvocationError(f"unknown argument(s): {', '.join(unknown)}")
            copied_arguments = {
                name: json_value(value, f"$.arguments.{name}") for name, value in arguments.items()
            }
            for name, value in copied_arguments.items():
                if not card.arguments[name].matches(value):
                    raise CapabilityInvocationError(f"invalid argument value: {name}")

            try:
                result = json_value(
                    registered.handler(copied_arguments, self), f"$.result.{capability_id}"
                )
            except CapabilityInvocationError:
                raise
            except Exception as exc:
                raise CapabilityInvocationError(f"capability handler failed: {capability_id}") from exc
            if card.result is None and result is not None:
                raise CapabilityInvocationError("capability returned an undeclared result")
            if card.result is not None and not card.result.matches(result):
                raise CapabilityInvocationError("capability result violates its declared type")

            self._clock.advance(seconds=card.cost.latency_ms / 1000)
            self._invocations.append(
                Invocation(
                    capability_id=capability_id,
                    arguments=copied_arguments,
                    result=result,
                )
            )
            return result
