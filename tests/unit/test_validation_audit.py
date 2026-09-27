import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from edge_delegate.contracts import PlanIR
from edge_delegate.data import build_record_world, dataset_fingerprint, generate_records
from edge_delegate.evaluation import EvaluationRunner
from edge_delegate.planner import PlannerOutputError, StaticPlanner
from edge_delegate_lab.validation_audit import (
    audit_command,
    compare_modes,
    primary_finding,
    render_audit,
    run_audit,
    validation_records,
)


def model_for(planner):
    return SimpleNamespace(planner=planner, model_info={})


def dataset_at(root):
    records = generate_records()[:2]
    path = root / "validation.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    (root / "manifest.json").write_text(
        json.dumps({"split_sha256": {"validation": dataset_fingerprint(records)}}),
        encoding="utf-8",
    )
    return records, path


def test_only_canonical_validation_is_accepted_before_model_loading(tmp_path):
    records, path = dataset_at(tmp_path)
    assert validation_records(path)[0] == records
    path.write_text(json.dumps(records[0]), encoding="utf-8")
    with pytest.raises(ValueError, match="validation split"):
        validation_records(path)


def test_modes_use_distinct_interfaces_and_expose_arguments_and_effects_without_values():
    record = generate_records()[0]
    gold = PlanIR.from_dict(record["expected_plan"])
    calls = []

    class Planner:
        def plan_many(self, requests, contexts):
            calls.append("batch")
            return [gold]

        def plan(self, request, context):
            calls.append("single")
            return replace(
                gold,
                steps=(*gold.steps[:-1], replace(gold.steps[-1], arguments={"value": 987654321})),
            )

    saved = {}
    report = run_audit(
        model_for(Planner()),
        [record],
        {},
        write=lambda name, value: saved.update({name: value}),
        progress=lambda *args: None,
    )
    assert calls == ["batch", "single"]
    assert report["reference_failure_ids"] == []
    assert report["comparison"]["single_regressions"] == [record["record_id"]]
    finding = report["modes"]["single"]["findings"][0]
    assert finding["primary_finding"] == "argument_or_dependency_mismatch"
    assert finding["tags"] == ["wrong_but_permitted"]
    assert "state:display.last_value" in finding["diagnostics"]["observed_effect_issues"]
    assert "987654321" not in json.dumps(saved)
    assert record["request"]["text"] not in json.dumps(report)
    assert report["independent_review_complete"] is False
    assert "not independent" in render_audit(report)


def test_planner_failure_redacts_messages_but_keeps_type_and_accounting():
    record = generate_records()[0]

    class Broken:
        def plan(self, *args):
            raise PlannerOutputError("secret payload 987654321")

    saved = {}
    report = run_audit(
        model_for(Broken()),
        [record],
        {},
        write=lambda name, value: saved.update({name: value}),
        progress=lambda *args: None,
    )
    assert report["modes"]["single"]["primary_counts"] == {"invalid_decision": 1}
    assert "987654321" not in json.dumps(saved)
    assert "PlannerOutputError" in json.dumps(saved)
    assert report["comparison"]["different_case_count"] == 0


def test_default_evaluation_keeps_legacy_case_shape_and_diagnostics_do_not_change_outcomes():
    records = generate_records()
    planner = StaticPlanner({r["record_id"]: PlanIR.from_dict(r["expected_plan"]) for r in records})
    plain = EvaluationRunner(planner, execution_harness=build_record_world).evaluate(records)
    detailed = EvaluationRunner(
        planner, execution_harness=build_record_world, diagnostics=True
    ).evaluate(records)
    assert all("diagnostics" not in case for case in plain["cases"])
    assert plain["metrics"] == detailed["metrics"]
    assert plain["cases"] == [
        {k: v for k, v in case.items() if k != "diagnostics"} for case in detailed["cases"]
    ]


def test_effects_are_recorded_even_when_expected_status_differs():
    record = next(r for r in generate_records() if r["expected_plan"]["route"] == "deny")
    action = PlanIR.from_dict(generate_records()[0]["expected_plan"])
    action = replace(action, request_id=record["request"]["request_id"])
    result = EvaluationRunner(
        StaticPlanner({action.request_id: action}),
        execution_harness=build_record_world,
        diagnostics=True,
    ).evaluate([record])["cases"][0]
    assert primary_finding(result) == "inappropriate_action_proposal"
    assert result["diagnostics"]["predicted_status"] != result["diagnostics"]["expected_status"]
    assert (
        result["diagnostics"]["validation_codes"] or result["diagnostics"]["observed_effect_issues"]
    )


def test_compare_rejects_mismatched_or_duplicate_records():
    sample = {"dataset_sha256": "same", "cases": [{"record_id": "one", "task_success": True}]}
    with pytest.raises(ValueError, match="different datasets"):
        compare_modes(sample, {**sample, "dataset_sha256": "other"})
    with pytest.raises(ValueError, match="unique case IDs"):
        compare_modes(sample, {**sample, "cases": sample["cases"] * 2})


def test_command_writes_complete_outputs_and_never_overwrites(tmp_path, monkeypatch):
    records, path = dataset_at(tmp_path)
    planner = StaticPlanner({r["record_id"]: PlanIR.from_dict(r["expected_plan"]) for r in records})
    calls = []

    def create(**kwargs):
        calls.append("load")
        return model_for(planner)

    monkeypatch.setattr(
        "edge_delegate.model_plugins.available_model_plugins",
        lambda: SimpleNamespace(get=lambda _: SimpleNamespace(create_diagnostic_session=create)),
    )
    args = dict(
        dataset=path, output=tmp_path / "audit", plugin_id="fixture", artifact=None, settings={}
    )
    assert audit_command(**args) == 0
    assert json.loads((args["output"] / "audit.json").read_text())["complete"] is True
    with pytest.raises(FileExistsError):
        audit_command(**args)
    assert calls == ["load"]


def test_model_initialization_failure_leaves_incomplete_evidence(tmp_path, monkeypatch):
    _, path = dataset_at(tmp_path)

    def fail(**kwargs):
        raise ValueError("do not persist this sensitive message")

    monkeypatch.setattr(
        "edge_delegate.model_plugins.available_model_plugins",
        lambda: SimpleNamespace(get=lambda _: SimpleNamespace(create_diagnostic_session=fail)),
    )
    output = tmp_path / "audit"
    with pytest.raises(ValueError):
        audit_command(dataset=path, output=output, plugin_id="fixture", artifact=None, settings={})
    assert not (output / "audit.json").exists()
    progress = json.loads((output / "progress.json").read_text())
    assert progress["complete"] is False and progress["phase"] == "failed"
    assert "sensitive" not in json.dumps(progress)
