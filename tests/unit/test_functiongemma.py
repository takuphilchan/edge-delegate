"""Tests for the strict FunctionGemma adapter boundary."""

import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from edge_delegate.ir import canonicalize_plan
from edge_delegate.planner import (
    FunctionGemmaPlanner,
    PlannerContext,
    PlannerError,
    ScriptedFunctionGemmaBackend,
    TransformersFunctionGemmaBackend,
    extract_plan_json,
)
from edge_delegate.planner.prompts import FUNCTIONGEMMA_DEVELOPER_MESSAGE


def test_extract_plan_json_accepts_submit_plan_wrapper(demo_plan) -> None:
    plan_json = canonicalize_plan(demo_plan)
    output = (
        "<start_function_call>call:submit_plan{plan_json:<escape>"
        f"{plan_json}"
        "<escape>}<end_function_call>"
    )
    assert extract_plan_json(output) == plan_json


@pytest.mark.parametrize(
    "output",
    [
        "Here is your plan: {}",
        "{}",
        "<start_function_call>call:unknown{}<end_function_call>",
        "```json\n{}\n```",
    ],
)
def test_extract_plan_json_rejects_untrusted_wrappers(output: str) -> None:
    with pytest.raises(PlannerError):
        extract_plan_json(output)


def test_planner_retrieves_cards_and_records_exact_tool_prompt(
    demo_world, demo_policy, demo_request, demo_plan
) -> None:
    plan_json = canonicalize_plan(demo_plan)
    backend = ScriptedFunctionGemmaBackend(
        [
            "<start_function_call>call:submit_plan{plan_json:<escape>"
            f"{plan_json}"
            "<escape>}<end_function_call>"
        ]
    )
    planner = FunctionGemmaPlanner(backend=backend, retrieval_limit=2)
    state = demo_world.snapshot()

    output = planner.plan(
        demo_request,
        PlannerContext(
            capabilities=demo_world.capability_cards,
            state=state,
            policy=demo_policy,
        ),
    )

    assert canonicalize_plan(output) == plan_json
    call = backend.calls[0]
    assert call["messages"][0]["content"] == FUNCTIONGEMMA_DEVELOPER_MESSAGE
    prompt = json.loads(call["messages"][1]["content"])
    assert {card["capability_id"] for card in prompt["capabilities"]} == {
        "display.value.show",
        "sensor.temperature.read",
    }
    assert call["tools"][0]["function"]["name"] == "submit_plan"


@pytest.mark.parametrize(
    "generation_options",
    [{}, {"cache_implementation": "static", "max_cache_len": 15, "compile_config": "test-config"}],
)
def test_transformers_backend_uses_official_deterministic_generation_settings(
    generation_options,
) -> None:
    class FakeTokens:
        def __init__(self, length: int) -> None:
            self.shape = (length,)

        def __getitem__(self, item):
            assert isinstance(item, slice)
            return FakeTokens(self.shape[-1] - int(item.start))

    class FakeBatch(dict):
        def to(self, device):
            assert device == "cpu"
            return self

    class FakeProcessor:
        eos_token_id = 7

        def __init__(self) -> None:
            self.template_call = None
            self.decode_call = None

        def apply_chat_template(self, messages, **kwargs):
            self.template_call = {"messages": messages, **kwargs}
            return FakeBatch(input_ids=FakeTokens(3))

        def decode(self, tokens, **kwargs):
            self.decode_call = {"tokens": tokens, **kwargs}
            return "model-output"

    class FakeModel:
        device = "cpu"

        def __init__(self) -> None:
            self.generate_call = None

        def generate(self, **kwargs):
            self.generate_call = kwargs
            return [FakeTokens(5)]

    class FakeMemory:
        rss = 123

    class FakeProcess:
        def memory_info(self):
            return FakeMemory()

    class FakePsutil:
        @staticmethod
        def Process():
            return FakeProcess()

    class FakeCuda:
        @staticmethod
        def is_available() -> bool:
            return False

    class FakeTorch:
        cuda = FakeCuda()
        inference_mode = staticmethod(nullcontext)

    processor = FakeProcessor()
    model = FakeModel()
    backend = object.__new__(TransformersFunctionGemmaBackend)
    backend._processor = processor
    backend._model = model
    backend._torch = FakeTorch()
    backend._psutil = FakePsutil()
    backend._last_generation = None
    backend._max_context_tokens = 15
    backend._stop_on_tool_end = False
    backend._generation_options = generation_options

    output = backend.generate(
        [{"role": "user", "content": "test"}],
        [{"type": "function"}],
        max_new_tokens=12,
    )

    assert output == "model-output"
    assert model.generate_call["do_sample"] is False
    assert model.generate_call["pad_token_id"] == 7
    assert model.generate_call["max_new_tokens"] == 12
    for name, value in generation_options.items():
        assert model.generate_call[name] == value
    assert processor.decode_call["skip_special_tokens"] is True
    assert backend.last_generation.prompt_tokens == 3
    assert backend.last_generation.generated_tokens == 2
    parts = backend.last_generation.preprocessing_breakdown_ms
    assert set(parts) == {"tokenization_ms", "input_transfer_ms", "resource_setup_ms", "other_ms"}
    assert all(value >= 0 for value in parts.values())
    assert sum(parts.values()) == pytest.approx(backend.last_generation.preprocessing_ms)


