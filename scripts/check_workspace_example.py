"""Check the trusted adapter example. This is not authenticated service evidence."""

import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


def check(example: Path, root: Path) -> None:
    directory = root / "notes"
    for answer, expected_count in (("", 0), ("create extra\n", 0), ("create\n", 1)):
        result = subprocess.run(
            [str(example), str(directory)],
            input=answer,
            text=True,
            capture_output=True,
            timeout=10,
            check=True,
        )
        assert "No authenticated v2 service" in result.stdout
        if expected_count:
            assert "Created note:" in result.stdout
            assert "A real note stored by the workspace adapter." in result.stdout
        else:
            assert "Declined; no note created." in result.stdout
        with sqlite3.connect(f"file:{directory / 'notes.sqlite'}?mode=ro", uri=True) as db:
            assert db.execute("SELECT count(*) FROM notes").fetchone() == (expected_count,)
            assert db.execute("SELECT count(*) FROM receipts").fetchone() == (
                2 if expected_count else 0,
            )
    print("PASS: notes adapter example declines without writes; creates and reads one note.")
    print(f"Private example state retained: {root}. Not authenticated SDK qualification.")


def check_authority(example: Path, root: Path) -> None:
    for index, answer in enumerate(("", "create extra\n", "create\n")):
        directory = root / f"authority-{index}"
        result = subprocess.run(
            [str(example), str(directory)],
            input=answer,
            text=True,
            capture_output=True,
            timeout=10,
            check=True,
        )
        assert "Trusted owner embedding; no IPC authentication" in result.stdout
        created = index == 2
        assert ("Readback:" if created else "Declined; no note created.") in result.stdout
        with sqlite3.connect(f"file:{directory / 'notes/notes.sqlite'}?mode=ro", uri=True) as db:
            assert db.execute("SELECT count(*) FROM notes").fetchone() == (int(created),)
        with sqlite3.connect(
            f"file:{directory / 'journal/actions.sqlite'}?mode=ro", uri=True
        ) as db:
            states = db.execute("SELECT state FROM action_records").fetchall()
            assert states == (
                [("succeeded",), ("succeeded",)] if created else [("cancelled_before_dispatch",)]
            )
            assert db.execute(
                "SELECT count(*) FROM action_events WHERE kind='approved'"
            ).fetchone() == (int(created),)
    print("PASS: generic authority example requires consent, persists events and reads back notes.")


if __name__ == "__main__":
    root = Path(tempfile.mkdtemp(prefix="edge-notes-check-"))
    check(Path(sys.argv[1]).resolve(), root)
    if len(sys.argv) > 2:
        check_authority(Path(sys.argv[2]).resolve(), root)
