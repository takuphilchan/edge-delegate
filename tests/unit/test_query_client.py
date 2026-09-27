"""The query client exposes model proposals without executing capabilities."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from edge_delegate.contracts import PlanIR, PlanningRequest, Route
from edge_delegate.planner import PlannerContext, PlannerOutputError
from edge_delegate_lab.cli import main as lab_main
from edge_delegate_lab.client import ClientProfile, QueryClient

REPOSITORY_ROOT = Path(__file__).parents[2]
EXAMPLE_PROFILE = REPOSITORY_ROOT / "examples" / "local-display"


@dataclass(slots=True)
class EchoClarifyPlanner:
    requests: list[PlanningRequest] = field(default_factory=list)

    def plan(self, request: PlanningRequest, context: PlannerContext) -> PlanIR:
        del context
        self.requests.append(request)
        return PlanIR(
            request_id=request.request_id,
            route=Route.CLARIFY,
            clarification="Which display should I use?",
            confidence=0.75,
        )


class FailingPlanner:
    def plan(self, request: PlanningRequest, context: PlannerContext) -> PlanIR:
        del request, context
        raise PlannerOutputError("model did not return the submit_plan envelope")


@dataclass(slots=True)
class FakeSession:
    planner: object
    raw_output: str = "raw-generation"
    model_info: dict[str, object] = field(
        default_factory=lambda: {"model_id": "scripted-query-model", "device": "cpu"}
    )

    def selected_capability_ids(self, request, context) -> tuple[str, ...]:
        del request
        return tuple(card.capability_id for card in context.capabilities)

    def last_generation(self, *, include_raw_output: bool) -> dict[str, object]:
        result: dict[str, object] = {"latency_ms": 1.25, "generated_tokens": 3}
        if include_raw_output:
            result["raw_output"] = self.raw_output
        return result

    def classify_error(self, error: Exception) -> str:
        del error
        return "output_format"


def test_query_client_returns_parsed_and_validated_non_executing_result() -> None:
    planner = EchoClarifyPlanner()
    client = QueryClient(FakeSession(planner), ClientProfile.load(EXAMPLE_PROFILE))

    first = client.query("Turn on the display.")
    second = client.query("Use another display.", include_raw_output=False)

    assert first["request"]["request_id"] == "client-query-0001"
    assert second["request"]["request_id"] == "client-query-0002"
    assert first["parse_valid"] is True
    assert first["request_id_correct"] is True
    assert first["static_valid"] is True
    assert first["valid"] is True
    assert first["plan"]["route"] == "clarify"
    assert first["generation"]["raw_output"] == "raw-generation"
    assert "raw_output" not in second["generation"]
    assert first["execution"] == {
        "attempted": False,
        "reason": "query client is non-executing",
    }
    assert len(planner.requests) == 2


def test_query_client_preserves_raw_generation_when_plan_parsing_fails() -> None:
    client = QueryClient(FakeSession(FailingPlanner()), ClientProfile.load(EXAMPLE_PROFILE))

    result = client.query("Show the temperature.")

    assert result["generation_succeeded"] is True
    assert result["parse_valid"] is False
    assert result["valid"] is False
    assert result["plan"] is None
    assert result["failure"]["category"] == "output_format"
    assert result["generation"]["raw_output"] == "raw-generation"
    assert result["execution"]["attempted"] is False


@pytest.mark.parametrize("text,locale", [("x" * 8001, "en"), ("hello", "x" * 36)])
def test_query_client_validates_request_before_selection_and_inference(text, locale):
    planner = EchoClarifyPlanner()

    class NoSelectionSession(FakeSession):
        def selected_capability_ids(self, request, context):
            pytest.fail("invalid input must not reach capability selection")

    client = QueryClient(
        NoSelectionSession(planner), ClientProfile.load(EXAMPLE_PROFILE), locale=locale
    )
    with pytest.raises(ValueError):
        client.query(text)
    assert planner.requests == []


def test_query_client_accepts_maximum_request_length():
    client = QueryClient(FakeSession(EchoClarifyPlanner()), ClientProfile.load(EXAMPLE_PROFILE))
    assert client.query("x" * 8000)["valid"] is True


@pytest.mark.parametrize("bad_output", ["not a plan", {}, None])
def test_query_client_handles_untyped_plugin_output_and_recovers(bad_output):
    class RecoveringPlanner(EchoClarifyPlanner):
        def plan(self, request, context):
            if not self.requests:
                self.requests.append(request)
                return bad_output
            return super().plan(request, context)

    client = QueryClient(FakeSession(RecoveringPlanner()), ClientProfile.load(EXAMPLE_PROFILE))
    failure = client.query("first request")
    assert failure["valid"] is False
    assert failure["failure"]["error_type"] == "PlannerOutputError"
    assert failure["execution"]["attempted"] is False
    assert client.query("second request")["valid"] is True


def test_profile_loader_reports_missing_contract_files(tmp_path) -> None:
    with pytest.raises(ValueError, match=r"profile is missing capabilities\.json"):
        ClientProfile.load(tmp_path)


def test_plan_command_prints_one_machine_readable_result(monkeypatch, capsys) -> None:
    client = QueryClient(FakeSession(EchoClarifyPlanner()), ClientProfile.load(EXAMPLE_PROFILE))
    monkeypatch.setattr("edge_delegate_lab.cli._query_client", lambda args: client)

    exit_code = lab_main(
        [
            "plan",
            "--profile",
            str(EXAMPLE_PROFILE),
            "--text",
            "Show the temperature.",
        ]
    )

    result = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert result["schema_version"] == "edge-delegate-query-result.v1"
    assert result["valid"] is True


def test_interactive_command_reuses_model_and_controls_raw_output(
    monkeypatch,
    capsys,
) -> None:
    planner = EchoClarifyPlanner()
    client = QueryClient(FakeSession(planner), ClientProfile.load(EXAMPLE_PROFILE))
    monkeypatch.setattr("edge_delegate_lab.cli._query_client", lambda args: client)
    responses = iter(("first request", "/raw off", "second request", "/quit"))
    monkeypatch.setattr("builtins.input", lambda prompt: next(responses))

    exit_code = lab_main(
        ["interactive", "--profile", str(EXAMPLE_PROFILE), "--format", "json", "--raw-output"]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Loaded scripted-query-model" in output
    assert "raw model output: off" in output
    assert output.count('"raw_output": "raw-generation"') == 1
    assert [request.request_id for request in planner.requests] == [
        "client-query-0001",
        "client-query-0002",
    ]


def test_interactive_invalid_input_does_not_end_or_reload_session(monkeypatch, capsys):
    planner = EchoClarifyPlanner()
    client = QueryClient(FakeSession(planner), ClientProfile.load(EXAMPLE_PROFILE))
    loads = []

    def load(args):
        loads.append(args)
        return client

    monkeypatch.setattr("edge_delegate_lab.cli._query_client", load)
    responses = iter(("x" * 8001, "valid request", "/quit"))
    monkeypatch.setattr("builtins.input", lambda prompt: next(responses))
    assert lab_main(["interactive", "--profile", str(EXAMPLE_PROFILE)]) == 0
    assert "Invalid query:" in capsys.readouterr().out
    assert len(loads) == 1
    assert [request.text for request in planner.requests] == ["valid request"]


def test_interactive_readable_default_and_format_switch(monkeypatch, capsys):
    client = QueryClient(FakeSession(EchoClarifyPlanner()), ClientProfile.load(EXAMPLE_PROFILE))
    monkeypatch.setattr("edge_delegate_lab.cli._query_client", lambda args: client)
    responses = iter(("first query", "/format bad", "/format json", "second query", "/quit"))
    monkeypatch.setattr("builtins.input", lambda prompt: next(responses))
    assert lab_main(["interactive", "--profile", str(EXAMPLE_PROFILE)]) == 0
    output = capsys.readouterr().out
    assert "Execution: NOT attempted" in output
    assert "Question: Which display should I use?" in output
    assert "not a chat conversation" in output
    assert "usage: /format text|json" in output
    assert '"schema_version": "edge-delegate-query-result.v1"' in output
    assert "raw-generation" not in output


def test_readable_query_failure_is_not_presented_as_success():
    from edge_delegate_lab.presentation import render_query

    client = QueryClient(FakeSession(FailingPlanner()), ClientProfile.load(EXAMPLE_PROFILE))
    text = render_query(client.query("show temperature"))
    assert "no usable plan" in text
    assert "Checks: PASSED" not in text
    assert "Execution: NOT attempted" in text


def test_readable_query_escapes_terminal_controls():
    from edge_delegate_lab.presentation import render_query

    client = QueryClient(
        FakeSession(EchoClarifyPlanner(), raw_output="\x1b[2Jhidden"),
        ClientProfile.load(EXAMPLE_PROFILE),
    )
    assert "\x1b" not in render_query(client.query("test"))


def test_readable_local_plan_explains_step_references(demo_plan):
    from dataclasses import replace

    from edge_delegate_lab.presentation import render_query

    class LocalPlanner:
        def plan(self, request, context):
            return replace(demo_plan, request_id=request.request_id)

    client = QueryClient(FakeSession(LocalPlanner()), ClientProfile.load(EXAMPLE_PROFILE))
    output = render_query(client.query("Show temperature"))
    assert "Checks: PASSED" in output
    assert "value=result of read_temperature" in output
    assert "Passing checks does not prove the plan matches your intent." in output


def test_readable_validation_failure_includes_issue_code(demo_plan):
    from dataclasses import replace

    from edge_delegate_lab.presentation import render_query

    class InvalidLocalPlanner:
        def plan(self, request, context):
            return replace(demo_plan, request_id=request.request_id, steps=())

    client = QueryClient(FakeSession(InvalidLocalPlanner()), ClientProfile.load(EXAMPLE_PROFILE))
    output = render_query(client.query("Show temperature"))
    assert "Checks: FAILED" in output
    assert "Problem [route_shape]" in output