@pytest.mark.parametrize(
    "settings",
    [
        {"merge_adapter": "yes"},
        {"compile_decode": 1},
        {"adapter_path": "candidate", "compile_decode": True},
    ],
)
def test_invalid_acceleration_configuration_rejected_before_model_loading(settings):
    with pytest.raises(ValueError):
        TransformersFunctionGemmaBackend(**settings)


@pytest.mark.parametrize("compiled", [False, True])
@pytest.mark.parametrize("device", ["cuda:0", "cpu"])
def test_acceleration_loader_merges_in_memory_and_respects_effective_context(
    monkeypatch, compiled, device
):
    import sys

    events = []
    model = SimpleNamespace(
        device=device,
        config=SimpleNamespace(max_position_embeddings=512),
        parameters=lambda: [],
        eval=lambda: events.append("eval"),
    )

    def merge(**kwargs):
        assert kwargs == {"safe_merge": True}
        events.append("merge")
        return model

    cuda = SimpleNamespace(
        is_available=lambda: False,
    )
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=cuda, __version__="test"))
    monkeypatch.setitem(
        sys.modules,
        "psutil",
        SimpleNamespace(
            Process=lambda: SimpleNamespace(memory_info=lambda: SimpleNamespace(rss=1))
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "transformers",
        SimpleNamespace(
            __version__="test",
            AutoProcessor=SimpleNamespace(from_pretrained=lambda *a, **k: object()),
            AutoModelForCausalLM=SimpleNamespace(from_pretrained=lambda *a, **k: model),
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "peft",
        SimpleNamespace(
            PeftModel=SimpleNamespace(
                from_pretrained=lambda *a: SimpleNamespace(merge_and_unload=merge)
            )
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "transformers.generation.configuration_utils",
        SimpleNamespace(CompileConfig=lambda **kwargs: kwargs),
    )
    if compiled and device == "cpu":
        with pytest.raises(PlannerError, match="CUDA-resident"):
            TransformersFunctionGemmaBackend(
                adapter_path="untouched", merge_adapter=True, compile_decode=True
            )
        return
    backend = TransformersFunctionGemmaBackend(
        adapter_path="untouched", merge_adapter=True, compile_decode=compiled
    )
    assert events == ["merge", "eval"]
    assert backend.model_info.adapter_merged is True
    assert backend.model_info.compiled_decode is compiled
    assert backend._max_context_tokens == 512
    if compiled:
        assert backend._generation_options["max_cache_len"] == 512
    else:
        assert backend._generation_options == {}


def test_transformers_backend_rejects_over_budget_prompt_before_device_transfer_or_generation():
    class NoTransferBatch(dict):
        def to(self, device):
            pytest.fail("over-budget prompt must not be transferred to a device")

    class Processor:
        def apply_chat_template(self, *args, **kwargs):
            return NoTransferBatch(input_ids=SimpleNamespace(shape=(1, 1000)))

    backend = object.__new__(TransformersFunctionGemmaBackend)
    backend._processor = Processor()
    backend._max_context_tokens = 1024
    backend._last_generation = "stale generation"
    # No model or torch is attached: the guard must run before accessing either.
    with pytest.raises(
        PlannerError, match=r"1000 prompt tokens \+ 25 reserved output tokens > 1024"
    ):
        backend.generate([{"role": "user", "content": "test"}], [], max_new_tokens=25)
    assert backend.last_generation is None


@pytest.mark.parametrize("budget", [0, -1, True, 1.5])
def test_transformers_backend_rejects_invalid_output_budget(budget):
    backend = object.__new__(TransformersFunctionGemmaBackend)
    with pytest.raises(ValueError, match="positive integer"):
        backend.generate([], [], max_new_tokens=budget)
