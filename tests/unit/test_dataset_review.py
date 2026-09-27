import json
from copy import deepcopy
from dataclasses import replace

import pytest

from edge_delegate.contracts import PlanningRequest
from edge_delegate.data import validate_record
from edge_delegate.data.fingerprint import content_fingerprint, dataset_fingerprint
from edge_delegate.data.generate import FIXED_NOW
from edge_delegate.data.reference_oracle import (
    DISPLAY,
    ORACLE_VERSION,
    READ,
    check_reference_plan,
    reference_effects,
)
from edge_delegate.data.review import (
    REVIEW_RECORD_VERSION,
    SPLITS,
    review_payload_fingerprint,
    validate_review_dataset,
    validate_review_record,
)
from edge_delegate.evaluation.outcomes import check_effects
from edge_delegate.planner import PlannerContext
from edge_delegate.planner.tasks import TaskDecision, reference_catalog
from edge_delegate.simulator import ManualClock
from edge_delegate.simulator.examples import local_display
from edge_delegate_lab.cli import main


def sign(record, *, approve=False):
    if approve:
        record["metadata"]["review"]["reviewed_payload_sha256"] = review_payload_fingerprint(record)
    record.pop("content_sha256", None)
    record["content_sha256"] = content_fingerprint(record)
    return record


def sample(task="display_number", *, split="train", accepted=True, restricted=False):
    """Software fixture only, not a claim that an actual human reviewed data."""
    identifier = f"{split}-{task}" + ("-restricted" if restricted else "")
    world, policy = local_display(clock=ManualClock(FIXED_NOW))
    if restricted:
        policy = replace(policy, granted_permissions=frozenset())
    world.write("display.last_value", -8)
    state = world.snapshot()
    decision = TaskDecision(task, {"value": 12} if task == "display_number" else {})
    request = PlanningRequest(identifier, f"Synthetic unit-test fixture: {identifier}")
    plan = reference_catalog().compile(
        decision, request, PlannerContext(world.capability_cards, state, policy)
    )
    outcome = {"local": "executed", "clarify": "clarification_required", "deny": "denied"}[
        plan.route.value
    ]
    record = {
        "schema_version": REVIEW_RECORD_VERSION,
        "record_id": identifier,
        "request": request.to_dict(),
        "capabilities": [c.to_dict() for c in world.capability_cards],
        "state": state.to_dict(),
        "policy": policy.to_dict(),
        "evaluation_at": FIXED_NOW.isoformat(),
        "expected_task": decision.to_dict(),
        "expected_plan": plan.to_dict(),
        "expected_outcome": outcome,
        "expected_effects": reference_effects(
            decision.to_dict(), state.values, outcome, [READ, DISPLAY]
        ),
        "metadata": {
            "scenario_group": identifier,
            "template_id": identifier,
            "paraphrase_cluster": identifier,
            "scenario_family": task,
            "device_family": "local-display.v1",
            "category": task if task in {"clarify", "deny"} else "supported",
            "catalog_version": "local-display.v1",
            "label_policy": "fixture-test-only.v1",
            "oracle_version": ORACLE_VERSION,
            "provenance": {"source_ids": [identifier], "parent_ids": [], "method": "human"},
            "review": {
                "status": "accepted" if accepted else "pending",
                "author": "test-author",
                "reviewer": "test-reviewer",
                "rationale": "Unit-test fixture, not reviewed user data",
                "author_decision": decision.to_dict(),
                "reviewer_decision": decision.to_dict(),
            },
        },
    }
    if restricted:
        record["metadata"].update(category="restricted", restriction_reason="Missing permissions")
    if split == "safety":
        record["metadata"]["category"] = "adversarial"
    return sign(record, approve=accepted)


def workspace(*, accepted=True):
    tasks = ("read_temperature", "display_number", "show_temperature", "clarify", "deny")
    splits = {
        split: [sample(task, split=split, accepted=accepted) for task in tasks] for split in SPLITS
    }
    for split in ("train", "validation", "test"):
        splits[split].append(
            sample("show_temperature", split=split, accepted=accepted, restricted=True)
        )
    manifest = {
        "schema_version": "edge-dataset-review.v1",
        "catalog": "local-display.v1",
        "oracle": ORACLE_VERSION,
        "label_policy": "fixture-test-only.v1",
        "sources": {
            r["record_id"]: {
                "family": r["record_id"],
                "contributor": "test-author",
                "rights": "test fixture",
                "exposure": "fresh",
            }
            for rows in splits.values()
            for r in rows
        },
    }
    for rows in splits.values():
        for record in rows:
            record["metadata"]["sources_sha256"] = content_fingerprint(
                {
                    source_id: manifest["sources"][source_id]
                    for source_id in record["metadata"]["provenance"]["source_ids"]
                }
            )
            sign(record, approve=accepted)
    return splits, refresh(splits, manifest)


