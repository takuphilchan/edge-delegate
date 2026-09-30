"""Run the real host, public-client tutorial and v2 CLI. Keep private evidence."""

import json
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def check(binaries: Path) -> None:
    root = Path(tempfile.mkdtemp(prefix="edge-workspace-service-"))
    directory = root / "service"
    with (root / "host.log").open("w") as log:
        host = subprocess.Popen(
            [
                str(binaries / "edge-delegate-host"),
                "serve-workspace",
                "--directory",
                str(directory),
            ],
            stdout=log,
            stderr=log,
        )
        try:
            deadline = time.monotonic() + 10
            while not (directory / "execution-v2.sock").exists():
                if host.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError(f"host failed; inspect private log in {root}")
                time.sleep(0.02)
            for request_id, answer in (
                ("declined", ""),
                ("accepted", "create\n"),
                ("accepted", ""),
            ):
                result = subprocess.run(
                    [
                        str(binaries / "examples/workspace_client"),
                        str(directory),
                        str(directory / "owner-v2.json"),
                        request_id,
                    ],
                    input=answer,
                    text=True,
                    capture_output=True,
                    check=True,
                    timeout=15,
                )
                assert (
                    "Declined; no note created." if request_id == "declined" else "Readback:"
                ) in result.stdout
            # CLI inspection uses a real command file but never prints a credential.
            command = root / "inspect.json"
            command.write_text(
                json.dumps(
                    {"method": "inspect", "principal": "sdk-example", "request_id": "accepted"}
                ),
                encoding="utf-8",
            )
            response = subprocess.run(
                [
                    str(binaries / "edgectl"),
                    "workspace-service",
                    "--directory",
                    str(directory),
                    "--credential",
                    str(directory / "owner-v2.json"),
                    "--command",
                    str(command),
                ],
                text=True,
                capture_output=True,
                check=True,
                timeout=10,
            )
            assert json.loads(response.stdout)["record"]["state"] == "succeeded"
            with sqlite3.connect(
                f"file:{directory / 'notes/notes.sqlite'}?mode=ro", uri=True
            ) as db:
                assert db.execute("SELECT count(*) FROM notes").fetchone() == (1,)
            print(
                "PASS: explicit approval, readback, decline, same-ID retry and v2 CLI inspection."
            )
            print(f"Private state retained at {root}; do not upload credentials or journals.")
        finally:
            host.terminate()
            try:
                host.wait(timeout=5)
            except subprocess.TimeoutExpired:
                host.kill()
                host.wait(timeout=5)


if __name__ == "__main__":
    check(Path(sys.argv[1]).resolve())
