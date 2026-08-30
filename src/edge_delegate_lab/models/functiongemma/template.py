"""Loss-mask markers for FunctionGemma's shipped training chat template."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Protocol

START_ANCHOR = (
    "        {%- if 'tool_calls' in message and message['tool_calls'] "
    "and message['tool_calls'] is iterable -%}"
)
END_ANCHOR = "            {%- set ns.prev_message_type = 'tool_call' -%}"
GENERATION_MARKER = re.compile(r"{%[-]?\s*generation\s*[-]?%}")
ENDGENERATION_MARKER = re.compile(r"{%[-]?\s*endgeneration\s*[-]?%}")


class AssistantMaskTokenizer(Protocol):
    def apply_chat_template(self, conversation, **kwargs): ...

    def decode(self, token_ids, **kwargs) -> str: ...

    def get_added_vocab(self) -> Mapping[str, int]: ...


def add_assistant_generation_mask(chat_template: str) -> str:
    """Mark model turns for loss masking without changing rendered token text."""

    if GENERATION_MARKER.search(chat_template) or ENDGENERATION_MARKER.search(chat_template):
        raise ValueError("chat template already contains generation markers")
    if chat_template.count(START_ANCHOR) != 1 or chat_template.count(END_ANCHOR) != 1:
        raise ValueError("unsupported FunctionGemma chat template; mask anchors changed")
    start = f"{START_ANCHOR}\n            {{%- generation -%}}"
    end = f"            {{%- endgeneration -%}}\n{END_ANCHOR}"
    return chat_template.replace(START_ANCHOR, start, 1).replace(END_ANCHOR, end, 1)


def validate_assistant_loss_masks(
    records: Sequence[Mapping[str, object]],
    tokenizer: AssistantMaskTokenizer,
) -> dict[str, object]:
    """Prove that each tool-call target and its stop sentinel contribute to loss."""

    added_token_ids = set(tokenizer.get_added_vocab().values())
    masked_counts: list[int] = []
    stop_tokens: set[str] = set()
    for index, record in enumerate(records):
        output = tokenizer.apply_chat_template(
            record["messages"],
            tools=record["tools"],
            add_generation_prompt=False,
            tokenize=True,
            return_dict=True,
            return_assistant_tokens_mask=True,
        )
        if not isinstance(output, Mapping):
            raise ValueError("tokenizer did not return assistant-mask metadata")
        input_ids = output.get("input_ids")
        assistant_mask = output.get("assistant_masks")
        if not isinstance(input_ids, list) or not isinstance(assistant_mask, list):
            raise ValueError("tokenizer assistant-mask metadata must contain token lists")
        if len(input_ids) != len(assistant_mask):
            raise ValueError("tokenizer input and assistant-mask lengths differ")
        masked_ids = [
            token_id
            for token_id, selected in zip(input_ids, assistant_mask, strict=True)
            if selected
        ]
        if not masked_ids:
            raise ValueError(f"record {index} has no assistant tokens selected for loss")
        masked_text = tokenizer.decode(masked_ids, skip_special_tokens=False)
        if "<start_function_call>" not in masked_text or "<end_function_call>" not in masked_text:
            raise ValueError(f"record {index} loss mask does not cover the complete tool call")
        terminal_id = next(
            (
                token_id
                for token_id in reversed(masked_ids)
                if tokenizer.decode([token_id], skip_special_tokens=False).strip()
            ),
            None,
        )
        if terminal_id is None or terminal_id not in added_token_ids:
            raise ValueError(f"record {index} loss mask does not end on a stop sentinel")
        masked_counts.append(len(masked_ids))
        stop_tokens.add(tokenizer.decode([terminal_id], skip_special_tokens=False))
    return {
        "checked_records": len(records),
        "minimum_masked_tokens": min(masked_counts, default=0),
        "maximum_masked_tokens": max(masked_counts, default=0),
        "terminal_special_tokens": sorted(stop_tokens),
    }