def refresh(splits, manifest):
    manifest["split_sha256"] = {key: dataset_fingerprint(rows) for key, rows in splits.items()}
    manifest["split_counts"] = {key: len(rows) for key, rows in splits.items()}
    return manifest


def test_oracle_values_are_independent_of_runtime_and_inputs_unchanged(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("oracle must not call system under evaluation")

    monkeypatch.setattr("edge_delegate.runtime.Coordinator.handle", forbidden)
    monkeypatch.setattr("edge_delegate.runtime.Executor.execute", forbidden)
    monkeypatch.setattr("edge_delegate.planner.tasks.TaskCatalog.compile", forbidden)
    state = {"environment.temperature_c": 24.5, "display.last_value": -8}
    expected = reference_effects(
        {"task": "display_number", "parameters": {"value": 12}}, state, "executed", [READ, DISPLAY]
    )
    assert expected == {
        "state": {"environment.temperature_c": 24.5, "display.last_value": 12},
        "exact_state": True,
        "final_output": True,
        "invocations": [DISPLAY],
        "forbidden_invocations": [READ],
    }
    read = reference_effects(
        {"task": "read_temperature", "parameters": {}}, state, "executed", [READ, DISPLAY]
    )
    assert read["state"] == state and read["final_output"] == 24.5
    assert read["invocations"] == [READ] and read["forbidden_invocations"] == [DISPLAY]
    show = reference_effects(
        {"task": "show_temperature", "parameters": {}}, state, "executed", [READ, DISPLAY]
    )
    assert show["state"]["display.last_value"] == 24.5
    assert show["invocations"] == [READ, DISPLAY]
    assert state["display.last_value"] == -8


@pytest.mark.parametrize(
    "mutation", ["wrong_value", "extra_state", "extra_read", "extra_write", "reversed", "no_calls"]
)
def test_independent_expectations_detect_mutated_effects(mutation):
    expected = sample("show_temperature")["expected_effects"]
    state, calls = deepcopy(expected["state"]), list(expected["invocations"])
    if mutation == "wrong_value":
        state["display.last_value"] = 12
    elif mutation == "extra_state":
        state["hidden.write"] = True
    elif mutation == "extra_read":
        calls.insert(0, READ)
    elif mutation == "extra_write":
        calls.append(DISPLAY)
    elif mutation == "reversed":
        calls.reverse()
    else:
        calls = []  # Even an already-equal final state is not successful execution.
    assert not check_effects(expected, state=state, final_output=True, invocations=calls)[0]


def test_nonaction_forbids_all_calls_and_numeric_booleans_are_not_values():
    record = sample("deny")
    effects = record["expected_effects"]
    assert set(effects["forbidden_invocations"]) == {READ, DISPLAY}
    assert not check_effects(
        effects, state=effects["state"], final_output=None, invocations=[READ]
    )[0]
    with pytest.raises(ValueError, match="numeric"):
        reference_effects(
            {"task": "display_number", "parameters": {"value": True}},
            record["state"]["values"],
            "executed",
            [DISPLAY],
        )


def test_wrong_expected_plan_cannot_define_its_own_oracle():
    record = sample()
    record["expected_plan"]["steps"][0]["arguments"]["value"] = 99
    with pytest.raises(ValueError, match="arguments"):
        check_reference_plan(record)
    record = sample("show_temperature")
    record["expected_plan"]["steps"].reverse()
    with pytest.raises(ValueError, match="calls"):
        check_reference_plan(record)


def test_accepted_pilot_validates_but_is_not_training_or_release_approval():
    splits, manifest = workspace()
    report = validate_review_dataset(splits, manifest)
    assert report["accepted_count"] == 23
    assert report["qualified"] is False and report["training_eligible"] is False
    with pytest.raises(ValueError, match="unsupported dataset record version"):
        validate_record(splits["train"][0])


def test_pending_review_is_explicit_and_cannot_pass_default_gate():
    splits, manifest = workspace(accepted=False)
    with pytest.raises(ValueError, match="accepted review"):
        validate_review_dataset(splits, manifest)
    assert validate_review_dataset(splits, manifest, require_review=False)["accepted_count"] == 0


@pytest.mark.parametrize(
    "change, message",
    [
        ("self_review", "differ"),
        ("disagreement", "unresolved"),
        ("stale_approval", "bind current"),
        ("bad_effects", "independent fixture"),
        ("missing_provenance", "provenance"),
        ("bad_hash", "fingerprint"),
    ],
)
def test_review_record_rejects_invalid_evidence(change, message):
    record = sample()
    if change == "self_review":
        record["metadata"]["review"]["reviewer"] = "test-author"
    elif change == "disagreement":
        record["metadata"]["review"]["reviewer_decision"] = {"task": "deny", "parameters": {}}
    elif change == "stale_approval":
        record["request"]["text"] = "different intent"
    elif change == "bad_effects":
        record["expected_effects"]["state"]["display.last_value"] = 99
    elif change == "missing_provenance":
        record["metadata"].pop("provenance")
    else:
        record["content_sha256"] = "incorrect"
    if change != "bad_hash":
        sign(record, approve=change == "bad_effects")
    with pytest.raises(ValueError, match=message):
        validate_review_record(record)


@pytest.mark.parametrize(
    "change, message",
    [
        ("leak", "family leakage"),
        ("duplicate_text", "duplicate request"),
        ("exposed", "development-exposed"),
        ("parent", "unresolved parent"),
        ("cycle", "cyclic"),
        ("coverage", "coverage"),
        ("source_changed", "registry changed"),
        ("version", "catalog/oracle"),
        ("hash", "fingerprint"),
    ],
)
def test_dataset_rejects_leakage_and_incomplete_evidence(change, message):
    splits, manifest = workspace()
    record = splits["test"][0]
    if change == "leak":
        record["metadata"]["template_id"] = splits["train"][0]["metadata"]["template_id"]
    elif change == "duplicate_text":
        record["request"]["text"] = splits["train"][0]["request"]["text"]
    elif change == "exposed":
        manifest["sources"][record["record_id"]]["exposure"] = "development"
    elif change == "parent":
        record["metadata"]["provenance"]["parent_ids"] = ["missing"]
    elif change == "cycle":
        record["metadata"]["provenance"]["parent_ids"] = [record["record_id"]]
    elif change == "coverage":
        splits["validation"].pop()
    elif change == "version":
        manifest["oracle"] = "unknown.v99"
    elif change == "source_changed":
        manifest["sources"][record["record_id"]]["rights"] = "changed after review"
    sign(record, approve=True)
    refresh(splits, manifest)
    if change == "hash":
        manifest["split_sha256"]["test"] = "incorrect"
    with pytest.raises(ValueError, match=message):
        validate_review_dataset(splits, manifest)


def test_public_command_checks_workspace_without_loading_models(tmp_path, capsys):
    splits, manifest = workspace(accepted=False)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for split, rows in splits.items():
        (tmp_path / f"{split}.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows), encoding="utf-8"
        )
    assert main(["review-data", "--directory", str(tmp_path)]) == 1
    assert "accepted review" in capsys.readouterr().err
    assert main(["review-data", "--directory", str(tmp_path), "--allow-pending"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["review_mode"] == "draft"
    assert report["training_eligible"] is False


def test_parent_cannot_cross_splits_even_with_distinct_wording():
    splits, manifest = workspace()
    child = splits["test"][0]
    child["metadata"]["provenance"]["parent_ids"] = [splits["train"][0]["record_id"]]
    sign(child, approve=True)
    refresh(splits, manifest)
    with pytest.raises(ValueError, match="parent lineage"):
        validate_review_dataset(splits, manifest)


def test_exact_state_is_explicit_and_legacy_subset_checks_still_work():
    effects = {"state": {"value": 1}, "invocations": []}
    observed = {"value": 1, "other": 2}
    assert check_effects(effects, state=observed, final_output=None, invocations=[])[0]
    effects["exact_state"] = True
    assert not check_effects(effects, state=observed, final_output=None, invocations=[])[0]
    effects["exact_state"] = "true"
    with pytest.raises(ValueError, match="boolean"):
        check_effects(effects, state=observed, final_output=None, invocations=[])
