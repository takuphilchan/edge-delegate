"""Tests for the strict FunctionGemma adapter boundary."""

import json

import pytest

from edge_delegate.ir import canonicalize_plan
from edge_delegate.planner import (
    FunctionGemmaPlanner,
    PlannerContext,
    PlannerError,
    ScriptedFunctionGemmaBackend,
    extract_plan_json,
)
from edge_delegate.planner.prompts import FUNCTIONGEMMA_DEVELOPER_MESSAGE


def test_extract_plan_json_accepts_submit_plan_wrapper(demo_plan) -> None:
    plan_json = canonicalize_plan(demo_plan)
    output = (
        "<start_function_call>call:submit_plan{plan_json:<escape>"
        f"{plan_json}"
        "<escape>}<end_function_call>"
    )
    assert extract_plan_json(output) == plan_json


@pytest.mark.parametrize(
    "output",
    [
        "Here is your plan: {}",
        "{}",
        "<start_function_call>call:unknown{}<end_function_call>",
        "```json\n{}\n```",
    ],
)
def test_extract_plan_json_rejects_untrusted_wrappers(output: str) -> None:
    with pytest.raises(PlannerError):
        extract_plan_json(output)


def test_planner_retrieves_cards_and_records_exact_tool_prompt(
    demo_world, demo_policy, demo_request, demo_plan
) -> None:
    plan_json = canonicalize_plan(demo_plan)
    backend = ScriptedFunctionGemmaBackend(
        [
            "<start_function_call>call:submit_plan{plan_json:<escape>"
            f"{plan_json}"
            "<escape>}<end_function_call>"
        ]
    )
    planner = FunctionGemmaPlanner(backend=backend, retrieval_limit=2)
    state = demo_world.snapshot()

    output = planner.plan(
        demo_request,
        PlannerContext(
            capabilities=demo_world.capability_cards,
            state=state,
            policy=demo_policy,
        ),
    )

    assert output == plan_json
    call = backend.calls[0]
    assert call["messages"][0]["content"] == FUNCTIONGEMMA_DEVELOPER_MESSAGE
    prompt = json.loads(call["messages"][1]["content"])
    assert {card["capability_id"] for card in prompt["capabilities"]} == {
        "display.value.show",
        "sensor.temperature.read",
    }
    assert call["tools"][0]["function"]["name"] == "submit_plan"
