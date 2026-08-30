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

    exit_code = lab_main(["interactive", "--profile", str(EXAMPLE_PROFILE)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Loaded scripted-query-model" in output
    assert "raw model output: off" in output
    assert output.count('"raw_output": "raw-generation"') == 1
    assert [request.request_id for request in planner.requests] == [
        "client-query-0001",
        "client-query-0002",
    ]
