"""Exercise the real owner console with explicit software fixture confirmation.

No independent human review is claimed. Invoked by test-rust-supervision.sh.
"""

from __future__ import annotations

import json
import os
import selectors
import sqlite3
import subprocess
import sys
import time
from pathlib import Path


def check(binary: Path, directory: Path) -> None:
    if directory.exists():
        raise ValueError("console diagnostic requires a new evidence directory")
    process = subprocess.Popen(
        [str(binary), "software-session", "--directory", str(directory)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert process.stdin is not None and process.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)

    def prompt(command: str | None = None) -> str:
        if command is not None:
            process.stdin.write((command + "\n").encode())
            process.stdin.flush()
        data = bytearray()
        deadline = time.monotonic() + 8
        while not data.endswith(b"software> "):
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise TimeoutError("console did not return to its prompt")
            chunk = os.read(process.stdout.fileno(), 4096)
            if not chunk:
                raise RuntimeError("console exited before completing the diagnostic")
            data.extend(chunk)
            if len(data) > 65536:
                raise ValueError("console output exceeded diagnostic limit")
        return data.removesuffix(b"software> ").decode().strip()

    try:
        assert "SOFTWARE" in prompt()
        assert "preview_required" in prompt("execute")
        preview = json.loads(prompt("preview 40"))
        assert preview["execution_attempted"] is False
        assert "explicit_approval_required" in prompt("execute")
        assert "approval_fingerprint_mismatch" in prompt("approve " + "0" * 64)
        assert "Approved exact preview" in prompt("approve " + preview["plan_sha256"])
        outcome = json.loads(prompt("execute"))
        assert outcome["state"] == "succeeded"
        replay = json.loads(prompt("execute"))
        assert replay["operation_id"] == outcome["operation_id"]
        assert json.loads(prompt("status " + outcome["request_id"])) == outcome
        next_preview = json.loads(prompt("preview 50"))
        assert prompt("cancel " + next_preview["plan"]["request_id"]) == "null"
        assert "preview_required" in prompt("execute")
        process.stdin.write(b"quit\n")
        process.stdin.flush()
        assert process.wait(timeout=5) == 0
        with sqlite3.connect(directory / "device.sqlite") as connection:
            assert connection.execute("SELECT volume,writes FROM state").fetchone() == (40, 1)
        print("PASS: real console preview/confirmation/execute/status/replay/cancel; one software write.")
    finally:
        selector.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        process.stdin.close()
        process.stdout.close()


if __name__ == "__main__":
    check(Path(sys.argv[1]), Path(sys.argv[2]))
