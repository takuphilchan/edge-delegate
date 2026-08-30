"""Tests for training configuration and the no-leakage SFT preflight."""

import pytest

from edge_delegate.data import write_dataset
from edge_delegate.model_plugins import builtin_model_plugins
from edge_delegate_lab.models.functiongemma import (
    TrainingConfig,
    add_assistant_generation_mask,
    load_sft_records,
    preflight_sft_data,
    validate_assistant_loss_masks,
)


class LengthTokenizer:
    def apply_chat_template(self, conversation, **kwargs):
        assert kwargs["tools"]
        assert kwargs["add_generation_prompt"] is False
        assert kwargs["tokenize"] is True
        return list(range(len(str(conversation))))


class MaskTokenizer:
    def apply_chat_template(self, conversation, **kwargs):
        del conversation
        assert kwargs["return_assistant_tokens_mask"] is True
        return {
            "input_ids": [1, 10, 11, 12],
            "assistant_masks": [0, 1, 1, 1],
        }

    def decode(self, token_ids, **kwargs):
        del kwargs
        values = {
            1: "prompt",
            10: "<start_function_call>",
            11: "call:submit_plan{}<end_function_call>",
            12: "<start_function_response>",
        }
        return "".join(values[token_id] for token_id in token_ids)

    def get_added_vocab(self):
        return {"<start_function_response>": 12}


def test_training_config_is_strict_and_serializable(tmp_path) -> None:
    mapping = {
        "schema_version": "edge-delegate-training.v1",
        "purpose": "pipeline_smoke",
        "plugin_id": "functiongemma",
        "base_model_id": "google/functiongemma-270m-it",
        "train_file": str(tmp_path / "train.jsonl"),
        "eval_file": str(tmp_path / "eval.jsonl"),
        "output_dir": str(tmp_path / "run"),
    }
    config = TrainingConfig.from_mapping(mapping)
    assert config.max_length == 2048
    assert config.to_dict()["output_dir"] == str(tmp_path / "run")

    with pytest.raises(ValueError, match="unknown training config fields"):
        TrainingConfig.from_mapping({**mapping, "surprise": True})


def test_sft_preflight_validates_exports_and_measures_lengths(tmp_path) -> None:
    dataset_dir = tmp_path / "dataset"
    write_dataset(
        dataset_dir,
        seed=17,
        exporters=(builtin_model_plugins().get("functiongemma"),),
    )
    train = load_sft_records(dataset_dir / "functiongemma-sft-train.jsonl")
    validation = load_sft_records(dataset_dir / "functiongemma-sft-validation.jsonl")

    report = preflight_sft_data(
        train,
        validation,
        max_length=100_000,
        tokenizer=LengthTokenizer(),
    )

    assert report.train_records == 20
    assert report.eval_records == 4
    assert report.group_overlap == ()
    assert report.record_id_overlap == ()
    assert report.maximum_train_tokens is not None
    assert report.truncation_required is False


def test_sft_preflight_rejects_group_leakage(tmp_path) -> None:
    dataset_dir = tmp_path / "dataset"
    write_dataset(
        dataset_dir,
        seed=17,
        exporters=(builtin_model_plugins().get("functiongemma"),),
    )
    train = load_sft_records(dataset_dir / "functiongemma-sft-train.jsonl")

    with pytest.raises(ValueError, match="record leakage"):
        preflight_sft_data(train, train, max_length=2048)


def test_functiongemma_training_mask_wraps_model_turn_without_rendered_text() -> None:
    template = (
        "before\n"
        "        {%- if 'tool_calls' in message and message['tool_calls'] "
        "and message['tool_calls'] is iterable -%}\n"
        "assistant-body\n"
        "            {%- set ns.prev_message_type = 'tool_call' -%}\n"
        "after"
    )
    patched = add_assistant_generation_mask(template)
    assert "{%- generation -%}" in patched
    assert "{%- endgeneration -%}" in patched
    assert "assistant-body" in patched

    with pytest.raises(ValueError, match="already contains"):
        add_assistant_generation_mask(patched)


def test_functiongemma_loss_mask_covers_tool_call_and_stop_sentinel() -> None:
    report = validate_assistant_loss_masks(
        [{"messages": [], "tools": []}],
        MaskTokenizer(),
    )

    assert report == {
        "checked_records": 1,
        "maximum_masked_tokens": 3,
        "minimum_masked_tokens": 3,
        "terminal_special_tokens": ["<start_function_response>"],
    }
