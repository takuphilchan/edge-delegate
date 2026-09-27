"""Durable claims; an unresolved operation blocks new work on that device."""

import hashlib
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from threading import Lock

from edge_delegate.contracts import PlanIR, PlanningRequest

from .idempotency import IdempotencyConflict
from .ports import CapabilityExecutionError, UnknownPhysicalOutcome


class OperationJournal:
    def __init__(self, path: str | Path):
        self._timing_lock = Lock()
        self._timing = dict.fromkeys(
            ("connect_ms", "setup_ms", "body_ms", "commit_ms", "close_ms", "transactions"), 0.0
        )
        self.path = str(path)
        if self.path == ":memory:":
            raise ValueError("gateway operation journal must be durable")
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS operations (
                operation_id TEXT PRIMARY KEY, device_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL, status TEXT NOT NULL, result TEXT)""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(operations)")}
            for column in ("request_id", "metadata"):
                if column not in columns:
                    db.execute(f"ALTER TABLE operations ADD COLUMN {column} TEXT")
            db.execute(
                "CREATE INDEX IF NOT EXISTS operations_request ON operations(device_id,request_id)"
            )
            db.execute("""CREATE TABLE IF NOT EXISTS audit (
                seq INTEGER PRIMARY KEY, request_id TEXT NOT NULL, event_type TEXT NOT NULL,
                outcome TEXT NOT NULL, timestamp TEXT, details TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS requests (
                request_id TEXT PRIMARY KEY, device_id TEXT NOT NULL,
                input_sha256 TEXT, plan TEXT)""")

    def request_plan(self, device_id, request):
        """Reserve request identity before planning; recover its immutable proposal.

        Raw request text is not stored. Plan arguments are persisted for recovery.
        A request ID is unique across devices within this journal.
        """
        request = PlanningRequest.from_dict(request.to_dict())
        encoded = json.dumps(request.to_dict(), sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT device_id,input_sha256,plan FROM requests WHERE request_id=?",
                (request.request_id,),
            ).fetchone()
            if row:
                if row[0] != device_id or row[1] != fingerprint:
                    raise IdempotencyConflict("request ID reused with different input or device")
                return None if row[2] is None else PlanIR.from_dict(json.loads(row[2]))
            if db.execute(
                "SELECT 1 FROM operations WHERE request_id=? LIMIT 1", (request.request_id,)
            ).fetchone():
                raise IdempotencyConflict(
                    "legacy request has no plan binding; reconcile receipts, then use a new ID"
                )
            db.execute(
                "INSERT INTO requests VALUES (?,?,?,NULL)",
                (request.request_id, device_id, fingerprint),
            )
        return None

    def bind_plan(self, device_id, plan):
        """First proposal wins atomically; a changed retry must never add actions."""
        plan = PlanIR.from_dict(plan.to_dict())
        encoded = json.dumps(plan.to_dict(), sort_keys=True, separators=(",", ":"))
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT device_id,plan FROM requests WHERE request_id=?", (plan.request_id,)
            ).fetchone()
            if row:
                if row[0] != device_id or (row[1] is not None and row[1] != encoded):
                    raise IdempotencyConflict(
                        "request is already bound to a different device or plan"
                    )
                if row[1] is not None:
                    # Gateway planning and direct Executor entry both enforce this binding.
                    # An identical durable binding needs no second UPDATE/commit write.
                    return
                db.execute(
                    "UPDATE requests SET plan=? WHERE request_id=?", (encoded, plan.request_id)
                )
            else:
                if db.execute(
                    "SELECT 1 FROM operations WHERE request_id=? LIMIT 1", (plan.request_id,)
                ).fetchone():
                    raise IdempotencyConflict("legacy request requires receipt-only recovery")
                # Direct Executor clients lack original text but still bind the complete plan.
                db.execute(
                    "INSERT INTO requests VALUES (?,?,NULL,?)",
                    (plan.request_id, device_id, encoded),
                )

    @contextmanager
    def connection(self):
        started = time.perf_counter()
        db = sqlite3.connect(self.path, timeout=2)
        connected = time.perf_counter()
        setup_done = body_done = commit_done = connected
        try:
            db.execute("PRAGMA synchronous=FULL")
            setup_done = time.perf_counter()
            try:
                yield db
            except BaseException:
                body_done = time.perf_counter()
                db.rollback()
                raise
            else:
                body_done = time.perf_counter()
                db.commit()
            finally:
                commit_done = time.perf_counter()
        finally:
            db.close()
            closed = time.perf_counter()
            with self._timing_lock:
                for key, value in {
                    "connect_ms": connected - started,
                    "setup_ms": setup_done - connected,
                    "body_ms": max(0, body_done - setup_done),
                    "commit_ms": max(0, commit_done - body_done),
                    "close_ms": closed - max(commit_done, setup_done),
                }.items():
                    self._timing[key] += value * 1000
                self._timing["transactions"] += 1

    def timing_snapshot(self):
        """Cumulative wall times, including failed transactions; no SQL or argument data."""
        with self._timing_lock:
            return dict(self._timing)

    def claim(self, operation_id, device_id, fingerprint, *, request_id=None, metadata=None):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT fingerprint,status,result,device_id FROM operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if row:
                if row[0] != fingerprint or row[3] != device_id:
                    raise IdempotencyConflict(
                        "operation identity reused with different device or arguments"
                    )
                return row[1], None if row[2] is None else json.loads(row[2])
            unresolved = db.execute(
                "SELECT 1 FROM operations WHERE device_id=? AND status='unknown' LIMIT 1",
                (device_id,),
            ).fetchone()
            if unresolved:
                raise UnknownPhysicalOutcome(
                    "device has unresolved work; reconcile before new work"
                )
            db.execute(
                "INSERT INTO operations(operation_id,device_id,fingerprint,status,result,request_id,metadata) "
                "VALUES (?,?,?,'unknown',NULL,?,?)",
                (
                    operation_id,
                    device_id,
                    fingerprint,
                    request_id,
                    None if metadata is None else json.dumps(metadata, allow_nan=False),
                ),
            )
            return "claimed", None

    def recorded_operations(self, device_id, *, request_id=None, operation_id=None):
        """Look up receipts to reconcile; never claim or create an operation."""
        if (request_id is None) == (operation_id is None):
            raise ValueError("select exactly one request ID or operation ID")
        column, value = (
            ("request_id", request_id) if request_id is not None else ("operation_id", operation_id)
        )
        with self.connection() as db:
            rows = db.execute(
                "SELECT operation_id,status,result,request_id,metadata FROM operations "
                f"WHERE device_id=? AND {column}=? ORDER BY rowid",
                (device_id, value),
            ).fetchall()
        return [
            {
                "operation_id": row[0],
                "status": row[1],
                "result": None if row[2] is None else json.loads(row[2]),
                "request_id": row[3],
                "metadata": None if row[4] is None else json.loads(row[4]),
            }
            for row in rows
        ]

    def finish(self, operation_id, status, result=None):
        if status not in {"succeeded", "failed"}:
            raise ValueError("only confirmed results can complete an operation")
        encoded = json.dumps(result, allow_nan=False)
        with self.connection() as db:
            changed = db.execute(
                "UPDATE operations SET status=?,result=? WHERE operation_id=? AND status='unknown'",
                (status, encoded, operation_id),
            ).rowcount
            if not changed:
                row = db.execute(
                    "SELECT status,result FROM operations WHERE operation_id=?", (operation_id,)
                ).fetchone()
                if row != (status, encoded):
                    raise CapabilityExecutionError("conflicting operation completion")

    def append(self, *, request_id, event_type, outcome, details=None, timestamp=None):
        with self.connection() as db:
            db.execute(
                "INSERT INTO audit(request_id,event_type,outcome,timestamp,details) VALUES(?,?,?,?,?)",
                (
                    request_id,
                    event_type,
                    outcome,
                    None if timestamp is None else timestamp.isoformat(),
                    json.dumps(dict(details or {}), allow_nan=False),
                ),
            )
