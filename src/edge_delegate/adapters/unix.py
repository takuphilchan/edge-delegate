"""Bounded local transport for the reference emulator (Linux/WSL only)."""

import json
import socket
import time
from datetime import UTC, datetime

from edge_delegate.contracts import CapabilityCard, DeviceState
from edge_delegate.runtime.ports import Reconciliation, UnknownPhysicalOutcome

MAX_MESSAGE_BYTES = 65536


def receive(sock, deadline):
    data = bytearray()
    while b"\n" not in data:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("transport deadline exceeded")
        sock.settimeout(remaining)
        chunk = sock.recv(min(4096, MAX_MESSAGE_BYTES + 1 - len(data)))
        if not chunk:
            raise ConnectionError("connection closed before acknowledgement")
        data.extend(chunk)
        if len(data) > MAX_MESSAGE_BYTES:
            raise ValueError("transport message exceeds limit")
    if data.count(b"\n") != 1 or not data.endswith(b"\n"):
        raise ValueError("expected one complete frame")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate transport field")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("nonfinite transport value")

    value = json.loads(data, object_pairs_hook=pairs, parse_constant=constant)
    if not isinstance(value, dict):
        raise ValueError("transport message must be an object")
    return value


class WallClock:
    def now(self):
        return datetime.now(UTC)


class UnixGateway:
    api_version = "edge-delegate-gateway.v2"

    def __init__(self, socket_path, *, device_id=None, timeout_ms=500):
        if not 1 <= timeout_ms <= 5000:
            raise ValueError("transport timeout must be 1..5000 ms")
        self.socket_path = str(socket_path)
        self.device_id = device_id
        self.timeout_ms = timeout_ms
        self.transport_ms = {}
        self.clock = WallClock()
        hello = self._call({"method": "describe"}, self._deadline())
        discovered = hello.get("device_id")
        if not isinstance(discovered, str) or not discovered.strip():
            raise ValueError("device must report a stable nonempty identity")
        if self.device_id is not None and discovered != self.device_id:
            raise ValueError("device identity mismatch")
        self.device_id = discovered
        self._cards = tuple(CapabilityCard.from_dict(card) for card in hello["capabilities"])
        if len({card.capability_id for card in self._cards}) != len(self._cards):
            raise ValueError("duplicate device capabilities")

    @property
    def capability_cards(self):
        return self._cards

    def _deadline(self):
        return time.monotonic() + self.timeout_ms / 1000

    def _call(self, request, deadline):
        started = time.perf_counter()
        try:
            return self._request(request, deadline)
        finally:
            method = request["method"]
            self.transport_ms[method] = (
                self.transport_ms.get(method, 0.0) + (time.perf_counter() - started) * 1000
            )

    def _request(self, request, deadline):
        request = {
            **request,
            "version": "edge-device.v1",
            "device_id": self.device_id,
            "deadline": deadline,
        }
        payload = json.dumps(request, allow_nan=False).encode() + b"\n"
        if len(payload) > MAX_MESSAGE_BYTES:
            raise ValueError("request too large")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("deadline exceeded")
            sock.settimeout(remaining)
            sock.connect(self.socket_path)
            sock.sendall(payload)
            response = receive(sock, deadline)
        if (
            response.get("version") != "edge-device.v1"
            or (self.device_id is not None and response.get("device_id") != self.device_id)
        ):
            raise ValueError("invalid response identity or version")
        return response

    def snapshot(self):
        return DeviceState.from_dict(self._call({"method": "snapshot"}, self._deadline())["state"])

    def invoke(self, capability_id, arguments):
        raise RuntimeError("use deadline-aware execution with a durable journal")

    def invoke_bounded(self, capability_id, arguments, *, operation_id, deadline):
        response = self._call(
            {
                "method": "invoke",
                "operation_id": operation_id,
                "capability_id": capability_id,
                "arguments": dict(arguments),
            },
            deadline,
        )
        if response.get("operation_id") != operation_id or response.get("status") != "succeeded":
            raise UnknownPhysicalOutcome("invocation acknowledgement not confirmed")
        return response["result"]

    def reconcile(self, operation_id, *, deadline):
        return self._receipt("reconcile", operation_id, deadline)

    def cancel_operation(self, operation_id, *, deadline):
        return self._receipt("cancel", operation_id, deadline)

    def _receipt(self, method, operation_id, deadline):
        response = self._call({"method": method, "operation_id": operation_id}, deadline)
        if response.get("operation_id") != operation_id or response.get("status") not in {
            "unknown",
            "succeeded",
            "failed",
        }:
            raise UnknownPhysicalOutcome("invalid reconciliation response")
        return Reconciliation(response["status"], response.get("result"))
