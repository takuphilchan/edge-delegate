"""Separate-process, durable reference device. This is not physical hardware."""

import argparse
import json
import os
import socket
import sqlite3
import sys
import time
import uuid
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from edge_delegate.adapters.unix import receive
from edge_delegate.runtime.executor import _invocation_fingerprint
from edge_delegate.runtime.ports import CapabilityExecutionError

from .examples import local_display


def serve(socket_path, database, *, fault="none", ready=None, on_ready=None):
    path = Path(socket_path)
    # Never remove an existing path belonging to another process/user.
    if path.exists():
        raise ValueError("socket path already exists; choose a fresh private directory")
    if path.parent.stat().st_mode & 0o077:
        raise ValueError("socket parent must be private (chmod 700)")
    world, _ = local_display()
    with (
        closing(sqlite3.connect(database)) as db,
        socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server,
    ):
        db.execute("PRAGMA synchronous=FULL")
        # Existing device databases retain their historical identity for receipt recovery.
        legacy = db.execute("SELECT 1 FROM sqlite_master WHERE name='receipts'").fetchone()
        db.execute("CREATE TABLE IF NOT EXISTS device_identity (id TEXT PRIMARY KEY)")
        identity = db.execute("SELECT id FROM device_identity").fetchone()
        if identity is None:
            device_id = "reference-emulator" if legacy else f"emulator-{uuid.uuid4()}"
            db.execute("INSERT INTO device_identity VALUES (?)", (device_id,))
        else:
            device_id = identity[0]
        db.execute("CREATE TABLE IF NOT EXISTS values_state (key TEXT PRIMARY KEY, value TEXT)")
        db.execute(
            "CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, fingerprint TEXT, result TEXT)"
        )
        if "status" not in {row[1] for row in db.execute("PRAGMA table_info(receipts)")}:
            db.execute("ALTER TABLE receipts ADD COLUMN status TEXT NOT NULL DEFAULT 'succeeded'")
        for key, value in world.snapshot().values.items():
            db.execute("INSERT OR IGNORE INTO values_state VALUES(?,?)", (key, json.dumps(value)))
        db.commit()
        server.bind(str(path))
        os.chmod(path, 0o600)
        server.listen(8)
        if ready is not None:
            ready.set()
        try:
            if on_ready is not None:
                on_ready(device_id)
            while True:
                conn, _ = server.accept()
                with conn:
                    try:
                        request = receive(conn, time.monotonic() + 1)
                        if request.get("version") != "edge-device.v1" or (
                            request.get("device_id") != device_id
                            and not (
                                request.get("method") == "describe"
                                and request.get("device_id") is None
                            )
                        ):
                            raise ValueError("unknown protocol or device")
                        deadline = request["deadline"]
                        if type(deadline) not in {int, float} or time.monotonic() >= deadline:
                            raise TimeoutError("expired request")
                        response = {"version": "edge-device.v1", "device_id": device_id}
                        for key, value in db.execute("SELECT key,value FROM values_state"):
                            world.write(key, json.loads(value))
                        # Snapshots must reflect a new observation, not a saved fixture timestamp.
                        state = world.snapshot().to_dict()
                        state["observed_at"] = datetime.now(UTC).isoformat()
                        if fault == "stale" or (
                            fault == "stale_after_read"
                            and db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
                        ):
                            state["observed_at"] = (
                                datetime.now(UTC) - timedelta(hours=1)
                            ).isoformat()
                        method = request["method"]
                        if method == "describe":
                            response["capabilities"] = [
                                card.to_dict() for card in world.capability_cards
                            ]
                        elif method == "snapshot":
                            response["state"] = state
                        elif method in {"invoke", "reconcile", "cancel"}:
                            operation = request["operation_id"]
                            if not isinstance(operation, str) or len(operation) != 64:
                                raise ValueError("invalid operation identity")
                            response["operation_id"] = operation
                            receipt = db.execute(
                                "SELECT fingerprint,result,status FROM receipts WHERE id=?",
                                (operation,),
                            ).fetchone()
                            if method in {"reconcile", "cancel"}:
                                if method == "cancel" and receipt is None:
                                    # This single-threaded device serializes cancellation
                                    # with dispatch and persists its fence before ACK.
                                    with db:
                                        db.execute(
                                            "INSERT INTO receipts(id,fingerprint,result,status) "
                                            "VALUES (?,NULL,'null','failed')",
                                            (operation,),
                                        )
                                    receipt = (None, "null", "failed")
                                response.update(
                                    status="unknown" if receipt is None else receipt[2],
                                    result=None if receipt is None else json.loads(receipt[1]),
                                )
                            elif receipt is not None and receipt[2] == "failed":
                                # Even a late arrival after cancellation cannot execute.
                                response.update(status="failed", result=None)
                            else:
                                if fault == "disconnect":
                                    continue
                                if fault == "delay":
                                    time.sleep(min(0.6, max(0, deadline - time.monotonic()) + 0.02))
                                if time.monotonic() >= deadline:
                                    continue
                                fingerprint = _invocation_fingerprint(
                                    request["capability_id"], request["arguments"]
                                )
                                if receipt is not None:
                                    if receipt[0] != fingerprint:
                                        raise ValueError("operation identity conflict")
                                    value = json.loads(receipt[1])
                                else:
                                    value = world.invoke(
                                        request["capability_id"], request["arguments"]
                                    )
                                    with db:
                                        for key, item in world.snapshot().values.items():
                                            db.execute(
                                                "UPDATE values_state SET value=? WHERE key=?",
                                                (json.dumps(item), key),
                                            )
                                        db.execute(
                                            "INSERT INTO receipts(id,fingerprint,result) VALUES(?,?,?)",
                                            (operation, fingerprint, json.dumps(value)),
                                        )
                                response.update(status="succeeded", result=value)
                                if fault == "lost_ack":
                                    continue
                                if fault == "malformed":
                                    conn.sendall(b"invalid\n")
                                    continue
                        else:
                            raise ValueError("unknown device method")
                        conn.settimeout(max(0.001, deadline - time.monotonic()))
                        conn.sendall(json.dumps(response, allow_nan=False).encode() + b"\n")
                    except (OSError, ValueError, KeyError, TypeError, CapabilityExecutionError):
                        # No acknowledgement is safer than claiming failure after a possible write.
                        continue
        finally:
            path.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Reference device emulator; no physical hardware")
    parser.add_argument("--socket", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument(
        "--fault",
        choices=(
            "none",
            "delay",
            "disconnect",
            "lost_ack",
            "malformed",
            "stale",
            "stale_after_read",
        ),
        default="none",
    )
    args = parser.parse_args(argv)

    def announce(device_id):
        print(
            f"READY: software emulator {device_id}\n"
            f"Socket: {args.socket}\n"
            "Waiting for requests. This terminal stays running; silence means idle.\n"
            "Use another terminal for the client, or use 'run --emulator-dir' for one-terminal operation.\n"
            "Ctrl+C stops the emulator; its database is preserved.",
            file=sys.stderr,
            flush=True,
        )

    try:
        serve(args.socket, args.database, fault=args.fault, on_ready=announce)
    except KeyboardInterrupt:
        print("Emulator stopped. Database and receipts preserved.", file=sys.stderr, flush=True)
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"Emulator could not start or continue: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
