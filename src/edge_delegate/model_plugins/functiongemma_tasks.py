"""Compact FunctionGemma task protocol; incompatible with full-plan adapters."""

import json
import re
import time
from dataclasses import dataclass, replace

from edge_delegate.planner import PlannerOutputError
from edge_delegate.planner.numeric import (
    DECIMAL_NUMERIC_POLICY,
    LEGACY_NUMERIC_POLICY,
    extract_numeric_literal,
    validate_numeric_policy,
)
from edge_delegate.planner.prompts import FUNCTIONGEMMA_DEVELOPER_MESSAGE
from edge_delegate.planner.tasks import BoundedPlanner, TaskDecision

from .functiongemma import FunctionGemmaDiagnosticSession, FunctionGemmaModelPlugin

TASK_TOOL = {
    "type": "function",
    "function": {
        "name": "select_task",
        "description": "Select read_temperature, display_number, show_temperature, clarify, or deny. No device execution.",
        "parameters": {
            "type": "object",
            "properties": {
                "decision_json": {
                    "type": "string",
                    "description": 'JSON {"task":"task ID","parameters":{}}. display_number requires numeric value. Otherwise parameters is empty.',
                }
            },
            "required": ["decision_json"],
        },
    },
}
TASK_CALL = re.compile(
    r"\A\s*<start_function_call>call:select_task\{decision_json:<escape>(.*?)<escape>\}<end_function_call>\s*\Z",
    re.S,
)


@dataclass(slots=True)
class TaskDiagnosticSession(FunctionGemmaDiagnosticSession):
    output_token_limit: int = 96
    numeric_policy: str = LEGACY_NUMERIC_POLICY
    numeric_diagnostics: dict | None = None

    @property
    def model_info(self):
        return {**self.backend.model_info.to_dict(), "numeric_policy": self.numeric_policy}

    def last_generation(self, *, include_raw_output):
        result = FunctionGemmaDiagnosticSession.last_generation(
            self, include_raw_output=include_raw_output
        )
        return (
            None
            if result is None
            else {
                **result,
                "numeric_policy": self.numeric_policy,
                "numeric_check": (self.numeric_diagnostics or {}).get("numeric_check"),
                "decision_stage": (self.numeric_diagnostics or {}).get("decision_stage"),
                "decision_error": (self.numeric_diagnostics or {}).get("decision_error"),
                **(
                    {"parsed_decision": (self.numeric_diagnostics or {}).get("parsed_decision")}
                    if include_raw_output
                    else {}
                ),
            }
        )

    def warmup(self):
        """Prepare compiled kernels before accepting requests; never invoke devices."""
        if not self.backend.model_info.compiled_decode:
            return {"performed": False, "device_actions": 0, "latency_ms": 0.0}
        started = time.perf_counter()
        for text in ("Read the temperature.", "Display -3.5."):
            self.backend.generate(
                messages(text), [TASK_TOOL], max_new_tokens=self.output_token_limit
            )
        return {
            "performed": True,
            "device_actions": 0,
            "latency_ms": (time.perf_counter() - started) * 1000,
        }


def messages(text):
    return [
        {"role": "developer", "content": FUNCTIONGEMMA_DEVELOPER_MESSAGE},
        {"role": "user", "content": text},
    ]


def parse_decision(text):
    match = TASK_CALL.fullmatch(text)
    if match is None:
        raise PlannerOutputError("expected exactly one select_task call")

    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise PlannerOutputError("duplicate task decision field")
            value[key] = item
        return value

    try:
        return TaskDecision.from_dict(json.loads(match[1], object_pairs_hook=pairs))
    except ValueError as exc:
        raise PlannerOutputError("malformed task decision") from exc


