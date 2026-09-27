"""Append-only review history; never invent reviewers, answers or approvals.

SQLite triggers prevent accidental edits. Hash chaining detects accidental tampering;
neither feature authenticates people against an administrator who controls the file.
"""

import json
import sqlite3
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime

from edge_delegate.evaluation.outcomes import _equal
from edge_delegate.planner.tasks import TaskDecision

from .fingerprint import canonical_json, content_fingerprint
from .reference_oracle import TASKS
from .review import review_payload_fingerprint, validate_review_record


class ReviewLedger:
    def __init__(self, path):
        self.path = str(path)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS review_events (
                    sequence INTEGER PRIMARY KEY, payload TEXT NOT NULL, sha256 TEXT NOT NULL UNIQUE
                );
                CREATE TRIGGER IF NOT EXISTS review_no_update BEFORE UPDATE ON review_events
                BEGIN SELECT RAISE(ABORT, 'review history is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS review_no_delete BEFORE DELETE ON review_events
                BEGIN SELECT RAISE(ABORT, 'review history is append-only'); END;
            """)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _events(db):
        events, previous = [], None
        for sequence, payload, digest in db.execute(
            "SELECT sequence,payload,sha256 FROM review_events ORDER BY sequence"
        ):
            event = json.loads(payload)
            if (
                sequence != len(events) + 1
                or event.get("previous_sha256") != previous
                or content_fingerprint(event) != digest
            ):
                raise ValueError("review ledger integrity failure")
            events.append({**event, "sha256": digest})
            previous = digest
        return events

    def events(self):
        with self._connect() as db:
            return self._events(db)

    def append(self, record, submission):
        validate_review_record(record, require_review=False)
        if set(submission) != {
            "stage",
            "actor",
            "decision",
            "rationale",
            "blind",
            "effects_reviewed",
        }:
            raise ValueError("review submission has missing or unknown fields")
        for key in ("actor", "rationale"):
            if not isinstance(submission[key], str) or not submission[key].strip():
                raise ValueError(f"review {key} required")
        if (
            type(submission["blind"]) is not bool
            or type(submission["effects_reviewed"]) is not bool
        ):
            raise ValueError("review declarations must be explicit booleans")
        decision = TaskDecision.from_dict(submission["decision"])
        if decision.task not in TASKS:
            raise ValueError("unknown reviewed task")
        author = record["metadata"]["review"]["author"].strip().casefold()
        actor = submission["actor"].strip().casefold()
        payload_hash = review_payload_fingerprint(record)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            history = self._events(db)
            previous = [
                e
                for e in history
                if e["record_id"] == record["record_id"] and e["payload_sha256"] == payload_hash
            ]
            stage = submission["stage"]
            if stage != "blind" and submission["blind"] is not False:
                raise ValueError("only the original review may declare blind labeling")
            if stage == "blind":
                if previous or actor == author or submission["blind"] is not True:
                    raise ValueError("first blind review requires an independent reviewer")
            elif stage == "adjudication":
                if not previous or previous[-1]["stage"] != "blind":
                    raise ValueError("adjudication must follow original blind review")
            elif stage == "approval":
                if not previous or previous[-1]["stage"] != "adjudication":
                    raise ValueError("approval requires recorded adjudication")
                if actor == author or actor != previous[0]["actor"].strip().casefold():
                    raise ValueError("original independent reviewer must confirm approval")
                if (
                    not _equal(decision.to_dict(), record["expected_task"])
                    or not _equal(previous[-1]["decision"], record["expected_task"])
                    or submission["effects_reviewed"] is not True
                ):
                    raise ValueError(
                        "approval must resolve meaning and confirm complete effects/context"
                    )
            else:
                raise ValueError("unknown review stage")
            event = {
                **submission,
                "schema_version": "edge-review-event.v1",
                "record_id": record["record_id"],
                "payload_sha256": payload_hash,
                "recorded_at": datetime.now(UTC).isoformat(),
                "previous_sha256": history[-1]["sha256"] if history else None,
            }
            digest = content_fingerprint(event)
            db.execute(
                "INSERT INTO review_events VALUES(?,?,?)",
                (len(history) + 1, canonical_json(event), digest),
            )
        return {**event, "sha256": digest}

    def reviewed_record(self, record):
        """Return a NEW reviewed snapshot; never edit source records or auto-adjudicate."""
        validate_review_record(record, require_review=False)
        history = [
            e
            for e in self.events()
            if e["record_id"] == record["record_id"]
            and e["payload_sha256"] == review_payload_fingerprint(record)
        ]
        if len(history) != 3 or [e["stage"] for e in history] != [
            "blind",
            "adjudication",
            "approval",
        ]:
            raise ValueError("complete blind/adjudication/approval history required")
        result = deepcopy(record)
        result["metadata"]["review"].update(
            status="accepted",
            reviewer=history[0]["actor"],
            reviewer_decision=history[-1]["decision"],
            rationale=history[-1]["rationale"],
            reviewed_payload_sha256=review_payload_fingerprint(record),
            history=history,
        )
        result["content_sha256"] = content_fingerprint(
            {k: v for k, v in result.items() if k != "content_sha256"}
        )
        validate_review_record(result)
        return result
