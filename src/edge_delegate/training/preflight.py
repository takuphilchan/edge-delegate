"""Validate SFT exports before they can reach an optimizer."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from edge_delegate.ir import parse_plan
from edge_delegate.planner.prompts import SUBMIT_PLAN_TOOL

MAX_SFT_LINE_BYTES = 2 * 1024 * 1024


class ChatTemplateTokenizer(Protocol):
    def apply_chat_template(self, conversation, **kwargs): ...


@dataclass(frozen=True, slots=True)
class SFTPreflight:
    train_records: int
    eval_records: int
    train_routes: tuple[str, ...]
    eval_routes: tuple[str, ...]
    train_groups: int
    eval_groups: int
    group_overlap: tuple[str, ...]
    record_id_overlap: tuple[str, ...]
    train_sha256: str
    eval_sha256: str
    maximum_train_tokens: int | None
    maximum_eval_tokens: int | None
    max_length: int
    truncation_required: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _reject_constant(value: str):
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def _without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def load_sft_records(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if len(line.encode("utf-8")) > MAX_SFT_LINE_BYTES:
                raise ValueError(f"{path}:{line_number} exceeds the SFT line size limit")
            if not line.strip():
                continue
            value = json.loads(
                line,
                object_pairs_hook=_without_duplicates,
                parse_constant=_reject_constant,
            )
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} must be a JSON object")
            _validate_sft_record(value, location=f"{path}:{line_number}")
            records.append(value)
    if not records:
        raise ValueError(f"SFT file is empty: {path}")
    record_ids = [str(record["record_id"]) for record in records]
    duplicates = sorted({item for item in record_ids if record_ids.count(item) > 1})
    if duplicates:
        raise ValueError(f"duplicate SFT record_ids in {path}: {', '.join(duplicates)}")
    return records


def _validate_sft_record(record: dict[str, object], *, location: str) -> None:
    required = {"record_id", "group_id", "expected_route", "messages", "tools"}
    missing = required - set(record)
    if missing:
        raise ValueError(f"{location} missing fields: {', '.join(sorted(missing))}")
    if not all(
        isinstance(record[name], str) and record[name] for name in required - {"messages", "tools"}
    ):
        raise ValueError(f"{location} identifiers and expected_route must be non-empty strings")
    messages = record["messages"]
    tools = record["tools"]
    if not isinstance(messages, list) or len(messages) < 3:
        raise ValueError(f"{location}.messages must contain developer, user, and assistant turns")
    if not isinstance(tools, list) or tools != [SUBMIT_PLAN_TOOL]:
        raise ValueError(f"{location}.tools must contain exactly the versioned submit_plan tool")
    roles = [message.get("role") if isinstance(message, dict) else None for message in messages]
    if roles[:2] != ["developer", "user"] or roles[-1] != "assistant":
        raise ValueError(f"{location}.messages has an invalid role sequence")
    assistant = messages[-1]
    tool_calls = assistant.get("tool_calls")
    if not isinstance(tool_calls, list) or len(tool_calls) != 1:
        raise ValueError(f"{location} assistant must contain exactly one tool call")
    call = tool_calls[0]
    function = call.get("function") if isinstance(call, dict) else None
    if not isinstance(function, dict) or function.get("name") != "submit_plan":
        raise ValueError(f"{location} assistant must call submit_plan")
    arguments = function.get("arguments")
    plan_json = arguments.get("plan_json") if isinstance(arguments, dict) else None
    if not isinstance(plan_json, str):
        raise ValueError(f"{location} submit_plan.plan_json must be a string")
    plan = parse_plan(plan_json)
    if plan.request_id != record["record_id"]:
        raise ValueError(f"{location} plan request_id does not match record_id")
    if plan.route.value != record["expected_route"]:
        raise ValueError(f"{location} plan route does not match expected_route")


def _fingerprint(records: list[dict[str, object]]) -> str:
    digest = hashlib.sha256()
    for record in records:
        encoded = json.dumps(
            record,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _token_length(record: dict[str, object], tokenizer: ChatTemplateTokenizer) -> int:
    encoded = tokenizer.apply_chat_template(
        record["messages"],
        tools=record["tools"],
        add_generation_prompt=False,
        tokenize=True,
    )
    if isinstance(encoded, Mapping):
        encoded = encoded["input_ids"]
    if encoded and isinstance(encoded[0], list):
        encoded = encoded[0]
    return len(encoded)


def preflight_sft_data(
    train_records: list[dict[str, object]],
    eval_records: list[dict[str, object]],
    *,
    max_length: int,
    tokenizer: ChatTemplateTokenizer | None = None,
) -> SFTPreflight:
    train_ids = {str(record["record_id"]) for record in train_records}
    eval_ids = {str(record["record_id"]) for record in eval_records}
    train_groups = {str(record["group_id"]) for record in train_records}
    eval_groups = {str(record["group_id"]) for record in eval_records}
    id_overlap = tuple(sorted(train_ids & eval_ids))
    group_overlap = tuple(sorted(train_groups & eval_groups))
    if id_overlap:
        raise ValueError(f"train/eval record leakage: {', '.join(id_overlap)}")
    if group_overlap:
        raise ValueError(f"train/eval group leakage: {', '.join(group_overlap)}")
    train_lengths = (
        [_token_length(record, tokenizer) for record in train_records] if tokenizer else []
    )
    eval_lengths = (
        [_token_length(record, tokenizer) for record in eval_records] if tokenizer else []
    )
    max_train = max(train_lengths, default=None)
    max_eval = max(eval_lengths, default=None)
    truncation_required = any(
        length is not None and length > max_length for length in (max_train, max_eval)
    )
    return SFTPreflight(
        train_records=len(train_records),
        eval_records=len(eval_records),
        train_routes=tuple(sorted({str(record["expected_route"]) for record in train_records})),
        eval_routes=tuple(sorted({str(record["expected_route"]) for record in eval_records})),
        train_groups=len(train_groups),
        eval_groups=len(eval_groups),
        group_overlap=group_overlap,
        record_id_overlap=id_overlap,
        train_sha256=_fingerprint(train_records),
        eval_sha256=_fingerprint(eval_records),
        maximum_train_tokens=max_train,
        maximum_eval_tokens=max_eval,
        max_length=max_length,
        truncation_required=truncation_required,
    )
