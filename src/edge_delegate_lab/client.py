"""Non-executing one-shot and interactive clients for installed model plugins."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from edge_delegate.contracts import CapabilityCard, DeviceState, PlanningRequest, Policy
from edge_delegate.ir import check_plan
from edge_delegate.model_plugins import ModelDiagnosticSession
from edge_delegate.planner import PlannerContext

MAX_PROFILE_FILE_BYTES = 1024 * 1024
MAX_RAW_OUTPUT_CHARS = 64 * 1024


def _reject_constant(value: str):
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def _without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> object:
    try:
        payload = path.read_bytes()
    except FileNotFoundError as exc:
        raise ValueError(f"profile is missing {path.name}: {path}") from exc
    if len(payload) > MAX_PROFILE_FILE_BYTES:
        raise ValueError(f"profile file exceeds {MAX_PROFILE_FILE_BYTES} bytes: {path}")
    return json.loads(
        payload.decode("utf-8"),
        object_pairs_hook=_without_duplicates,
        parse_constant=_reject_constant,
    )


@dataclass(frozen=True, slots=True)
class ClientProfile:
    """Typed, non-executable context loaded from a profile directory."""

    root: Path
    capabilities: tuple[CapabilityCard, ...]
    state: DeviceState
    policy: Policy

    @classmethod
    def load(cls, root: Path) -> ClientProfile:
        resolved = root.resolve()
        if not resolved.is_dir():
            raise ValueError(f"profile directory does not exist: {root}")
        raw_cards = _load_json(resolved / "capabilities.json")
        if not isinstance(raw_cards, list):
            raise ValueError("profile capabilities.json must contain a JSON array")
        return cls(
            root=resolved,
            capabilities=tuple(
                CapabilityCard.from_dict(card, f"$[{index}]")
                for index, card in enumerate(raw_cards)
            ),
            state=DeviceState.from_dict(_load_json(resolved / "state.json")),
            policy=Policy.from_dict(_load_json(resolved / "policy.json")),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "root": str(self.root),
            "capability_ids": [card.capability_id for card in self.capabilities],
            "state": self.state.to_dict(),
            "policy": self.policy.to_dict(),
        }


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
        self._query_count += 1
        request = PlanningRequest(
            request_id=f"client-query-{self._query_count:04d}",
            text=text.strip(),
            locale=self._locale,
        )
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


def render_result(result: dict[str, object]) -> str:
    return json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True)


def interactive_help() -> str:
    return "\n".join(
        (
            "Enter a natural-language request to generate and validate Plan IR.",
            "Commands:",
            "  /context       show the active capabilities, state, and policy",
            "  /raw on|off    include or hide raw model output",
            "  /help          show this help",
            "  /quit          exit",
            "Execution is always disabled in this client.",
        )
    )
