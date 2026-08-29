"""Versioned, declarative prompt construction for local planning models."""

from __future__ import annotations

import json
from collections.abc import Sequence

from edge_delegate.contracts import CapabilityCard, DeviceState, PlanningRequest, Policy

FUNCTIONGEMMA_DEVELOPER_MESSAGE = (
    "You are a model that can do function calling with the following functions"
)
PROMPT_VERSION = "functiongemma-plan-v0"
SUBMIT_PLAN_TOOL: dict[str, object] = {
    "type": "function",
    "function": {
        "name": "submit_plan",
        "description": (
            "Submit one complete edge execution Plan IR. This proposes a plan only; "
            "deterministic software validates it before any execution."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "plan_json": {
                    "type": "string",
                    "description": "Complete compact JSON for a plan-ir.v0 object.",
                }
            },
            "required": ["plan_json"],
        },
    },
}


def _compact(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    )


def build_planner_messages(
    request: PlanningRequest,
    state: DeviceState,
    policy: Policy,
    capabilities: Sequence[CapabilityCard],
) -> list[dict[str, str]]:
    """Build the exact messages used for baseline inference and SFT records."""

    instructions = {
        "prompt_version": PROMPT_VERSION,
        "task": "Call submit_plan exactly once with a complete plan-ir.v0 JSON string.",
        "constraints": [
            "Use only the declared capabilities.",
            "Never invent arguments, state, permission, approval, or capability results.",
            "Use local only when every requested operation is locally possible.",
            "Use clarify for material ambiguity, defer for temporary unavailability, and deny "
            "for prohibited or unsafe requests.",
            "Use external or hybrid only when policy external_allowed is true.",
            "Write and physical steps require an idempotency_key.",
            "References may target only an earlier step and use {$ref: step_id}.",
            "The plan request_id must exactly match the input request_id.",
        ],
        "plan_shape": {
            "schema_version": "plan-ir.v0",
            "request_id": "string",
            "route": "local|hybrid|external|clarify|defer|deny",
            "steps": [
                {
                    "step_id": "stable_snake_case",
                    "capability_id": "declared identifier",
                    "arguments": {},
                    "idempotency_key": "required for write or physical steps",
                }
            ],
            "reason_codes": ["stable_machine_codes"],
            "confidence": "number from 0 to 1",
            "clarification": "string or null",
        },
        "request": request.to_dict(),
        "device_state": state.to_dict(),
        "policy": policy.to_dict(),
        "capabilities": [card.to_dict() for card in capabilities],
    }
    return [
        {"role": "developer", "content": FUNCTIONGEMMA_DEVELOPER_MESSAGE},
        {"role": "user", "content": _compact(instructions)},
    ]


def sft_assistant_message(plan_json: str) -> dict[str, object]:
    """Return a provider-neutral assistant tool-call message for training exports."""

    return {
        "role": "assistant",
        "tool_calls": [
            {
                "type": "function",
                "function": {
                    "name": "submit_plan",
                    "arguments": {"plan_json": plan_json},
                },
            }
        ],
    }
