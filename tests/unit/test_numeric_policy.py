import json
import math
from types import SimpleNamespace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from edge_delegate.contracts import PlanningRequest
from edge_delegate.model_plugins.functiongemma_tasks import FunctionGemmaTasksPlugin
from edge_delegate.model_plugins.task_classifier import TaskClassifierPlugin
from edge_delegate.planner import PlannerContext
from edge_delegate.planner.numeric import (
    DECIMAL_NUMERIC_POLICY,
    LEGACY_NUMERIC_POLICY,
    extract_numeric_literal,
    numeric_parameter,
)
from edge_delegate.simulator.examples import local_display
from edge_delegate_lab.simulation import run_simulation
from tests.unit.test_task_plugins import classifier_artifact as classifier_artifact

VALID = [
    ("Display -1000.", -1000),
    ("Display +1000.00!", 1000),
    ("Display -.5.", -0.5),
    ("Display +.25?", 0.25),
    ("Display -0.00.", 0),
    ("Display 00012.50.", 12.5),
    ("Display 12. Please.", 12),
    ("Put -3.50 on the local screen.", -3.5),
]
INVALID = [
    "Display twelve.",
    "Display 1001.",
    "Display -1000.01.",
    "Display 1.234.",
    "Display 1.000.",
    "Display 1000.001.",
    "Display 1e2.",
    "Display 1E-2.",
    "Display 1,000.",
    "Display 1 000.",
    "Display 12 or 13.",
    "Display 12, not 13.",
    "Display 1.2.3.",
    "Display --3.",
    "Display +-3.",
    "Display - 3.",
    "Display . 5.",
    "Display point 5.",
    "Display dot 5.",
    "Display 3+4.",
    "Display 6 plus eight.",
    "Display 3 * two.",
    "Display two or 12.",
    "Display 12/2.",
    "Display 12%.",
    "Display 12.foo.",
    "Display sensor12.",
    "Display \uff11\uff12.",
    "Display \u0661\u0662.",
    "Display \u22123.",
    "Display 12°C.",
    "Display NaN.",
    "Display Infinity.",
    "Display 12..",
    "Display .",
    "Display a value.",
    "Display 12, please.",
    "Display $12.",
]


@pytest.mark.parametrize("text,value", VALID)
def test_decimal_policy_accepts_exact_literals(text, value):
    result = extract_numeric_literal(text, policy=DECIMAL_NUMERIC_POLICY)
    assert result.value == value
    assert result.reason is None
    assert result.policy == DECIMAL_NUMERIC_POLICY
    if value == 0:
        assert math.copysign(1, result.value) == 1


@pytest.mark.parametrize("text", INVALID)
def test_decimal_policy_never_salvages_unsupported_literals(text):
    result = extract_numeric_literal(text, policy=DECIMAL_NUMERIC_POLICY)
    assert result.value is None
    assert result.reason


@given(st.integers(min_value=-100000, max_value=100000))
def test_all_cents_in_range_round_trip_without_rounding(cents):
    sign = "-" if cents < 0 else "+"
    literal = f"{sign}{abs(cents) // 100}.{abs(cents) % 100:02d}"
    assert numeric_parameter(f"Display {literal}.", policy=DECIMAL_NUMERIC_POLICY) == cents / 100


def test_legacy_defaults_are_unchanged():
    for text, value in [("Display 1001.", 1001), ("Display 1.234.", 1.234)]:
        assert (
            numeric_parameter(text)
            == numeric_parameter(text, policy=LEGACY_NUMERIC_POLICY)
            == value
        )
    assert math.copysign(1, numeric_parameter("Display -0.")) == -1
    assert (
        extract_numeric_literal("x" * 8001, policy=DECIMAL_NUMERIC_POLICY).reason == "invalid_text"
    )


@pytest.fixture(params=["functiongemma-tasks", "task-classifier"])
def session_factory(request, monkeypatch, classifier_artifact):
    def create(*, settings=None, model_value=12, task="display_number"):
        settings = {"numeric_policy": DECIMAL_NUMERIC_POLICY} if settings is None else settings
        if request.param == "task-classifier":
            return TaskClassifierPlugin().create_diagnostic_session(
                artifact_path=str(classifier_artifact),
                settings=settings,
            )
        output = (
            "<start_function_call>call:select_task{decision_json:<escape>"
            + json.dumps(
                {
                    "task": task,
                    "parameters": {"value": model_value} if task == "display_number" else {},
                }
            )
            + "<escape>}<end_function_call>"
        )
        backend = SimpleNamespace(
            generate=lambda *a, **k: output,
            generate_batch=lambda messages, *a, **k: [output] * len(messages),
            model_info=SimpleNamespace(to_dict=lambda: {}),
            last_generation=SimpleNamespace(to_dict=lambda **k: {}),
        )

        def backend_factory(self, **kwargs):
            assert "numeric_policy" not in kwargs["settings"]
            return backend, 8, 96

        monkeypatch.setattr(FunctionGemmaTasksPlugin, "_create_backend", backend_factory)
        return FunctionGemmaTasksPlugin().create_diagnostic_session(
            artifact_path="fixture", settings=settings
        )

    return create


