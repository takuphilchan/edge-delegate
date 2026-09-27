import pytest

from edge_delegate.contracts import PlanIR
from edge_delegate.data import build_record_world, validate_records
from edge_delegate.data.tasks import generate_task_records, write_task_dataset
from edge_delegate.evaluation import EvaluationRunner
from edge_delegate.planner import StaticPlanner


@pytest.fixture(scope="module")
def records():
    return generate_task_records()


def test_v1_contains_real_stale_negative_cases_and_valid_gold(records):
    assert len(records) == 4000
    validate_records(records)
    stale = [record for record in records if record["expected_outcome"] == "invalid_plan"]
    assert stale
    planner = StaticPlanner({r["record_id"]: PlanIR.from_dict(r["expected_plan"]) for r in records})
    report = EvaluationRunner(planner, execution_harness=build_record_world).evaluate(records)
    assert report["metrics"]["task_success_rate"] == 1


def test_dataset_is_frozen_and_all_sources_stay_in_one_split(tmp_path):
    import json

    manifest = write_task_dataset(tmp_path)
    assert manifest["split_counts"] == {
        "train": 2800,
        "validation": 600,
        "test": 600,
        "safety": 200,
    }
    assert manifest["independent_review_complete"] is False
    groups = []
    for name in ("train", "validation", "test", "safety"):
        members = [
            json.loads(line) for line in (tmp_path / f"{name}.jsonl").read_text().splitlines()
        ]
        groups.append({member["metadata"]["scenario_group"] for member in members})
    for index, group in enumerate(groups):
        assert not any(group & other for other in groups[index + 1 :])
    with pytest.raises(ValueError, match="overwritten"):
        write_task_dataset(tmp_path)
