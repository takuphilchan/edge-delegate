"""Dataset provenance, split, CLI, and evaluator integration tests."""

import json

from edge_delegate.cli import main
from edge_delegate.contracts import PlanIR
from edge_delegate.data import generate_records, split_records, validate_records, write_dataset
from edge_delegate.evaluation import EvaluationRunner
from edge_delegate.planner import StaticPlanner


def test_generated_records_are_executable_and_fingerprinted() -> None:
    records = generate_records()
    assert len(records) == 36
    validate_records(records)
    assert {record["expected_plan"]["route"] for record in records} == {
        "local",
        "hybrid",
        "external",
        "clarify",
        "defer",
        "deny",
    }


def test_split_keeps_paraphrases_together_and_isolates_safety() -> None:
    records = generate_records()
    splits = split_records(records, seed=17)
    memberships: dict[str, set[str]] = {}
    for split, members in splits.items():
        for record in members:
            template = record["metadata"]["template_id"]
            memberships.setdefault(template, set()).add(split)
    assert all(len(names) == 1 for names in memberships.values())
    assert {record["metadata"]["template_id"] for record in splits["safety"]} == {
        "disable-alarm-no-approval",
        "prompt-injection",
    }
    assert all(splits[name] for name in ("train", "validation", "test", "safety"))


def test_gold_evaluator_self_check_is_perfect() -> None:
    records = generate_records()
    plans = {
        str(record["record_id"]): PlanIR.from_dict(record["expected_plan"]) for record in records
    }
    report = EvaluationRunner(StaticPlanner(plans)).evaluate(records)
    metrics = report["metrics"]
    assert metrics["parse_valid_rate"] == 1.0
    assert metrics["request_id_accuracy"] == 1.0
    assert metrics["static_valid_rate"] == 1.0
    assert metrics["route_accuracy"] == 1.0
    assert metrics["exact_plan_accuracy"] == 1.0
    assert metrics["local_execution_success_rate"] == 1.0
    assert metrics["brier_score"] == 0.0


def test_evaluator_rejects_a_plan_bound_to_another_request() -> None:
    record = generate_records()[0]
    expected = PlanIR.from_dict(record["expected_plan"])
    wrong = PlanIR(
        request_id="another-request",
        route=expected.route,
        steps=expected.steps,
        reason_codes=expected.reason_codes,
        confidence=expected.confidence,
        clarification=expected.clarification,
    )
    report = EvaluationRunner(StaticPlanner({str(record["record_id"]): wrong})).evaluate(
        [record]
    )
    assert report["metrics"]["request_id_accuracy"] == 0.0
    assert report["metrics"]["outcome_accuracy"] == 0.0


def test_data_and_evaluation_cli_write_reproducible_artifacts(tmp_path, capsys) -> None:
    dataset_dir = tmp_path / "dataset"
    report_path = tmp_path / "evaluation.json"

    assert main(["generate-data", "--output", str(dataset_dir), "--seed", "17"]) == 0
    manifest = json.loads(capsys.readouterr().out)
    assert manifest["record_count"] == 36
    assert (dataset_dir / "functiongemma-sft-train.jsonl").is_file()

    assert (
        main(
            [
                "evaluate",
                "--dataset",
                str(dataset_dir / "all.jsonl"),
                "--planner",
                "gold",
                "--output",
                str(report_path),
            ]
        )
        == 0
    )
    capsys.readouterr()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["metrics"]["outcome_accuracy"] == 1.0


def test_write_dataset_is_seed_reproducible(tmp_path) -> None:
    first = write_dataset(tmp_path / "first", seed=23)
    second = write_dataset(tmp_path / "second", seed=23)
    assert first == second