class FunctionGemmaTasksPlugin(FunctionGemmaModelPlugin):
    prompt_version = "functiongemma-task-v1"
    stop_on_tool_end = True
    descriptor = replace(
        FunctionGemmaModelPlugin.descriptor,
        plugin_id="functiongemma-tasks",
        display_name="FunctionGemma bounded tasks",
        supported_protocols=("functiongemma-task",),
        artifact_contracts=tuple(
            replace(contract, plan_protocol_id="functiongemma-task")
            for contract in FunctionGemmaModelPlugin.descriptor.artifact_contracts
        ),
    )

    def create_diagnostic_session(self, *, artifact_path, settings):
        settings = dict(settings)
        numeric_policy = validate_numeric_policy(
            settings.pop("numeric_policy", LEGACY_NUMERIC_POLICY)
        )
        if settings.get("allow_legacy_artifact") is True:
            raise ValueError("compact task adapters require a matching manifest")
        backend, retrieval, tokens = self._create_backend(
            artifact_path=artifact_path,
            settings={
                "max_new_tokens": 96,
                "cpu_threads": 4,
                **settings,
                "allow_legacy_artifact": False,
            },
        )

        numeric_diagnostics = {}

        def checked(request, raw):
            numeric_diagnostics.clear()
            numeric_diagnostics["decision_stage"] = "parse"
            try:
                decision = parse_decision(raw)
            except PlannerOutputError:
                numeric_diagnostics["decision_error"] = "invalid_task_encoding"
                raise
            numeric_diagnostics["parsed_decision"] = decision.to_dict()
            numeric_diagnostics["decision_stage"] = "task_contract"
            if decision.task == "display_number":
                extraction = extract_numeric_literal(request.text, policy=numeric_policy)
                value = extraction.value
                numeric_diagnostics["numeric_check"] = extraction.reason or "accepted"
                if value is None:
                    numeric_diagnostics["decision_stage"] = "numeric_clarification"
                    return TaskDecision("clarify")
                if numeric_policy == DECIMAL_NUMERIC_POLICY and type(
                    decision.parameters.get("value")
                ) not in {int, float}:
                    numeric_diagnostics["decision_error"] = "model_value_type"
                    raise PlannerOutputError("display_number requires a numeric model value")
                if decision.parameters != {"value": value}:
                    numeric_diagnostics["decision_error"] = "model_literal_mismatch"
                    raise PlannerOutputError("model value does not match explicit request value")
                if numeric_policy == DECIMAL_NUMERIC_POLICY:
                    # Use the checked representation, including normalized negative zero.
                    numeric_diagnostics["decision_stage"] = "checked_decision"
                    return TaskDecision("display_number", {"value": value})
            numeric_diagnostics["decision_stage"] = "checked_decision"
            return decision

        def decide(request, context):
            numeric_diagnostics.clear()
            return checked(
                request,
                backend.generate(messages(request.text), [TASK_TOOL], max_new_tokens=tokens),
            )

        def decide_batch(requests, contexts):
            # Only text enters the model prompt; compile every context separately.
            texts = list(dict.fromkeys(request.text for request in requests))
            raw_outputs = backend.generate_batch(
                [messages(text) for text in texts], [TASK_TOOL], max_new_tokens=tokens
            )
            by_text = dict(zip(texts, raw_outputs, strict=True))
            decisions = []
            for request in requests:
                try:
                    decisions.append(checked(request, by_text[request.text]))
                except Exception as exc:
                    decisions.append(exc)
            return decisions

        return TaskDiagnosticSession(
            backend,
            BoundedPlanner(decide, decide_batch=decide_batch),
            retrieval,
            tokens,
            numeric_policy,
            numeric_diagnostics,
        )

    def create_planner(self, *, artifact_path, settings):
        return self.create_diagnostic_session(
            artifact_path=artifact_path, settings=settings
        ).planner

    def train_from_config(self, *, config_path, preflight_only):
        from edge_delegate_lab.models.functiongemma import TrainingConfig, train_lora_adapter

        config = TrainingConfig.from_yaml(config_path)
        if config.plugin_id != self.descriptor.plugin_id or not config.base_model_revision:
            raise ValueError(
                "compact training requires its plugin ID and pinned base_model_revision"
            )
        if not config.task_validation_file:
            raise ValueError("compact training requires canonical task_validation_file")
        from pathlib import Path

        from edge_delegate.data import validate_records
        from edge_delegate_lab.jsonio import load_jsonl

        canonical = load_jsonl(Path(config.task_validation_file))
        exported = load_jsonl(config.eval_file)
        validate_records(canonical)
        if {row["record_id"] for row in canonical} != {row["record_id"] for row in exported}:
            raise ValueError("canonical validation cases must match SFT validation export")
        report = train_lora_adapter(
            config,
            compute_capabilities=self.compute_capabilities,
            preflight_only=preflight_only,
            plan_protocol_id="functiongemma-task",
        )
        if not preflight_only:
            from edge_delegate_lab.models.selection import select_task_checkpoint

            report["task_selection"] = select_task_checkpoint(
                self, config.output_dir, config.task_validation_file
            )
        return report

    @staticmethod
    def _training_record(record):
        decision = TaskDecision.from_dict(record["expected_task"])
        turns = messages(record["request"]["text"])
        turns.append(
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "type": "function",
                        "function": {
                            "name": "select_task",
                            "arguments": {
                                "decision_json": json.dumps(
                                    decision.to_dict(), separators=(",", ":")
                                )
                            },
                        },
                    }
                ],
            }
        )
        return {
            "record_id": record["record_id"],
            "group_id": record["metadata"]["scenario_group"],
            "expected_route": record["expected_plan"]["route"],
            "messages": turns,
            "tools": [TASK_TOOL],
        }


plugin = FunctionGemmaTasksPlugin()
