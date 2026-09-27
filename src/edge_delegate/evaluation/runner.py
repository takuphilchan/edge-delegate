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
from edge_delegate.planner.base import PlanningObservation
from edge_delegate.runtime import DeviceGateway, ExecutionStatus, Executor

from .calibration import brier_score, expected_calibration_error, selective_accuracy
from .execution import compare_plans
from .outcomes import check_effects


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
    task_success: bool | None = None
    effect_issues: tuple[str, ...] = ()
    wrong_but_permitted: bool = False
    unnecessary_abstention: bool = False
    forbidden_invocation_count: int = 0


class EvaluationRunner:
    def __init__(
        self,
        planner: Planner,
        *,
        execution_harness: Callable[[dict[str, object]], DeviceGateway] | None = None,
        use_batch: bool = True,
        diagnostics: bool = False,
        progress: Callable[[int, int], None] | None = None,
    ) -> None:
        self._planner = planner
        self._execution_harness = execution_harness
        self._use_batch = use_batch
        self._capture_diagnostics = diagnostics
        self._progress = progress

    def evaluate(self, records: list[dict[str, object]]) -> dict[str, object]:
        from edge_delegate.data.fingerprint import dataset_fingerprint

        self._batch_predictions = {}
        self._diagnostics = {}
        batch = getattr(self._planner, "plan_many", None)
        if self._capture_diagnostics:
            batch = getattr(self._planner, "plan_many_with_diagnostics", batch)
        if self._use_batch and callable(batch):
            requests = [PlanningRequest.from_dict(record["request"]) for record in records]
            contexts = [
                PlannerContext(
                    capabilities=tuple(
                        CapabilityCard.from_dict(card) for card in record["capabilities"]
                    ),
                    state=DeviceState.from_dict(record["state"]),
                    policy=Policy.from_dict(record["policy"]),
                )
                for record in records
            ]
            predictions = batch(requests, contexts)
            self._batch_predictions = {
                request.request_id: predicted
                for request, predicted in zip(requests, predictions, strict=True)
            }
        cases = []
        for record in records:
            cases.append(self._evaluate_record(record))
            if self._progress is not None:
                self._progress(len(cases), len(records))
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
            "schema_version": "edge-delegate-evaluation.v2",
            "complete": True,
            "dataset_sha256": dataset_fingerprint(records),
            "deprecated_metrics": {"outcome_accuracy": "status-only alias; use task_success_rate"},
            "evaluated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "case_count": len(cases),
            **({"decision_metrics": self._decision_metrics()} if self._capture_diagnostics else {}),
            "metrics": {
                "parse_valid_rate": rate("parse_valid"),
                "request_id_accuracy": rate("request_id_correct"),
                "static_valid_rate": rate("static_valid"),
                "route_accuracy": rate("route_correct"),
                "capability_sequence_accuracy": rate("capability_sequence_exact"),
                "exact_plan_accuracy": rate("plan_exact"),
                "outcome_accuracy": rate("outcome_correct"),
                "status_accuracy": rate("outcome_correct"),
                "task_assessed_count": sum(case.task_success is not None for case in cases),
                "task_success_rate": (
                    sum(case.task_success is True for case in cases)
                    / sum(case.task_success is not None for case in cases)
                    if any(case.task_success is not None for case in cases)
                    else None
                ),
                "wrong_but_permitted_count": sum(case.wrong_but_permitted for case in cases),
                "forbidden_invocation_count": sum(
                    case.forbidden_invocation_count for case in cases
                ),
                "unnecessary_abstention_count": sum(case.unnecessary_abstention for case in cases),
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
            "cases": [
                {
                    **asdict(case),
                    "category": record.get("metadata", {}).get("category", "legacy"),
                    "expected_task": record.get("expected_task"),
                    "family": record.get("metadata", {}).get("scenario_group"),
                    **(
                        {"diagnostics": self._diagnostics[case.record_id]}
                        if self._capture_diagnostics
                        else {}
                    ),
                }
                for case, record in zip(cases, records, strict=True)
            ],
        }

    def _decision_metrics(self):
        assessed = [
            diagnostic["intent_correct"]
            for diagnostic in self._diagnostics.values()
            if diagnostic.get("intent_correct") is not None
        ]
        return {
            "assessed_count": len(assessed),
            "correct_count": sum(assessed),
            "accuracy": sum(assessed) / len(assessed) if assessed else None,
            "unassessed_count": len(self._diagnostics) - len(assessed),
            "scope": "checked plugin decision before compilation; not raw model intent",
        }

    def _observe_prediction(self, predicted, record):
        if not isinstance(predicted, PlanningObservation):
            return predicted
        if self._capture_diagnostics:
            from edge_delegate.data.fingerprint import content_fingerprint
            from edge_delegate.evaluation.outcomes import _equal

            expected = record.get("expected_task")
            self._diagnostics[str(record["record_id"])] = {
                "decision_available": predicted.decision is not None,
                # Hash values, do not persist free-form task names or parameters by default.
                "decision_sha256": (
                    content_fingerprint(predicted.decision)
                    if predicted.decision is not None
                    else None
                ),
                "intent_correct": (
                    _equal(predicted.decision, expected)
                    if expected is not None and predicted.decision is not None
                    else None
                ),
            }
        return predicted.unwrap()

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
            if request.request_id in self._batch_predictions:
                predicted = self._batch_predictions[request.request_id]
                if isinstance(predicted, Exception):
                    raise predicted
            else:
                plan = self._planner.plan
                if self._capture_diagnostics:
                    plan = getattr(self._planner, "plan_with_diagnostics", plan)
                predicted = plan(
                    request,
                    PlannerContext(capabilities=cards, state=state, policy=policy),
                )
            predicted = self._observe_prediction(predicted, record)
            if not isinstance(predicted, PlanIR):
                raise PlannerOutputError("planner did not return typed Plan IR")
        except Exception as exc:
            self._diagnostics[record_id] = {
                **self._diagnostics.get(record_id, {}),
                "stage": "planning",
                "error_type": type(exc).__name__,
            }
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
                task_success=False if "expected_effects" in record else None,
            )
        comparison = compare_plans(predicted, expected)
        evaluation_at = (
            datetime.fromisoformat(record["evaluation_at"])
            if "evaluation_at" in record
            else state.observed_at
        )
        report = check_plan(predicted, cards, state, policy, now=evaluation_at)
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
        device = None
        execution = None
        invocations: list[str] = []
        if predicted.route in {Route.LOCAL, Route.HYBRID} or expected.route in {
            Route.LOCAL,
            Route.HYBRID,
        }:
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
                        now=evaluation_at,
                    )
                    execution = Executor(on_invoke=invocations.append).execute(
                        validated, device, policy
                    )
                    execution_success = execution.status is ExecutionStatus.SUCCEEDED
                    execution_error = execution.error
                    if not execution_success:
                        predicted_status = "execution_failed"
                except Exception as exc:
                    execution_success = False
                    execution_error = f"{type(exc).__name__}: {exc}"
                    predicted_status = "execution_failed"
        task_success = None
        effect_issues = ()
        if "expected_effects" in record:
            if predicted_status != expected_status:
                task_success = False
            elif not candidate_valid:
                task_success = (
                    expected_status == "invalid_plan"
                    and not record["expected_effects"]["invocations"]
                )
            elif predicted.route not in {Route.LOCAL, Route.HYBRID}:
                task_success, effect_issues = check_effects(
                    record["expected_effects"],
                    state=state.values,
                    final_output=None,
                    invocations=[],
                )
            elif device is not None and execution is not None:
                task_success, effect_issues = check_effects(
                    record["expected_effects"],
                    state=device.snapshot().values,
                    final_output=execution.final_output,
                    invocations=invocations,
                )
                task_success = task_success and execution_success is True
        if self._capture_diagnostics:
            from edge_delegate.data.fingerprint import content_fingerprint

            predicted_dict = predicted.to_dict()
            expected_dict = expected.to_dict()
            observed_state = state.values if device is None else device.snapshot().values
            observed_output = None if execution is None else execution.final_output
            observed_issues = ()
            if "expected_effects" in record:
                _, observed_issues = check_effects(
                    record["expected_effects"],
                    state=observed_state,
                    final_output=observed_output,
                    invocations=invocations,
                )
            self._diagnostics[record_id] = {
                **self._diagnostics.get(record_id, {}),
                "stage": "evaluated",
                "predicted_route": predicted.route.value,
                "expected_route": expected.route.value,
                "predicted_status": predicted_status,
                "expected_status": expected_status,
                "validation_codes": [issue.code for issue in report.issues],
                "predicted_plan_sha256": content_fingerprint(predicted_dict),
                "arguments_match": content_fingerprint(
                    [step["arguments"] for step in predicted_dict["steps"]]
                )
                == content_fingerprint([step["arguments"] for step in expected_dict["steps"]]),
                "invocations": list(invocations),
                "observed_effect_issues": list(observed_issues),
                "observed_state_sha256": content_fingerprint(dict(observed_state)),
                "observed_output_sha256": content_fingerprint(observed_output),
            }
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
            confidence=predicted.confidence
            if getattr(self._planner, "provides_confidence", True)
            else None,
            error=execution_error,
            task_success=task_success,
            effect_issues=effect_issues,
            wrong_but_permitted=execution_success is True and task_success is False,
            unnecessary_abstention=(
                expected.route is Route.LOCAL
                and predicted.route in {Route.DENY, Route.CLARIFY, Route.DEFER}
            ),
            forbidden_invocation_count=sum(
                capability_id in record.get("expected_effects", {}).get("forbidden_invocations", [])
                for capability_id in invocations
            ),
        )
