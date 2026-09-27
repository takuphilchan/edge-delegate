"""FunctionGemma planner adapter with a replaceable inference backend."""

from __future__ import annotations

import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Protocol, runtime_checkable

from edge_delegate.contracts import CapabilityCard, PlanIR, PlanningRequest
from edge_delegate.ir import canonicalize_plan, parse_plan
from edge_delegate.retrieval import CapabilityIndex

from .base import Planner, PlannerContext, PlannerError, PlannerOutputError
from .prompts import SUBMIT_PLAN_TOOL, build_planner_messages

DEFAULT_MODEL_ID = "google/functiongemma-270m-it"
_FUNCTION_CALL = re.compile(
    r"\A\s*<start_function_call>\s*call:submit_plan\{plan_json:<escape>"
    r"(?P<plan>.*?)<escape>\}\s*<end_function_call>\s*\Z",
    flags=re.DOTALL,
)


class FunctionCallFormatError(PlannerOutputError):
    """Raised when the model does not emit the required submit_plan call."""


class FunctionPlanError(PlannerOutputError):
    """Raised when submit_plan contains malformed or invalid Plan IR."""


@dataclass(frozen=True, slots=True)
class ModelDiagnostics:
    model_id: str
    adapter_path: str | None
    revision: str | None
    device: str
    device_name: str | None
    dtype: str
    parameter_count: int
    model_footprint_bytes: int | None
    load_time_ms: float
    cpu_rss_before_bytes: int
    cpu_rss_after_bytes: int
    peak_gpu_memory_bytes: int | None
    torch_version: str
    transformers_version: str
    adapter_merged: bool = False
    compiled_decode: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class GenerationDiagnostics:
    raw_output: str
    prompt_tokens: int
    generated_tokens: int
    latency_ms: float
    cpu_rss_before_bytes: int
    cpu_rss_after_bytes: int
    peak_gpu_memory_bytes: int | None
    preprocessing_ms: float | None = None
    decoding_ms: float | None = None
    preprocessing_breakdown_ms: dict[str, float] | None = None

    def to_dict(self, *, include_raw_output: bool = True) -> dict[str, object]:
        result = asdict(self)
        if not include_raw_output:
            result.pop("raw_output")
        return result


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
        adapter_path: str | None = None,
        device_map: str = "auto",
        dtype: str = "auto",
        revision: str | None = None,
        max_context_tokens: int = 2048,
        stop_on_tool_end: bool = False,
        cpu_threads: int | None = None,
        merge_adapter: bool = False,
        compile_decode: bool = False,
    ) -> None:
        if (
            not isinstance(max_context_tokens, int)
            or isinstance(max_context_tokens, bool)
            or max_context_tokens < 1
        ):
            raise ValueError("max_context_tokens must be a positive integer")
        self._max_context_tokens = max_context_tokens
        self._stop_on_tool_end = stop_on_tool_end
        if type(merge_adapter) is not bool or type(compile_decode) is not bool:
            raise ValueError("merge_adapter and compile_decode must be booleans")
        if compile_decode and adapter_path is not None and not merge_adapter:
            raise ValueError("compiled decoding with a LoRA adapter requires merge_adapter")
        self._generation_options = {}
        try:
            import psutil
            import torch
            import transformers
            from transformers import AutoModelForCausalLM, AutoProcessor
        except ImportError as exc:
            raise PlannerError(
                "FunctionGemma inference requires the inference extra: "
                "python -m pip install -e '.[inference]'"
            ) from exc
        self._torch = torch
        if cpu_threads is not None:
            if type(cpu_threads) is not int or not 1 <= cpu_threads <= 64:
                raise ValueError("cpu_threads must be 1..64")
            torch.set_num_threads(cpu_threads)
        self._psutil = psutil
        self._last_generation: GenerationDiagnostics | None = None
        process = psutil.Process()
        cpu_before = process.memory_info().rss
        gpu_available = torch.cuda.is_available()
        if gpu_available:
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats()
        load_started = time.perf_counter()
        try:
            self._processor = AutoProcessor.from_pretrained(model_id, revision=revision)
            self._model = AutoModelForCausalLM.from_pretrained(
                model_id,
                device_map=device_map,
                dtype=dtype,
                revision=revision,
            )
            if adapter_path is not None:
                from peft import PeftModel

                self._model = PeftModel.from_pretrained(self._model, adapter_path)
                if merge_adapter:
                    # Changes only this resident model, never the saved candidate.
                    self._model = self._model.merge_and_unload(safe_merge=True)
            self._model.eval()
        except Exception as exc:
            raise PlannerError(
                f"could not load {model_id!r} with adapter {adapter_path!r}; confirm "
                "Hugging Face access, license acceptance, and adapter compatibility"
            ) from exc
        if compile_decode:
            if str(self._model.device).split(":")[0] != "cuda":
                raise PlannerError("compiled decoding currently requires a CUDA-resident model")
            from transformers.generation.configuration_utils import CompileConfig

            self._generation_options = {
                "cache_implementation": "static",
                "max_cache_len": max_context_tokens,
                "compile_config": CompileConfig(fullgraph=True, mode="reduce-overhead"),
            }
        if gpu_available:
            torch.cuda.synchronize()
        load_time_ms = (time.perf_counter() - load_started) * 1000
        cpu_after = process.memory_info().rss
        parameter = next(iter(self._model.parameters()), None)
        model_dtype = "unknown" if parameter is None else str(parameter.dtype)
        footprint_getter = getattr(self._model, "get_memory_footprint", None)
        footprint = None if footprint_getter is None else int(footprint_getter())
        config = getattr(self._model, "config", None)
        model_context = getattr(config, "max_position_embeddings", None)
        if isinstance(model_context, int) and model_context > 0:
            self._max_context_tokens = min(self._max_context_tokens, model_context)
        if compile_decode:
            # Keep decode shapes stable across request lengths instead of recompiling
            # a different static cache for each prompt/output-length combination.
            self._generation_options["max_cache_len"] = self._max_context_tokens
        revision = None if config is None else getattr(config, "_commit_hash", None)
        model_device = str(getattr(self._model, "device", "unknown"))
        self._model_info = ModelDiagnostics(
            model_id=model_id,
            adapter_path=adapter_path,
            revision=revision,
            device=model_device,
            device_name=torch.cuda.get_device_name(0) if gpu_available else None,
            dtype=model_dtype,
            parameter_count=sum(parameter.numel() for parameter in self._model.parameters()),
            model_footprint_bytes=footprint,
            load_time_ms=load_time_ms,
            cpu_rss_before_bytes=cpu_before,
            cpu_rss_after_bytes=cpu_after,
            peak_gpu_memory_bytes=(
                int(torch.cuda.max_memory_allocated()) if gpu_available else None
            ),
            torch_version=torch.__version__,
            transformers_version=transformers.__version__,
            adapter_merged=merge_adapter and adapter_path is not None,
            compiled_decode=compile_decode,
        )

    @property
    def model_info(self) -> ModelDiagnostics:
        return self._model_info

    def generate_batch(self, conversations, tools, *, max_new_tokens, batch_size=8):
        """Offline quality evaluation only; not a single-request latency measurement."""
        tokenizer = getattr(self._processor, "tokenizer", self._processor)
        original_padding = tokenizer.padding_side
        outputs = []
        try:
            tokenizer.padding_side = "left"
            for start in range(0, len(conversations), batch_size):
                encoded = self._processor.apply_chat_template(
                    conversations[start : start + batch_size],
                    tools=list(tools),
                    add_generation_prompt=True,
                    return_dict=True,
                    return_tensors="pt",
                    padding=True,
                )
                length = int(encoded["input_ids"].shape[-1])
                if length + max_new_tokens > self._max_context_tokens:
                    raise PlannerError("batched evaluation exceeds context budget")
                encoded = encoded.to(self._model.device)
                stop = [tokenizer.eos_token_id]
                if self._stop_on_tool_end:
                    tool_end = tokenizer.get_added_vocab().get("<end_function_call>")
                    if tool_end is None:
                        raise PlannerError("tokenizer lacks tool-call stop token")
                    stop.append(tool_end)
                with self._torch.inference_mode():
                    generated = self._model.generate(
                        **encoded,
                        do_sample=False,
                        max_new_tokens=max_new_tokens,
                        pad_token_id=tokenizer.pad_token_id,
                        eos_token_id=stop,
                        **self._generation_options,
                    )
                outputs.extend(
                    tokenizer.batch_decode(generated[:, length:], skip_special_tokens=True)
                )
        finally:
            tokenizer.padding_side = original_padding
        return outputs

    @property
    def last_generation(self) -> GenerationDiagnostics | None:
        return self._last_generation

    def generate(
        self,
        messages: Sequence[Mapping[str, object]],
        tools: Sequence[Mapping[str, object]],
        *,
        max_new_tokens: int,
    ) -> str:
        self._last_generation = None
        preprocessing_started = time.perf_counter()
        if (
            not isinstance(max_new_tokens, int)
            or isinstance(max_new_tokens, bool)
            or max_new_tokens < 1
        ):
            raise ValueError("max_new_tokens must be a positive integer")
        tokenization_started = time.perf_counter()
        encoded = self._processor.apply_chat_template(
            list(messages),
            tools=list(tools),
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        )
        tokenization_ms = (time.perf_counter() - tokenization_started) * 1000
        prompt_length = int(encoded["input_ids"].shape[-1])
        if prompt_length + max_new_tokens > self._max_context_tokens:
            raise PlannerError(
                f"context budget exceeded: {prompt_length} prompt tokens + "
                f"{max_new_tokens} reserved output tokens > {self._max_context_tokens}; "
                "shorten the query, reduce retrieved capabilities, or lower max_new_tokens"
            )
        model_device = getattr(self._model, "device", None)
        transfer_started = time.perf_counter()
        if model_device is not None:
            encoded = encoded.to(model_device)
        input_transfer_ms = (time.perf_counter() - transfer_started) * 1000
        resource_started = time.perf_counter()
        process = self._psutil.Process()
        cpu_before = process.memory_info().rss
        gpu_available = self._torch.cuda.is_available()
        if gpu_available:
            self._torch.cuda.reset_peak_memory_stats()
        generation_started = time.perf_counter()
        resource_setup_ms = (generation_started - resource_started) * 1000
        preprocessing_ms = (generation_started - preprocessing_started) * 1000
        stop_options = {}
        if self._stop_on_tool_end:
            tokenizer = getattr(self._processor, "tokenizer", self._processor)
            tool_end = tokenizer.get_added_vocab().get("<end_function_call>")
            if tool_end is None:
                raise PlannerError("compact task tokenizer lacks end_function_call token")
            stop_options["eos_token_id"] = [self._processor.eos_token_id, tool_end]
        with self._torch.inference_mode():
            generated = self._model.generate(
                **encoded,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                pad_token_id=self._processor.eos_token_id,
                **stop_options,
                **self._generation_options,
            )
        if gpu_available:
            self._torch.cuda.synchronize()
        latency_ms = (time.perf_counter() - generation_started) * 1000
        decoding_started = time.perf_counter()
        generated_tokens = generated[0][prompt_length:]
        raw_output = self._processor.decode(
            generated_tokens,
            skip_special_tokens=True,
        )
        self._last_generation = GenerationDiagnostics(
            raw_output=raw_output,
            prompt_tokens=int(prompt_length),
            generated_tokens=int(generated_tokens.shape[-1]),
            latency_ms=latency_ms,
            cpu_rss_before_bytes=cpu_before,
            cpu_rss_after_bytes=process.memory_info().rss,
            peak_gpu_memory_bytes=(
                int(self._torch.cuda.max_memory_allocated()) if gpu_available else None
            ),
            preprocessing_ms=preprocessing_ms,
            decoding_ms=(time.perf_counter() - decoding_started) * 1000,
            preprocessing_breakdown_ms={
                "tokenization_ms": tokenization_ms,
                "input_transfer_ms": input_transfer_ms,
                "resource_setup_ms": resource_setup_ms,
                "other_ms": max(
                    0, preprocessing_ms - tokenization_ms - input_transfer_ms - resource_setup_ms
                ),
            },
        )
        return raw_output


