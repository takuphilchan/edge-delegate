"""Non-executing one-shot and interactive clients for installed model plugins."""

from __future__ import annotations

from datetime import UTC, datetime

from edge_delegate.contracts import PlanIR, PlanningRequest
from edge_delegate.ir import check_plan
from edge_delegate.model_plugins import ModelDiagnosticSession
from edge_delegate.planner import PlannerContext, PlannerOutputError

from .presentation import render_result as render_result
from .profiles import ClientProfile

MAX_RAW_OUTPUT_CHARS = 64 * 1024


class QueryClient:
    """Keep one model session loaded while evaluating arbitrary user queries."""

    def __init__(
        self,
        session: ModelDiagnosticSession,
        profile: ClientProfile,
        *,
        locale: str = "en",
    ) -> None:
        self._session = session
        self._profile = profile
        self._locale = locale
        self._query_count = 0

    @property
    def model_info(self) -> dict[str, object]:
        return dict(self._session.model_info)

    @property
    def profile(self) -> ClientProfile:
        return self._profile

    def query(self, text: str, *, include_raw_output: bool = True) -> dict[str, object]:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("query text must not be empty")
        request = PlanningRequest.from_dict(
            {
                "request_id": f"client-query-{self._query_count + 1:04d}",
                "text": text,
                "locale": self._locale,
            }
        )
        self._query_count += 1
        context = PlannerContext(
            capabilities=self._profile.capabilities,
            state=self._profile.state,
            policy=self._profile.policy,
        )
        selected_ids = self._session.selected_capability_ids(request, context)
        base: dict[str, object] = {
            "schema_version": "edge-delegate-query-result.v1",
            "request": request.to_dict(),
            "profile": {
                "root": str(self._profile.root),
                "state_snapshot_id": self._profile.state.snapshot_id,
                "policy_id": self._profile.policy.policy_id,
            },
            "selected_capability_ids": list(selected_ids),
            "execution": {
                "attempted": False,
                "reason": "query client is non-executing",
            },
        }
        try:
            plan = self._session.planner.plan(request, context)
            if not isinstance(plan, PlanIR):
                raise PlannerOutputError("planner did not return typed Plan IR")
        except Exception as exc:
            generation = self._generation(include_raw_output=include_raw_output)
            return {
                **base,
                "generation_succeeded": generation is not None,
                "parse_valid": False,
                "request_id_correct": False,
                "static_valid": False,
                "valid": False,
                "plan": None,
                "validation": None,
                "generation": generation,
                "failure": {
                    "category": self._session.classify_error(exc),
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
            }

        report = check_plan(
            plan,
            self._profile.capabilities,
            self._profile.state,
            self._profile.policy,
            now=datetime.now(UTC),
        )
        request_id_correct = plan.request_id == request.request_id
        issues = [
            {"path": issue.path, "code": issue.code, "message": issue.message}
            for issue in report.issues
        ]
        if not request_id_correct:
            issues.insert(
                0,
                {
                    "path": "$.request_id",
                    "code": "request_id_mismatch",
                    "message": "plan request_id does not match the active query",
                },
            )
        valid = request_id_correct and report.valid
        return {
            **base,
            "generation_succeeded": True,
            "parse_valid": True,
            "request_id_correct": request_id_correct,
            "static_valid": report.valid,
            "valid": valid,
            "plan": plan.to_dict(),
            "validation": {
                "valid": valid,
                "issues": issues,
                "estimated": {
                    "total_latency_ms": report.total_latency_ms,
                    "total_energy_mj": report.total_energy_mj,
                    "peak_memory_bytes": report.peak_memory_bytes,
                },
            },
            "generation": self._generation(include_raw_output=include_raw_output),
            "failure": None,
        }

    def _generation(self, *, include_raw_output: bool) -> dict[str, object] | None:
        generation = self._session.last_generation(include_raw_output=include_raw_output)
        if generation is None:
            return None
        result = dict(generation)
        if include_raw_output and "raw_output" in result:
            raw_output = str(result["raw_output"])
            result["raw_output"] = raw_output[:MAX_RAW_OUTPUT_CHARS]
            result["raw_output_truncated"] = len(raw_output) > MAX_RAW_OUTPUT_CHARS
        return result


def interactive_help() -> str:
    return "\n".join(
        (
            "Preview only: no device actions or external-model calls.",
            "Each query is independent; this is not a chat conversation.",
            "The profile is a saved snapshot, not live device state.",
            "Enter a request to generate a plan and check it against that profile.",
            "Commands:",
            "  /context       show the active capabilities, state, and policy",
            "  /raw on|off    include or hide raw model output",
            "  /format text|json    choose readable output or structured details",
            "  /help          show this help",
            "  /quit          exit",
            "Execution is always disabled in this client.",
        )
    )
