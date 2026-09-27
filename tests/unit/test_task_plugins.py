import json
from types import SimpleNamespace

import pytest

from edge_delegate.contracts import PlanningRequest
from edge_delegate.model_plugins.functiongemma_tasks import parse_decision
from edge_delegate.model_plugins.task_classifier import (
    DIMENSION,
    LABELS,
    TaskClassifierPlugin,
    numeric_parameter,
)
from edge_delegate.planner import PlannerContext, PlannerOutputError
from edge_delegate.simulator.examples import local_display


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Display -3.5", -3.5),
        ("Display -3.5.", -3.5),
        ("Display 12.", 12),
        ("Display .5. Please.", 0.5),
        ("Display 1.2.3", None),
        ("Display 12.foo", None),
        ("display 12 or 13", None),
        ("display 1e3", None),
        ("display 1,000", None),
    ],
)
def test_numeric_extraction_is_conservative(text, expected):
    assert numeric_parameter(text) == expected


def test_compact_parser_rejects_legacy_extra_fields_and_duplicate_keys():
    prefix = "<start_function_call>call:select_task{decision_json:<escape>"
    suffix = "<escape>}<end_function_call>"
    assert (
        parse_decision(prefix + '{"task":"read_temperature","parameters":{}}' + suffix).task
        == "read_temperature"
    )
    for value in (
        '{"task":"deny","task":"read_temperature","parameters":{}}',
        '{"task":"deny","parameters":{},"request_id":"made-up"}',
    ):
        with pytest.raises(PlannerOutputError):
            parse_decision(prefix + value + suffix)
    with pytest.raises(PlannerOutputError):
        parse_decision("<start_function_call>call:submit_plan{}<end_function_call>")


@pytest.mark.parametrize("compiled", [True, False])
def test_compact_warmup_prepares_model_only_and_is_optional(compiled):
    from edge_delegate.model_plugins.functiongemma_tasks import TaskDiagnosticSession

    calls = []
    backend = SimpleNamespace(
        model_info=SimpleNamespace(compiled_decode=compiled),
        generate=lambda *a, **k: calls.append((a, k)),
    )
    session = TaskDiagnosticSession(backend, None, 8, 96)
    result = session.warmup()
    assert result["performed"] is compiled
    assert result["device_actions"] == 0
    assert len(calls) == (2 if compiled else 0)
    assert all(call[1]["max_new_tokens"] == 96 for call in calls)


@pytest.fixture
def classifier_artifact(tmp_path):
    import hashlib

    from edge_delegate import __version__
    from edge_delegate.model_plugins.api import MODEL_PLUGIN_API_VERSION
    from edge_delegate.model_plugins.artifact import ModelArtifactManifest
    from edge_delegate.model_plugins.task_classifier import FEATURE_SPEC

    data = {
        "protocol": "bounded-task.v1",
        "labels": list(LABELS),
        "weights": [[0] * DIMENSION for _ in LABELS],
        "bias": [0, 20, 0, 0, 0],
        "threshold": 0.5,
    }
    (tmp_path / "classifier.json").write_text(json.dumps(data))
    (tmp_path / "features.json").write_text(json.dumps(FEATURE_SPEC))
    ModelArtifactManifest(
        artifact_id="test",
        plugin_id="task-classifier",
        plugin_api_version=MODEL_PLUGIN_API_VERSION,
        plugin_package_version=__version__,
        base_model_id="test-model",
        base_model_revision="1",
        plan_protocol_id="bounded-task",
        plan_protocol_version="1",
        plan_schema="plan-ir.v0",
        tokenizer_files={
            "features.json": hashlib.sha256((tmp_path / "features.json").read_bytes()).hexdigest()
        },
        adapter_method="supervised",
        adapter_format="json",
        adapter_files={
            "classifier.json": hashlib.sha256(
                (tmp_path / "classifier.json").read_bytes()
            ).hexdigest()
        },
        train_dataset_sha256="0" * 64,
        validation_dataset_sha256="1" * 64,
        training_recipe_id="test",
        training_recipe_version="1",
        max_context_tokens=8000,
        supported_precisions=("fp32",),
    ).write(tmp_path / "edge-delegate-artifact.json")
    return tmp_path


def test_classifier_session_loads_once_and_compiles(classifier_artifact):
    session = TaskClassifierPlugin().create_diagnostic_session(
        artifact_path=str(classifier_artifact), settings={}
    )
    world, policy = local_display()
    plan = session.planner.plan(
        PlanningRequest("test", "Display 12"),
        PlannerContext(world.capability_cards, world.snapshot(), policy),
    )
    assert plan.steps[0].arguments == {"value": 12.0}
    assert session.last_generation(include_raw_output=False).get("raw_output") is None


def test_compact_plugin_refuses_a_legacy_adapter_without_loading_weights(tmp_path):
    from edge_delegate.model_plugins.functiongemma_tasks import FunctionGemmaTasksPlugin

    with pytest.raises(ValueError, match=r"manifest|edge-delegate-artifact"):
        FunctionGemmaTasksPlugin().create_planner(artifact_path=str(tmp_path), settings={})
