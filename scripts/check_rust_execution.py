"""Drive the authenticated service through its public CLI. Software fixtures only."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path


def check(host: Path, cli: Path, evidence: Path) -> None:
    evidence.mkdir(mode=0o700)  # refuse to reuse evidence or credentials
    directory = evidence / "service"
    owner = directory / "owner.json"
    client = evidence / "client.json"
    counter = 0

    def call(credential: Path, command: dict, *, enroll=False, rejected=False):
        nonlocal counter
        counter += 1
        command_file = evidence / f"command-{counter:03d}.json"
        command_file.write_text(json.dumps(command), encoding="utf-8")
        args = [
            str(cli),
            "service",
            "--directory",
            str(directory),
            "--credential",
            str(credential),
            "--command",
            str(command_file),
        ]
        if enroll:
            args += ["--save-credential", str(client)]
        result = subprocess.run(args, capture_output=True, text=True, timeout=15)
        if rejected:
            assert result.returncode != 0 and not result.stdout, "expected rejection"
            return None
        if result.returncode:
            raise RuntimeError(f"CLI rejected {command['method']}: {result.stderr}")
        return json.loads(result.stdout)

    def start():
        log = evidence / f"host-{counter:03d}.log"
        with log.open("wb") as output:
            process = subprocess.Popen(
                [str(host), "serve-software", "--directory", str(directory)],
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        until = time.monotonic() + 10
        try:
            while "READY:" not in log.read_text(encoding="utf-8"):
                if process.poll() is not None or time.monotonic() >= until:
                    raise RuntimeError("execution host did not become ready; inspect its log")
                time.sleep(0.02)
        except BaseException:
            stop(process)
            raise
        return process

    def stop(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    process = start()
    try:
        call(
            owner,
            {"method": "enroll", "principal": "diagnostic-client", "scope": "control"},
            enroll=True,
        )
        proposal = call(client, {"method": "preview_volume", "percent": 40, "budget_ms": 2000})
        identity = {"request_id": proposal["request_id"]}
        approval = {
            "method": "approve",
            "principal": "diagnostic-client",
            **identity,
            "plan_sha256": proposal["plan_sha256"],
        }
        call(client, {"method": "submit", **identity}, rejected=True)
        call(client, approval, rejected=True)
        print("PASS: unapproved execution and client self-approval rejected.")
        call(owner, approval)  # explicit test-program confirmation, not independent human review
        submission = call(client, {"method": "submit", **identity})
        assert submission["admission_durable"] is True
        until = time.monotonic() + 5
        while True:
            result = call(client, {"method": "status", **identity})
            if result["operation"] and result["operation"]["state"] == "succeeded":
                break
            if time.monotonic() >= until:
                raise TimeoutError("software operation did not succeed")
            time.sleep(0.02)
        call(client, {"method": "submit", **identity})
        print("PASS: owner-approved submission, durable status and same-ID retry.")
        stop(process)
        process = start()
        recovered = call(client, {"method": "status", **identity})
        assert recovered["operation"]["state"] == "succeeded"
        assert recovered["operation"]["operation_id"] == result["operation"]["operation_id"]
        call(client, {"method": "submit", **identity}, rejected=True)
        print("PASS: credential and result survive restart; old approval cannot resume execution.")
        call(owner, {"method": "revoke", "principal": "diagnostic-client"})
        call(client, {"method": "capabilities"}, rejected=True)
        stop(process)
        process = start()
        call(client, {"method": "capabilities"}, rejected=True)
        print("PASS: revoked credential remains rejected after restart.")
        db_path = directory / "authority" / "device.sqlite"
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as db:
            volume, writes = db.execute("SELECT volume,writes FROM state").fetchone()
        assert (volume, writes) == (40, 1)
        report = {
            "schema_version": "edge-execution-service-diagnostic.v1",
            "software_only": True,
            "independent_human_review": False,
            "request_id": identity["request_id"],
            "simulator_write_count": writes,
            "simulator_volume": volume,
            "revocation_survived_restart": True,
            "operation": recovered["operation"],
        }
        (evidence / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"PASS: exactly one recorded software write. Report: {evidence / 'report.json'}")
        print(
            "Keep credentials/enrollment private. Journals retained; no native hardware was controlled."
        )
    finally:
        stop(process)


if __name__ == "__main__":
    check(*(Path(arg).resolve() for arg in sys.argv[1:]))
