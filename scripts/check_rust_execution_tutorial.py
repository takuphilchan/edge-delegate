"""Exercise the maintained tutorial's actual command blocks with an isolated software device."""

from __future__ import annotations

import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TUTORIAL = ROOT / "docs/tutorials/rust-execution-service.md"


def check(host: Path, cli: Path, evidence: Path) -> None:
    # Only trusted, repository-owned documentation is executed. No downloaded/user text.
    evidence.mkdir(mode=0o700)
    service = evidence / "edge-delegate-service"
    text = TUTORIAL.read_text(encoding="utf-8")

    def blocks(step: int) -> list[str]:
        section = re.split(rf"^## {step}\. .*\n", text, maxsplit=1, flags=re.MULTILINE)[1]
        section = re.split(r"^## ", section, maxsplit=1, flags=re.MULTILINE)[0]
        commands = re.findall(r"```bash\n(.*?)\n```", section, re.DOTALL)
        assert commands, f"tutorial step {step} has no bash blocks"
        return commands

    def command(source: str) -> str:
        return source.replace("$HOME/.local/state", str(evidence)).replace(
            "cargo run --locked -p edge-cli --", shlex.quote(str(cli))
        )

    env = {**os.environ, "EDGE_SERVICE_DIR": str(service)}

    def run(source: str) -> str:
        return subprocess.run(
            ["bash", "-eu", "-c", "umask 077\n" + command(source)],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout

    # The caller builds the binaries. Extract the tutorial's host arguments verbatim.
    host_command = blocks(1)[0].split("cargo run --locked -p edge-host -- ", 1)[1]
    host_args = shlex.split(command(host_command).replace("\\\n", " "))

    def stop(process: subprocess.Popen) -> None:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def start() -> subprocess.Popen:
        log = evidence / "host.log"
        with log.open("wb") as stream:
            process = subprocess.Popen([str(host), *host_args], stdout=stream, stderr=stream)
        try:
            until = time.monotonic() + 10
            while "READY:" not in log.read_text(encoding="utf-8"):
                if process.poll() is not None or time.monotonic() >= until:
                    raise RuntimeError("tutorial host did not become ready; inspect host.log")
                time.sleep(0.02)
        except BaseException:
            stop(process)
            raise
        return process

    process = start()
    try:
        enrollment = json.loads(run(blocks(2)[0]))
        assert enrollment["enrollment_saved"] is True
        for source in blocks(3):
            run(source)
        preview = json.loads((service / "preview.json").read_text())
        assert preview["kind"] == "preview"
        approval = json.loads(run(blocks(4)[0]))
        assert approval["kind"] == "confirmed"
        assert approval["plan_sha256"] == preview["plan_sha256"]
        submission = json.loads(run(blocks(5)[0]))
        assert submission["admission_durable"] is True
        until = time.monotonic() + 5
        while True:
            status = json.loads(run(blocks(6)[0]))
            if status["operation"] and status["operation"]["state"] == "succeeded":
                break
            if time.monotonic() >= until:
                raise TimeoutError("tutorial operation did not complete")
            time.sleep(0.02)
        stop(process)
        process = start()
        restored = json.loads(run(blocks(6)[0]))
        assert restored["operation"] == status["operation"]
        with sqlite3.connect(f"file:{service / 'authority/device.sqlite'}?mode=ro", uri=True) as db:
            assert db.execute("SELECT volume,writes FROM state").fetchone() == (40, 1)
        print(
            "PASS: tutorial command blocks; separate approval, one software write, restart status."
        )
        print(f"Private tutorial evidence retained at {evidence}; do not upload credentials.")
    finally:
        stop(process)


def check_sdk_example(host: Path, example: Path, evidence: Path) -> None:
    """Confirm that the public onboarding example changes nothing without explicit input."""
    evidence.mkdir(mode=0o700)
    directory = evidence / "service"
    log = evidence / "host.log"
    with log.open("wb") as output:
        process = subprocess.Popen(
            [str(host), "serve-software", "--directory", str(directory)],
            stdout=output,
            stderr=subprocess.STDOUT,
        )
    try:
        until = time.monotonic() + 10
        while "READY:" not in log.read_text(encoding="utf-8"):
            if process.poll() is not None or time.monotonic() >= until:
                raise RuntimeError("SDK quickstart host did not become ready")
            time.sleep(0.02)
        for answer, expected_writes in (
            ("", 0),
            ("\n", 0),
            ("approve extra\n", 0),
            ("approve\n", 1),
        ):
            result = subprocess.run(
                [str(example), str(directory)],
                input=answer,
                text=True,
                capture_output=True,
                check=True,
                timeout=15,
            )
            assert "Preview (no action executed):" in result.stdout
            expected = (
                "Succeeded: simulated output is 40%; receipt recorded."
                if expected_writes
                else ("Not submitted. No device action was requested.")
            )
            assert expected in result.stdout
            with sqlite3.connect(
                f"file:{directory / 'authority/device.sqlite'}?mode=ro", uri=True
            ) as db:
                assert db.execute("SELECT writes FROM state").fetchone() == (expected_writes,)
        print(
            "PASS: SDK quickstart; EOF/decline/invalid confirmation do not write; explicit approval writes once."
        )
        print(f"Private quickstart state retained at {evidence}; do not share credentials.")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    host, cli, evidence, *examples = (Path(arg).resolve() for arg in sys.argv[1:])
    check(host, cli, evidence)
    if examples:
        check_sdk_example(host, examples[0], evidence.parent / "sdk-quickstart")
