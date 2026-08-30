"""Operational and quality diagnostics for a real local planner checkpoint."""

from __future__ import annotations

import math
import statistics
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
from edge_delegate.ir import check_plan
from edge_delegate.model_plugins import ModelDiagnosticSession
from edge_delegate.planner import PlannerContext

from .execution import compare_plans

MAX_RAW_OUTPUT_CHARS = 64 * 1024
CONTROLLED_ROUTE_ORDER = (
    Route.LOCAL,
    Route.CLARIFY,
    Route.DEFER,
    Route.EXTERNAL,
    Route.HYBRID,
    Route.DENY,
)


@dataclass(frozen=True, slots=True)
class DoctorCaseResult:
    record_id: str
    expected_route: str
    selected_capability_ids: tuple[str, ...]
    generation_succeeded: bool
    parse_valid: bool
    request_id_correct: bool
    static_valid: bool
    route_correct: bool
    exact_plan: bool
    failure_category: str | None
    error: str | None
    static_issue_codes: tuple[str, ...]
    predicted_plan: dict[str, object] | None
    generation: dict[str, object] | None


def select_controlled_records(
    records: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Select one deterministic integration case per supported route."""

    selected: list[dict[str, object]] = []
    for route in CONTROLLED_ROUTE_ORDER:
        match = next(
            (
                record
                for record in records
                if isinstance(record.get("expected_plan"), dict)
                and record["expected_plan"].get("route") == route.value
            ),
            None,
        )
        if match is not None:
            selected.append(match)
    return selected


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _bounded_generation(
    session: ModelDiagnosticSession,
    *,
    include_raw_output: bool,
) -> dict[str, object] | None:
    generation = session.last_generation(include_raw_output=include_raw_output)
    if generation is None:
        return None
    result = dict(generation)
    if include_raw_output:
        raw_output = str(result["raw_output"])
        result["raw_output"] = raw_output[:MAX_RAW_OUTPUT_CHARS]
        result["raw_output_truncated"] = len(raw_output) > MAX_RAW_OUTPUT_CHARS
    return result


class ModelDoctor:
    """Run inference diagnostics without executing any model-proposed capability."""

    def __init__(
        self,
        session: ModelDiagnosticSession,
    ) -> None:
        self._session = session
        self._planner = session.planner

    def run(
        self,
        records: list[dict[str, object]],
        *,
        include_raw_output: bool = True,
    ) -> dict[str, object]:
        cases = [
            self._run_case(record, include_raw_output=include_raw_output) for record in records
        ]
        generations = [case.generation for case in cases if case.generation is not None]
        latencies = [
            float(value)
            for item in generations
            if isinstance((value := item.get("latency_ms")), (int, float))
        ]
        warm_latencies = latencies[1:]

        def rate(field: str) -> float:
            return sum(bool(getattr(case, field)) for case in cases) / len(cases) if cases else 0.0

        return {
            "schema_version": "edge-delegate-model-doctor.v0",
            "purpose": "integration_smoke_not_model_quality_benchmark",
            "evaluated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "execution_policy": "model proposals were statically checked but never executed",
            "model": dict(self._session.model_info),
            "operational": {
                "case_count": len(cases),
                "generation_success_count": len(generations),
                "all_generations_succeeded": len(generations) == len(cases),
            },
            "quality_smoke": {
                "parse_valid_rate": rate("parse_valid"),
                "request_id_accuracy": rate("request_id_correct"),
                "static_valid_rate": rate("static_valid"),
                "route_accuracy": rate("route_correct"),
                "exact_plan_accuracy": rate("exact_plan"),
            },
            "latency": {
                "first_generation_ms": latencies[0] if latencies else None,
                "warm_p50_ms": statistics.median(warm_latencies) if warm_latencies else None,
                "warm_p95_ms": _percentile(warm_latencies, 0.95),
                "maximum_peak_gpu_memory_bytes": max(
                    (
                        int(item["peak_gpu_memory_bytes"])
                        for item in generations
                        if item.get("peak_gpu_memory_bytes") is not None
                    ),
                    default=None,
                ),
            },
            "failure_counts": {
                category: sum(case.failure_category == category for case in cases)
                for category in sorted(
                    {case.failure_category for case in cases if case.failure_category}
                )
            },
            "cases": [asdict(case) for case in cases],
        }

    def _run_case(
        self,
        record: dict[str, object],
        *,
        include_raw_output: bool,
    ) -> DoctorCaseResult:
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
        context = PlannerContext(capabilities=cards, state=state, policy=policy)
        selected_ids = self._session.selected_capability_ids(request, context)
        try:
            predicted = self._planner.plan(request, context)
        except Exception as exc:
            category = self._session.classify_error(exc)
            generation = _bounded_generation(
                self._session,
                include_raw_output=include_raw_output,
            )
            return DoctorCaseResult(
                record_id=record_id,
                expected_route=expected.route.value,
                selected_capability_ids=selected_ids,
                generation_succeeded=generation is not None,
                parse_valid=False,
                request_id_correct=False,
                static_valid=False,
                route_correct=False,
                exact_plan=False,
                failure_category=category,
                error=f"{type(exc).__name__}: {exc}",
                static_issue_codes=(),
                predicted_plan=None,
                generation=generation,
            )

        report = check_plan(predicted, cards, state, policy, now=state.observed_at)
        comparison = compare_plans(predicted, expected)
        request_id_correct = predicted.request_id == request.request_id
        if not request_id_correct:
            category = "request_id_mismatch"
        elif not report.valid:
            category = "static_validation"
        elif not comparison.route_correct:
            category = "route_selection"
        elif not comparison.plan_exact:
            category = "plan_content"
        else:
            category = None
        return DoctorCaseResult(
            record_id=record_id,
            expected_route=expected.route.value,
            selected_capability_ids=selected_ids,
            generation_succeeded=True,
            parse_valid=True,
            request_id_correct=request_id_correct,
            static_valid=report.valid,
            route_correct=comparison.route_correct,
            exact_plan=comparison.plan_exact,
            failure_category=category,
            error=None,
            static_issue_codes=tuple(issue.code for issue in report.issues),
            predicted_plan=predicted.to_dict(),
            generation=_bounded_generation(
                self._session,
                include_raw_output=include_raw_output,
            ),
        )