@pytest.mark.parametrize("text", INVALID)
def test_both_plugins_clarify_invalid_numbers_without_invocations(session_factory, text):
    session = session_factory()
    result = run_simulation(session.planner, PlanningRequest("numeric", text))
    assert result["status"] == "clarification_required"
    assert result["invocation_count"] == 0
    assert result["state_before"] == result["state_after"]
    assert session.model_info["numeric_policy"] == DECIMAL_NUMERIC_POLICY
    assert session.last_generation(include_raw_output=False)["numeric_check"] not in {
        None,
        "accepted",
    }


@pytest.mark.parametrize("text,value", VALID)
def test_both_plugins_display_valid_literals_only(session_factory, text, value):
    session = session_factory(model_value=value)
    result = run_simulation(session.planner, PlanningRequest("numeric", text))
    assert result["status"] == "executed"
    assert result["invocation_count"] == 1
    assert result["state_after"]["display.last_value"] == value
    if value == 0:
        assert math.copysign(1, result["state_after"]["display.last_value"]) == 1


@pytest.mark.parametrize("settings", [{}, {"numeric_policy": LEGACY_NUMERIC_POLICY}])
def test_old_plugin_deployments_keep_range_and_precision(session_factory, settings):
    for text, value in [("Display 1001.", 1001), ("Display 1.234.", 1.234)]:
        session = session_factory(settings=settings, model_value=value)
        result = run_simulation(session.planner, PlanningRequest("legacy", text))
        assert result["status"] == "executed"
        assert result["state_after"]["display.last_value"] == value
        assert session.model_info["numeric_policy"] == LEGACY_NUMERIC_POLICY


@pytest.mark.parametrize("policy", ["decimal.v2", "", None, True, {}])
def test_unknown_policy_fails_before_model_or_artifact_load(policy):
    for plugin in (FunctionGemmaTasksPlugin(), TaskClassifierPlugin()):
        with pytest.raises(ValueError, match="numeric_policy"):
            plugin.create_diagnostic_session(
                artifact_path="does-not-exist", settings={"numeric_policy": policy}
            )


def test_batch_and_single_use_same_policy_and_context(session_factory):
    session = session_factory()
    world, policy = local_display()
    context = PlannerContext(world.capability_cards, world.snapshot(), policy)
    requests = [
        PlanningRequest(str(index), text)
        for index, text in enumerate(["Display 12.", "Display 1001.", "Display 1.234."])
    ]
    batch = session.planner.plan_many(requests, [context] * len(requests))
    assert batch == [session.planner.plan(request, context) for request in requests]
    assert [plan.route.value for plan in batch] == ["local", "clarify", "clarify"]


def test_functiongemma_never_repairs_wrong_values_or_wrong_tasks(monkeypatch):
    for decision in (
        {"task": "display_number", "parameters": {"value": 13}},
        {"task": "display_number", "parameters": {"value": True}},
        {"task": "read_temperature", "parameters": {"value": 12}},
    ):
        output = (
            "<start_function_call>call:select_task{decision_json:<escape>"
            + json.dumps(decision)
            + "<escape>}<end_function_call>"
        )
        backend = SimpleNamespace(generate=lambda *a, output=output, **k: output)
        monkeypatch.setattr(
            FunctionGemmaTasksPlugin,
            "_create_backend",
            lambda *a, backend=backend, **k: (backend, 8, 96),
        )
        planner = FunctionGemmaTasksPlugin().create_planner(
            artifact_path=None, settings={"numeric_policy": DECIMAL_NUMERIC_POLICY}
        )
        text = "Display 1." if decision["parameters"]["value"] is True else "Display 12."
        result = run_simulation(planner, PlanningRequest("mismatch", text))
        assert result["status"] == "invalid_plan"
        assert result["invocation_count"] == 0
        assert result["state_before"] == result["state_after"]