def extract_plan(output: str) -> PlanIR:
    """Accept only the exact FunctionGemma call and return typed Plan IR."""

    if not isinstance(output, str):
        raise PlannerError("FunctionGemma backend output must be text")
    stripped = output.strip()
    match = _FUNCTION_CALL.fullmatch(stripped)
    if match is None:
        raise FunctionCallFormatError("model did not call submit_plan in the required format")
    candidate = match.group("plan")
    try:
        plan = parse_plan(candidate)
    except Exception as exc:
        raise FunctionPlanError(f"model returned invalid Plan IR: {exc}") from exc
    return plan


def extract_plan_json(output: str) -> str:
    """Compatibility helper returning the canonical JSON for a strict typed plan."""

    return canonicalize_plan(extract_plan(output))


@dataclass(slots=True)
class ScriptedFunctionGemmaBackend:
    """Deterministic backend for unit tests and adapter smoke tests."""

    outputs: list[str]
    calls: list[dict[str, object]] = field(default_factory=list)
    model_info: ModelDiagnostics = field(
        default_factory=lambda: ModelDiagnostics(
            model_id="scripted",
            adapter_path=None,
            revision=None,
            device="cpu",
            device_name=None,
            dtype="none",
            parameter_count=0,
            model_footprint_bytes=0,
            load_time_ms=0.0,
            cpu_rss_before_bytes=0,
            cpu_rss_after_bytes=0,
            peak_gpu_memory_bytes=None,
            torch_version="not-loaded",
            transformers_version="not-loaded",
        )
    )
    last_generation: GenerationDiagnostics | None = None

    def generate(
        self,
        messages: Sequence[Mapping[str, object]],
        tools: Sequence[Mapping[str, object]],
        *,
        max_new_tokens: int,
    ) -> str:
        self.last_generation = None
        self.calls.append(
            {
                "messages": list(messages),
                "tools": list(tools),
                "max_new_tokens": max_new_tokens,
            }
        )
        if not self.outputs:
            raise PlannerError("scripted backend has no output remaining")
        output = self.outputs.pop(0)
        self.last_generation = GenerationDiagnostics(
            raw_output=output,
            prompt_tokens=0,
            generated_tokens=0,
            latency_ms=0.0,
            cpu_rss_before_bytes=0,
            cpu_rss_after_bytes=0,
            peak_gpu_memory_bytes=None,
        )
        return output


