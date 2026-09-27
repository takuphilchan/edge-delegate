"""Independent plugin example: exact commands and a durable software counter.

No inference/training claims. Only public Edge Delegate interfaces are imported.
SQLite commits are durable but not hard real-time; this is not a hardware adapter.
"""

import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime

from edge_delegate.contracts import CapabilityCard, DeviceState, PlanStep
from edge_delegate.model_plugins.api import ModelPluginDescriptor
from edge_delegate.model_plugins.compute import ModelComputeCapabilities
from edge_delegate.planner.tasks import (
    BoundedPlanner,
    TaskCatalog,
    TaskDecision,
    TaskDefinition,
    reference_catalog,
)
from edge_delegate.runtime.ports import CapabilityExecutionError, Reconciliation


class Clock:
    def now(self):
        return datetime.now(UTC)


def steps(capability, parameters):
    if parameters:
        raise ValueError("counter tasks accept no parameters")
    return (PlanStep("counter", capability),)


def catalog():
    return TaskCatalog(
        [
            TaskDefinition(
                "read_counter", "Read the software counter.", lambda p: steps("counter.read", p)
            ),
            TaskDefinition(
                "increment_counter",
                "Increment the software counter once.",
                lambda p: steps("counter.increment", p),
            ),
        ],
        version="counter-demo.v1",
    )


class Session:
    def __init__(self):
        self.model_info = {
            "model_id": "exact-command-example",
            "qualified": False,
            "trained": False,
        }
        self.planner = BoundedPlanner(self.decide, catalog=catalog())

    def decide(self, request, context):
        commands = {"read counter": "read_counter", "increment counter": "increment_counter"}
        return TaskDecision(commands.get(request.text.strip().lower().rstrip("."), "deny"))

    def selected_capability_ids(self, request, context):
        return tuple(card.capability_id for card in context.capabilities)

    def last_generation(self, *, include_raw_output):
        return None

    def classify_error(self, error):
        return "counter_example_error"


class Plugin:
    descriptor = ModelPluginDescriptor(
        "counter-demo", "0.1.0", "Exact-command counter example", ("counter-demo",)
    )
    compute_capabilities = ModelComputeCapabilities(("fp32",), ("none",), False, False, False, 8000)

    def create_diagnostic_session(self, *, artifact_path, settings):
        if artifact_path is not None or settings:
            raise ValueError("counter-demo uses no weights or model settings")
        return Session()

    def create_planner(self, *, artifact_path, settings):
        return self.create_diagnostic_session(
            artifact_path=artifact_path, settings=settings
        ).planner


class DisplayPlugin(Plugin):
    """One exact phrase for wheel/emulator smoke tests; no learned model."""

    descriptor = ModelPluginDescriptor(
        "display-demo", "0.1.0", "Exact-command display example", ("display-demo",)
    )

    def create_diagnostic_session(self, *, artifact_path, settings):
        session = super().create_diagnostic_session(artifact_path=artifact_path, settings=settings)
        session.model_info = {
            "model_id": "exact-display-example",
            "trained": False,
            "qualified": False,
        }
        session.planner = BoundedPlanner(
            lambda request, _: TaskDecision(
                "show_temperature" if request.text == "Show the temperature." else "deny"
            ),
            catalog=reference_catalog(),
        )
        return session


class Counter:
    api_version = "edge-delegate-gateway.v2"
    clock = Clock()

    def __init__(self, database):
        self.database = database
        if database == ":memory:":
            raise ValueError("counter must have a durable database")
        try:
            fd = os.open(database, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        with self.transaction(time.monotonic() + 1) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS device (id TEXT PRIMARY KEY, value INTEGER NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, capability TEXT, status TEXT, result INTEGER)"
            )
            row = db.execute("SELECT id FROM device").fetchone()
            self.device_id = row[0] if row else f"counter-{uuid.uuid4()}"
            if row is None:
                db.execute("INSERT INTO device VALUES (?,0)", (self.device_id,))
        self.capability_cards = tuple(
            CapabilityCard.from_dict(
                {
                    "schema_version": "capability-card.v0",
                    "capability_id": f"counter.{name}",
                    "version": "0.1.0",
                    "description": f"{name} the software counter",
                    "arguments": {},
                    "result": {"kind": "integer"},
                    "side_effect": effect,
                    "permissions": permissions,
                    "cost": {"latency_ms": 1},
                }
            )
            for name, effect, permissions in [
                ("read", "read", []),
                ("increment", "write", ["counter.write"]),
            ]
        )

    @contextmanager
    def transaction(self, deadline):
        if time.monotonic() >= deadline:
            raise TimeoutError("counter deadline expired")
        db = sqlite3.connect(self.database, timeout=max(0, deadline - time.monotonic()))
        try:
            db.execute("PRAGMA synchronous=FULL")
            with db:
                db.execute("BEGIN IMMEDIATE")
                if time.monotonic() >= deadline:
                    raise TimeoutError("counter deadline expired waiting for lock")
                yield db
                if time.monotonic() >= deadline:
                    raise TimeoutError("counter deadline expired before commit")
        finally:
            db.close()

    def snapshot(self):
        with self.transaction(time.monotonic() + 0.5) as db:
            value = db.execute("SELECT value FROM device").fetchone()[0]
        return DeviceState(
            str(uuid.uuid4()),
            self.clock.now(),
            {"counter.value": value},
            available_memory_bytes=134217728,
        )

    def invoke(self, *_):
        raise RuntimeError("use deadline-aware execution")

    def invoke_bounded(self, capability_id, arguments, *, operation_id, deadline):
        if arguments or capability_id not in {"counter.read", "counter.increment"}:
            raise CapabilityExecutionError("unsupported counter operation")
        with self.transaction(deadline) as db:
            row = db.execute(
                "SELECT capability,status,result FROM receipts WHERE id=?", (operation_id,)
            ).fetchone()
            if row:
                if row[0] != capability_id or row[1] != "succeeded":
                    raise CapabilityExecutionError("operation fenced or identity conflict")
                return row[2]
            if capability_id == "counter.increment":
                db.execute("UPDATE device SET value=value+1")
            value = db.execute("SELECT value FROM device").fetchone()[0]
            db.execute(
                "INSERT INTO receipts VALUES (?,?,'succeeded',?)",
                (operation_id, capability_id, value),
            )
            return value

    def reconcile(self, operation_id, *, deadline):
        with self.transaction(deadline) as db:
            row = db.execute(
                "SELECT status,result FROM receipts WHERE id=?", (operation_id,)
            ).fetchone()
            return Reconciliation("unknown") if row is None else Reconciliation(*row)

    def cancel_operation(self, operation_id, *, deadline):
        with self.transaction(deadline) as db:
            db.execute(
                "INSERT OR IGNORE INTO receipts VALUES (?,NULL,'failed',NULL)", (operation_id,)
            )
            row = db.execute(
                "SELECT status,result FROM receipts WHERE id=?", (operation_id,)
            ).fetchone()
            return Reconciliation(*row)


def device_adapter(*, settings):
    if set(settings) != {"database"} or not isinstance(settings["database"], str):
        raise ValueError("counter-demo requires one database path")
    return Counter(settings["database"])


plugin = Plugin()
display_plugin = DisplayPlugin()
