"""Durable software light adapter. No hardware, network, or model dependencies.

State and receipts commit atomically in this emulator. Physical adapters cannot
infer equivalent guarantees; they must independently qualify their effects.
"""

import hashlib
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime

from edge_delegate.contracts import CapabilityCard, DeviceState, Policy
from edge_delegate.planner.control import validate_light_action
from edge_delegate.runtime.ports import CapabilityExecutionError, Reconciliation


class _Clock:
    def now(self):
        return datetime.now(UTC)


def light_capabilities():
    cards = []
    for field, parameter, spec in (
        ("power", "on", {"kind": "boolean"}),
        ("brightness", "percent", {"kind": "integer", "minimum": 0, "maximum": 100}),
    ):
        for verb in ("read", "set"):
            cards.append(
                CapabilityCard.from_dict(
                    {
                        "schema_version": "capability-card.v0",
                        "capability_id": f"light.{field}.{verb}",
                        "version": "1.0.0",
                        "description": f"{verb} software light {field}; brightness never changes power",
                        "arguments": {parameter: spec} if verb == "set" else {},
                        "result": spec,
                        "side_effect": "write" if verb == "set" else "read",
                        "permissions": ["light.write"] if verb == "set" else [],
                        "cost": {"latency_ms": 2},
                    }
                )
            )
    return tuple(cards)


def light_policy():
    """Explicit emulator policy; not authorization for physical installations."""
    return Policy(
        "software-lights.v1",
        granted_permissions=frozenset({"light.write"}),
        allowed_capabilities=frozenset(card.capability_id for card in light_capabilities()),
        max_state_age_seconds=5,
    )


class LightEmulator:
    api_version = "edge-delegate-gateway.v2"
    clock = _Clock()

    def __init__(self, database, *, lose_ack=False):
        self.database = str(database)
        if self.database == ":memory:":
            raise ValueError("light emulator requires durable storage")
        self.lose_ack = lose_ack
        self.capability_cards = light_capabilities()
        try:
            descriptor = os.open(self.database, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
        with self._transaction(time.monotonic() + 2, check_identity=False) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS light (singleton INTEGER PRIMARY KEY CHECK(singleton=1), id TEXT NOT NULL, power INTEGER NOT NULL, brightness INTEGER NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS receipts (operation TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT NOT NULL)"
            )
            db.execute("INSERT OR IGNORE INTO light VALUES(1,?,0,100)", (f"light-{uuid.uuid4()}",))
            self.device_id = db.execute("SELECT id FROM light WHERE singleton=1").fetchone()[0]

    @contextmanager
    def _transaction(self, deadline, *, check_identity=True):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("light deadline expired")
        db = sqlite3.connect(self.database, timeout=remaining)
        try:
            db.execute("PRAGMA synchronous=FULL")
            with db:
                db.execute("BEGIN IMMEDIATE")
                if time.monotonic() >= deadline:
                    raise TimeoutError("light deadline expired waiting for storage")
                if check_identity:
                    row = db.execute("SELECT id FROM light WHERE singleton=1").fetchone()
                    if row != (self.device_id,):
                        raise CapabilityExecutionError("light storage identity changed")
                yield db
                if time.monotonic() >= deadline:
                    raise TimeoutError("light deadline expired before commit")
        finally:
            db.close()

    def snapshot(self):
        with self._transaction(time.monotonic() + 0.5) as db:
            power, brightness = db.execute("SELECT power,brightness FROM light").fetchone()
        return DeviceState(
            str(uuid.uuid4()),
            self.clock.now(),
            {
                "light.power": bool(power),
                "light.brightness_percent": brightness,
            },
        )

    def invoke(self, *_):
        raise RuntimeError("use bounded invocation")

    def invoke_bounded(self, capability_id, arguments, *, operation_id, deadline):
        validate_light_action(capability_id, arguments)
        fingerprint = hashlib.sha256(
            json.dumps(
                [capability_id, dict(arguments)],
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        with self._transaction(deadline) as db:
            receipt = db.execute(
                "SELECT fingerprint,result FROM receipts WHERE operation=?",
                (operation_id,),
            ).fetchone()
            if receipt:
                if receipt[0] != fingerprint:
                    raise CapabilityExecutionError("operation arguments changed")
                return json.loads(receipt[1])
            if capability_id == "light.power.set":
                db.execute("UPDATE light SET power=? WHERE singleton=1", (int(arguments["on"]),))
            elif capability_id == "light.brightness.set":
                db.execute(
                    "UPDATE light SET brightness=? WHERE singleton=1", (arguments["percent"],)
                )
            power, brightness = db.execute("SELECT power,brightness FROM light").fetchone()
            result = bool(power) if capability_id.startswith("light.power.") else brightness
            db.execute(
                "INSERT INTO receipts VALUES(?,?,?)",
                (
                    operation_id,
                    fingerprint,
                    json.dumps(result),
                ),
            )
        if self.lose_ack:
            self.lose_ack = False
            raise ConnectionError("simulated completion followed by lost acknowledgement")
        return result

    def reconcile(self, operation_id, *, deadline):
        with self._transaction(deadline) as db:
            row = db.execute(
                "SELECT result FROM receipts WHERE operation=?",
                (operation_id,),
            ).fetchone()
        return (
            Reconciliation("unknown")
            if row is None
            else Reconciliation("succeeded", json.loads(row[0]))
        )
