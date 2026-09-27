import json
from copy import deepcopy
from pathlib import Path

import pytest

from edge_delegate.contracts import PlanIR
from edge_delegate.data import build_record_world, validate_records
from edge_delegate.data.review import validate_review_dataset
from edge_delegate.evaluation import EvaluationRunner
from edge_delegate.planner import StaticPlanner
from edge_delegate_lab.cli import main as lab_main
from edge_delegate_lab.pilot import build_pilot, render_review, write_pilot

SOURCE = Path(__file__).parents[2] / "data/fixtures/pilot-v2/source.json"


def source():
    return json.loads(SOURCE.read_text(encoding="utf-8"))


def test_pilot_is_reproducible_exposed_and_pending():
    first = build_pilot(source())
    assert first == build_pilot(source())
    splits, manifest, report = first
    assert len(splits["train"]) == 80
    assert not any(splits[name] for name in ("validation", "test", "safety"))
    assert report["accepted_count"] == 0
    assert report["training_eligible"] is False
    assert manifest["policy_approved"] is False
    assert len(manifest["sources"]) == 16
    assert all(s["exposure"] == "development" for s in manifest["sources"].values())
    assert all(r["metadata"]["review"]["status"] == "pending" for r in splits["train"])
    assert all("reviewer" not in r["metadata"]["review"] for r in splits["train"])
    assert set(report["coverage"]["train"]["categories"]) == {
        "supported",
        "clarify",
        "deny",
        "restricted",
        "adversarial",
        "challenge",
    }
    with pytest.raises(ValueError, match="accepted review"):
        validate_review_dataset(splits, manifest)
    with pytest.raises(ValueError, match="unsupported dataset record version"):
        validate_records(splits["train"])


def test_assembly_does_not_ask_compiler_or_execution_for_labels(monkeypatch):
    def prohibited(*args, **kwargs):
        raise AssertionError("system under evaluation cannot author its own labels")

    monkeypatch.setattr("edge_delegate.planner.tasks.TaskCatalog.compile", prohibited)
    monkeypatch.setattr("edge_delegate.runtime.Coordinator.handle", prohibited)
    monkeypatch.setattr("edge_delegate.runtime.Executor.execute", prohibited)
    assert build_pilot(source())[2]["record_count"] == 80


def test_independent_gold_expectations_agree_with_simulator_without_certifying_labels():
    records = build_pilot(source())[0]["train"]
    planner = StaticPlanner({r["record_id"]: PlanIR.from_dict(r["expected_plan"]) for r in records})
    report = EvaluationRunner(planner, execution_harness=build_record_world).evaluate(records)
    assert report["case_count"] == 80
    assert report["metrics"]["task_success_rate"] == 1
    assert report["metrics"]["forbidden_invocation_count"] == 0


def test_readable_review_does_not_reveal_proposed_labels_or_rationale():
    records = build_pilot(source())[0]["train"]
    blind = render_review(records)
    answers = render_review(records, answers=True)
    assert blind.count("## pilot-") == answers.count("## pilot-") == 80
    assert "Intended task and parameters: ______" in blind
    assert "Proposed task:" not in blind
    assert "Expected runtime status:" not in blind
    assert records[0]["metadata"]["review"]["rationale"] not in blind
    assert all(r["request"]["text"] in blind for r in records)


def test_simulator_uses_declared_draft_state_and_rejects_unknown_versions():
    record = build_pilot(source())[0]["train"][0]
    assert dict(build_record_world(record).snapshot().values) == record["state"]["values"]
    record["schema_version"] = "unknown.v99"
    with pytest.raises(ValueError, match="unsupported simulator"):
        build_record_world(record)


def test_context_counterfactuals_keep_intent_and_literal_is_not_sensor_value():
    records = build_pilot(source())[0]["train"]
    pair = [r for r in records if r["request"]["text"] == "Display 15."]
    assert len(pair) == 2
    assert pair[0]["expected_task"] == pair[1]["expected_task"]
    assert {r["expected_outcome"] for r in pair} == {"executed", "denied"}
    literals = [r for r in records if r["expected_task"]["task"] == "display_number"]
    assert all(
        r["expected_task"]["parameters"]["value"]
        != r["state"]["values"]["environment.temperature_c"]
        for r in literals
    )
    assert any(
        r["expected_task"]["parameters"]["value"] == r["state"]["values"]["display.last_value"]
        for r in literals
    )


def test_written_workspace_checks_and_rebuild_never_overwrites_review(tmp_path, capsys):
    output = tmp_path / "pilot"
    assert write_pilot(SOURCE, output)["record_count"] == 80
    assert lab_main(["review-data", "--directory", str(output), "--allow-pending"]) == 0
    assert json.loads(capsys.readouterr().out)["accepted_count"] == 0
    assert lab_main(["review-data", "--directory", str(output)]) == 1
    assert "accepted review" in capsys.readouterr().err
    review = output / "REVIEW.md"
    review.write_text("Reviewer notes must survive.", encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_pilot(SOURCE, output)
    assert review.read_text(encoding="utf-8") == "Reviewer notes must survive."


@pytest.mark.parametrize("mutation", ["fresh", "missing_case", "duplicate_family", "bad_context"])
def test_invalid_pilot_source_is_rejected(mutation):
    data = deepcopy(source())
    if mutation == "fresh":
        data["exposure"] = "fresh"
    elif mutation == "missing_case":
        data["groups"][0]["cases"].pop()
    elif mutation == "duplicate_family":
        data["groups"][1]["family"] = data["groups"][0]["family"]
    else:
        data["groups"][0]["cases"][0]["context"] = "invented"
    with pytest.raises(ValueError):
        build_pilot(data)
