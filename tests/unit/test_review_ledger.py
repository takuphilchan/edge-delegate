import sqlite3

import pytest

from edge_delegate.data.review_ledger import ReviewLedger
from tests.unit.test_dataset_review import sample


def submission(stage, decision, actor="independent-fixture-reviewer"):
    return {
        "stage": stage,
        "actor": actor,
        "decision": decision,
        "rationale": "Synthetic unit-test evidence only.",
        "blind": stage == "blind",
        "effects_reviewed": stage == "approval",
    }


def test_review_preserves_disagreement_and_exports_copy(tmp_path):
    record = sample(accepted=False)
    ledger = ReviewLedger(tmp_path / "review.db")
    original = {"task": "clarify", "parameters": {}}
    ledger.append(record, submission("blind", original))
    ledger.append(
        record, submission("adjudication", record["expected_task"], actor="fixture-owner")
    )
    ledger.append(record, submission("approval", record["expected_task"]))
    revised = ledger.reviewed_record(record)
    assert revised["metadata"]["review"]["status"] == "accepted"
    assert record["metadata"]["review"]["status"] == "pending"
    assert revised["metadata"]["review"]["history"][0]["decision"] == original
    assert len(ledger.events()) == 3
    with (
        sqlite3.connect(ledger.path) as db,
        pytest.raises(sqlite3.IntegrityError, match="append-only"),
    ):
        db.execute("DELETE FROM review_events")


def test_cannot_approve_without_blind_review_or_impersonate_author(tmp_path):
    record = sample(accepted=False)
    ledger = ReviewLedger(tmp_path / "review.db")
    with pytest.raises(ValueError, match="adjudication"):
        ledger.append(record, submission("approval", record["expected_task"]))
    with pytest.raises(ValueError, match="independent"):
        ledger.append(
            record,
            submission(
                "blind", record["expected_task"], actor=record["metadata"]["review"]["author"]
            ),
        )
    with pytest.raises(ValueError, match="complete"):
        ledger.reviewed_record(record)
    assert ledger.events() == []


def test_incomplete_or_wrong_reviewer_approval_is_rejected(tmp_path):
    record = sample(accepted=False)
    ledger = ReviewLedger(tmp_path / "review.db")
    ledger.append(record, submission("blind", record["expected_task"]))
    ledger.append(record, submission("adjudication", record["expected_task"]))
    with pytest.raises(ValueError, match="original"):
        ledger.append(record, submission("approval", record["expected_task"], actor="someone-else"))
    with pytest.raises(ValueError, match="effects"):
        ledger.append(
            record, {**submission("approval", record["expected_task"]), "effects_reviewed": False}
        )
