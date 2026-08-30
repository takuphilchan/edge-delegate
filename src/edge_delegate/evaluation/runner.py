"""Reproducible software and planner evaluation coordinator."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from edge_delegate.contracts import (
    CapabilityCard,
    DeviceState,
    PlanIR,
    PlanningRequest,
    Policy,
    Route,
)
from edge_delegate.ir import check_plan, validate_plan
from edge_delegate.planner import Planner, PlannerContext, PlannerOutputError
from edge_delegate.runtime import DeviceGateway, ExecutionStatus, Executor

from .calibration import brier_score, expected_calibration_error, selective_accuracy
from .execution import compare_plans


@dataclass(frozen=True, slots=True)
class CaseResult:
    record_id: str
    parse_valid: bool
    request_id_correct: bool
    static_valid: bool
    route_correct: bool
    capability_sequence_exact: bool
    plan_exact: bool
    outcome_correct: bool
    execution_success: bool | None
    confidence: float | None
    error: str | None = None


class EvaluationRunner:
    def __init__(
        self,
        planner: Planner,
        *,
        execution_harness: Callable[[dict[str, object]], DeviceGateway] | None = None,
    ) -> None:
        self._planner = planner
        self._execution_harness = execution_harness

    def evaluate(self, records: list[dict[str, object]]) -> dict[str, object]:
        cases = [self._evaluate_record(record) for record in records]
        calibration_cases = [
            (
                case.confidence,
                case.request_id_correct
                and case.static_valid
                and case.plan_exact
                and case.execution_success is not False,
            )
            for case in cases
            if case.confidence is not None
        ]
        confidences = [confidence for confidence, _ in calibration_cases]
        plan_successes = [success for _, success in calibration_cases]

        def rate(field: str) -> float:
            return sum(bool(getattr(case, field)) for case in cases) / len(cases) if cases else 0.0

        executable = [
            case.execution_success for case in cases if case.execution_success is not None
        ]
        return {
            "schema_version": "edge-delegate-evaluation.v1",
            "evaluated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "case_count": len(cases),
            "metrics": {
                "parse_valid_rate": rate("parse_valid"),
                "request_id_accuracy": rate("request_id_correct"),
                "static_valid_rate": rate("static_valid"),
                "route_accuracy": rate("route_correct"),
                "capability_sequence_accuracy": rate("capability_sequence_exact"),
                "exact_plan_accuracy": rate("plan_exact"),
                "outcome_accuracy": rate("outcome_correct"),
                "local_execution_success_rate": (
                    sum(bool(item) for item in executable) / len(executable) if executable else None
                ),
                "calibration_case_count": len(calibration_cases),
                "brier_score": (
                    brier_score(confidences, plan_successes) if calibration_cases else None
                ),
                "expected_calibration_error": (
                    expected_calibration_error(confidences, plan_successes)
                    if calibration_cases
                    else None
                ),
                "selective_accuracy": (
                    [asdict(point) for point in selective_accuracy(confidences, plan_successes)]
                    if calibration_cases
                    else []
                ),
            },
            "cases": [asdict(case) for case in cases],
        }

    def _evaluate_record(self, record: dict[str, object]) -> CaseResult:
        record_id = str(record["record_id"])
        request = PlanningRequest.from_dict(record["request"])
        state = DeviceState.from_dict(record["state"])
        policy = Policy.from_dict(record["policy"])
        raw_cards = record["capabilities"]
        if not isinstance(raw_cards, list):
            raise ValueError("record capabilities must be a list")
        cards = tuple(
            CapabilityCard.from_dict(card, f"$.capabilities[{index}]")
            for index, card in enumerate(raw_cards)
        )
        expected = PlanIR.from_dict(record["expected_plan"])
        try:
            predicted = self._planner.plan(
                request,
                PlannerContext(capabilities=cards, state=state, policy=policy),
            )
            if not isinstance(predicted, PlanIR):
                raise PlannerOutputError("planner did not return typed Plan IR")
        except Exception as exc:
            return CaseResult(
                record_id=record_id,
                parse_valid=False,
                request_id_correct=False,
                static_valid=False,
                route_correct=False,
                capability_sequence_exact=False,
                plan_exact=False,
                outcome_correct=False,
                execution_success=None,
                confidence=None,
                error=f"{type(exc).__name__}: {exc}",
            )
        comparison = compare_plans(predicted, expected)
        report = check_plan(predicted, cards, state, policy, now=state.observed_at)
        request_id_correct = predicted.request_id == request.request_id
        candidate_valid = report.valid and request_id_correct
        expected_status = str(record["expected_outcome"])
        predicted_status = {
            Route.LOCAL: "executed" if candidate_valid else "invalid_plan",
            Route.HYBRID: "external_required" if candidate_valid else "invalid_plan",
            Route.EXTERNAL: "external_required" if candidate_valid else "invalid_plan",
            Route.CLARIFY: "clarification_required" if candidate_valid else "invalid_plan",
            Route.DEFER: "deferred" if candidate_valid else "invalid_plan",
            Route.DENY: "denied" if candidate_valid else "invalid_plan",
        }[predicted.route]
        execution_success: bool | None = None
        execution_error: str | None = None
        if expected.route in {Route.LOCAL, Route.HYBRID}:
            if not candidate_valid or predicted.route not in {Route.LOCAL, Route.HYBRID}:
                execution_success = False
            elif self._execution_harness is not None:
                try:
                    device = self._execution_harness(record)
                    validated = validate_plan(
                        predicted,
                        cards,
                        state,
                        policy,
                        now=state.observed_at,
                    )
                    execution = Executor().execute(validated, device, policy)
                    execution_success = execution.status is ExecutionStatus.SUCCEEDED
                    execution_error = execution.error
                except Exception as exc:
                    execution_success = False
                    execution_error = f"{type(exc).__name__}: {exc}"
        return CaseResult(
            record_id=record_id,
            parse_valid=True,
            request_id_correct=request_id_correct,
            static_valid=report.valid,
            route_correct=comparison.route_correct,
            capability_sequence_exact=comparison.capability_sequence_exact,
            plan_exact=comparison.plan_exact,
            outcome_correct=predicted_status == expected_status,
            execution_success=execution_success,
            confidence=predicted.confidence,
            error=execution_error,
        )
