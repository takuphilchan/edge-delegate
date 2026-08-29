"""Training-only mask markers for FunctionGemma's shipped chat template."""

from __future__ import annotations

import re

START_ANCHOR = (
    "        {%- if 'tool_calls' in message and message['tool_calls'] "
    "and message['tool_calls'] is iterable -%}"
)
END_ANCHOR = "            {%- set ns.prev_message_type = 'tool_call' -%}"
GENERATION_MARKER = re.compile(r"{%[-]?\s*generation\s*[-]?%}")
ENDGENERATION_MARKER = re.compile(r"{%[-]?\s*endgeneration\s*[-]?%}")


def add_assistant_generation_mask(chat_template: str) -> str:
    """Mark model turns for loss masking without changing rendered token text."""

    if GENERATION_MARKER.search(chat_template) or ENDGENERATION_MARKER.search(chat_template):
        raise ValueError("chat template already contains generation markers")
    if chat_template.count(START_ANCHOR) != 1 or chat_template.count(END_ANCHOR) != 1:
        raise ValueError("unsupported FunctionGemma chat template; mask anchors changed")
    start = f"{START_ANCHOR}\n            {{%- generation -%}}"
    end = f"            {{%- endgeneration -%}}\n{END_ANCHOR}"
    return chat_template.replace(START_ANCHOR, start, 1).replace(END_ANCHOR, end, 1)
