"""FunctionGemma planner adapter with a replaceable inference backend."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from edge_delegate.contracts import PlanningRequest
from edge_delegate.ir import canonicalize_plan, parse_plan
from edge_delegate.retrieval import CapabilityIndex

from .base import Planner, PlannerContext, PlannerError
from .prompts import SUBMIT_PLAN_TOOL, build_planner_messages

DEFAULT_MODEL_ID = "google/functiongemma-270m-it"
_FUNCTION_CALL = re.compile(
    r"\A\s*<start_function_call>\s*call:submit_plan\{plan_json:<escape>"
    r"(?P<plan>.*?)<escape>\}\s*<end_function_call>\s*\Z",
    flags=re.DOTALL,
)


@runtime_checkable
class FunctionGemmaBackend(Protocol):
    def generate(
        self,
        messages: Sequence[Mapping[str, object]],
        tools: Sequence[Mapping[str, object]],
        *,
        max_new_tokens: int,
    ) -> str: ...


class TransformersFunctionGemmaBackend:
    """Lazy Hugging Face backend; importing the core package does not load ML libraries."""

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        *,
        device_map: str = "auto",
        dtype: str = "auto",
    ) -> None:
        try:
            from transformers import AutoModelForCausalLM, AutoProcessor
        except ImportError as exc:
            raise PlannerError(
                "FunctionGemma inference requires the planner extra: "
                "python -m pip install -e '.[planner]'"
            ) from exc
        try:
            self._processor = AutoProcessor.from_pretrained(model_id)
            self._model = AutoModelForCausalLM.from_pretrained(
                model_id,
                device_map=device_map,
                dtype=dtype,
            )
        except Exception as exc:
            raise PlannerError(
                f"could not load {model_id!r}; confirm Hugging Face access and license acceptance"
            ) from exc

    def generate(
        self,
        messages: Sequence[Mapping[str, object]],
        tools: Sequence[Mapping[str, object]],
        *,
        max_new_tokens: int,
    ) -> str:
        encoded = self._processor.apply_chat_template(
            list(messages),
            tools=list(tools),
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        )
        model_device = getattr(self._model, "device", None)
        if model_device is not None:
            encoded = encoded.to(model_device)
        generated = self._model.generate(
            **encoded,
            max_new_tokens=max_new_tokens,
            do_sample=False,
        )
        prompt_length = encoded["input_ids"].shape[-1]
        return self._processor.decode(
            generated[0][prompt_length:],
            skip_special_tokens=False,
        )


def extract_plan_json(output: str) -> str:
    """Accept only the exact FunctionGemma submit_plan call."""

    if not isinstance(output, str):
        raise PlannerError("FunctionGemma backend output must be text")
    stripped = output.strip()
    match = _FUNCTION_CALL.fullmatch(stripped)
    if match is None:
        raise PlannerError("model did not call submit_plan in the required format")
    candidate = match.group("plan")
    try:
        plan = parse_plan(candidate)
    except Exception as exc:
        raise PlannerError(f"model returned invalid Plan IR: {exc}") from exc
    return canonicalize_plan(plan)


@dataclass(slots=True)
class ScriptedFunctionGemmaBackend:
    """Deterministic backend for unit tests and adapter smoke tests."""

    outputs: list[str]
    calls: list[dict[str, object]] = field(default_factory=list)

    def generate(
        self,
        messages: Sequence[Mapping[str, object]],
        tools: Sequence[Mapping[str, object]],
        *,
        max_new_tokens: int,
    ) -> str:
        self.calls.append(
            {
                "messages": list(messages),
                "tools": list(tools),
                "max_new_tokens": max_new_tokens,
            }
        )
        if not self.outputs:
            raise PlannerError("scripted backend has no output remaining")
        return self.outputs.pop(0)


@dataclass(slots=True)
class FunctionGemmaPlanner(Planner):
    backend: FunctionGemmaBackend
    retrieval_limit: int = 8
    max_new_tokens: int = 1024

    def plan(self, request: PlanningRequest, context: PlannerContext) -> str:
        allowed = (
            None
            if context.policy.allowed_capabilities is None
            else context.policy.allowed_capabilities - context.policy.denied_capabilities
        )
        retrieved = CapabilityIndex(context.capabilities).search(
            request.text,
            limit=self.retrieval_limit,
            allowed_ids=allowed,
        )
        selected = tuple(item.card for item in retrieved)
        if not selected:
            selected = tuple(
                card
                for card in context.capabilities
                if allowed is None or card.capability_id in allowed
            )[: self.retrieval_limit]
        messages = build_planner_messages(request, context.state, context.policy, selected)
        output = self.backend.generate(
            messages,
            [SUBMIT_PLAN_TOOL],
            max_new_tokens=self.max_new_tokens,
        )
        return extract_plan_json(output)