def select_capabilities(
    request: PlanningRequest,
    context: PlannerContext,
    *,
    limit: int,
) -> tuple[CapabilityCard, ...]:
    """Apply the planner's deterministic retrieval and policy filtering."""

    allowed = (
        None
        if context.policy.allowed_capabilities is None
        else context.policy.allowed_capabilities - context.policy.denied_capabilities
    )
    retrieved = CapabilityIndex(context.capabilities).search(
        request.text,
        limit=limit,
        allowed_ids=allowed,
    )
    selected = tuple(item.card for item in retrieved)
    if selected:
        return selected
    return tuple(
        card for card in context.capabilities if allowed is None or card.capability_id in allowed
    )[:limit]


@dataclass(slots=True)
class FunctionGemmaPlanner(Planner):
    backend: FunctionGemmaBackend
    retrieval_limit: int = 8
    max_new_tokens: int = 1024

    def plan(self, request: PlanningRequest, context: PlannerContext) -> PlanIR:
        selected = select_capabilities(request, context, limit=self.retrieval_limit)
        messages = build_planner_messages(request, context.state, context.policy, selected)
        output = self.backend.generate(
            messages,
            [SUBMIT_PLAN_TOOL],
            max_new_tokens=self.max_new_tokens,
        )
        return extract_plan(output)
