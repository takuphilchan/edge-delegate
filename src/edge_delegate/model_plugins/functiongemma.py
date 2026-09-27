"""Built-in FunctionGemma model plugin using the existing strict adapter."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from edge_delegate import __version__
from edge_delegate.contracts import CapabilityCard, DeviceState, PlanIR, PlanningRequest, Policy
from edge_delegate.ir import canonicalize_plan
from edge_delegate.planner import (
    DEFAULT_MODEL_ID,
    FunctionCallFormatError,
    FunctionGemmaPlanner,
    FunctionPlanError,
    PlannerContext,
    PlannerOutputError,
    TransformersFunctionGemmaBackend,
    select_capabilities,
)
from edge_delegate.planner.prompts import (
    SUBMIT_PLAN_TOOL,
    build_planner_messages,
    sft_assistant_message,
)

from .api import ArtifactContract, ModelPluginDescriptor
from .artifact import ModelArtifactManifest
from .compute import ModelComputeCapabilities

FUNCTIONGEMMA_PLUGIN_ID = "functiongemma"
FUNCTIONGEMMA_PROTOCOL_ID = "functiongemma-submit-plan"


@dataclass(slots=True)
class FunctionGemmaDiagnosticSession:
    """Expose FunctionGemma telemetry through the model-neutral doctor contract."""

    backend: object
    planner: FunctionGemmaPlanner
    retrieval_limit: int

    @property
    def model_info(self) -> Mapping[str, object]:
        return self.backend.model_info.to_dict()

    def selected_capability_ids(
        self,
        request: PlanningRequest,
        context: PlannerContext,
    ) -> tuple[str, ...]:
        return tuple(
            card.capability_id
            for card in select_capabilities(request, context, limit=self.retrieval_limit)
        )

    def last_generation(self, *, include_raw_output: bool) -> Mapping[str, object] | None:
        generation = self.backend.last_generation
        if generation is None:
            return None
        return generation.to_dict(include_raw_output=include_raw_output)

    def classify_error(self, error: Exception) -> str:
        if isinstance(error, FunctionCallFormatError):
            return "output_format"
        if isinstance(error, (FunctionPlanError, PlannerOutputError)):
            return "invalid_plan_ir"
        return "inference_error"


class FunctionGemmaModelPlugin:
    descriptor = ModelPluginDescriptor(
        plugin_id=FUNCTIONGEMMA_PLUGIN_ID,
        package_version=__version__,
        display_name="Google FunctionGemma",
        supported_protocols=(FUNCTIONGEMMA_PROTOCOL_ID,),
        artifact_contracts=(
            ArtifactContract(
                plan_protocol_id=FUNCTIONGEMMA_PROTOCOL_ID,
                plan_protocol_version="1",
                plan_schema="plan-ir.v0",
                adapter_method="lora",
                adapter_format="peft",
                required_adapter_files=("adapter_config.json", "adapter_model.safetensors"),
                required_tokenizer_files=("tokenizer.json", "tokenizer_config.json"),
            ),
        ),
    )
    compute_capabilities = ModelComputeCapabilities(
        supported_precisions=("bf16", "fp16", "fp32"),
        supported_attention_backends=("eager", "sdpa"),
        supports_gradient_checkpointing=True,
        supports_quantized_training=False,
        supports_peft=True,
        maximum_context_tokens=2048,
    )

    def create_planner(
        self,
        *,
        artifact_path: str | None,
        settings: Mapping[str, object],
    ) -> FunctionGemmaPlanner:
        backend, retrieval_limit, max_new_tokens = self._create_backend(
            artifact_path=artifact_path,
            settings=settings,
        )
        return FunctionGemmaPlanner(
            backend=backend,
            retrieval_limit=retrieval_limit,
            max_new_tokens=max_new_tokens,
        )

    def create_diagnostic_session(
        self,
        *,
        artifact_path: str | None,
        settings: Mapping[str, object],
    ) -> FunctionGemmaDiagnosticSession:
        backend, retrieval_limit, max_new_tokens = self._create_backend(
            artifact_path=artifact_path,
            settings=settings,
        )
        planner = FunctionGemmaPlanner(
            backend=backend,
            retrieval_limit=retrieval_limit,
            max_new_tokens=max_new_tokens,
        )
        return FunctionGemmaDiagnosticSession(backend, planner, retrieval_limit)

    def _create_backend(
        self,
        *,
        artifact_path: str | None,
        settings: Mapping[str, object],
    ) -> tuple[TransformersFunctionGemmaBackend, int, int]:
        allowed = {
            "allow_legacy_artifact",
            "cpu_threads",
            "merge_adapter",
            "compile_decode",
            "device_map",
            "dtype",
            "max_new_tokens",
            "model_id",
            "retrieval_limit",
        }
        unknown = set(settings) - allowed
        if unknown:
            raise ValueError(f"unknown FunctionGemma plugin settings: {', '.join(sorted(unknown))}")
        configured_model_id = settings.get("model_id")
        model_id = DEFAULT_MODEL_ID if configured_model_id is None else configured_model_id
        device_map = settings.get("device_map", "auto")
        dtype = settings.get("dtype", "auto")
        retrieval_limit = settings.get("retrieval_limit", 8)
        max_new_tokens = settings.get("max_new_tokens", 1024)
        allow_legacy = settings.get("allow_legacy_artifact", True)
        if not all(isinstance(value, str) and value for value in (model_id, device_map, dtype)):
            raise ValueError("FunctionGemma model_id, device_map, and dtype must be strings")
        if not isinstance(retrieval_limit, int) or isinstance(retrieval_limit, bool):
            raise ValueError("FunctionGemma retrieval_limit must be an integer")
        if not isinstance(max_new_tokens, int) or isinstance(max_new_tokens, bool):
            raise ValueError("FunctionGemma max_new_tokens must be an integer")
        if retrieval_limit < 1 or max_new_tokens < 1:
            raise ValueError("FunctionGemma retrieval and generation limits must be positive")
        if not isinstance(allow_legacy, bool):
            raise ValueError("FunctionGemma allow_legacy_artifact must be boolean")
        revision = None
        max_context_tokens = self.compute_capabilities.maximum_context_tokens
        if artifact_path is not None:
            root = Path(artifact_path)
            manifest_path = root / "edge-delegate-artifact.json"
            if manifest_path.is_file():
                manifest = ModelArtifactManifest.read(manifest_path)
                manifest.verify_files(root, descriptor=self.descriptor)
                if configured_model_id is not None and model_id != manifest.base_model_id:
                    raise ValueError("configured base model does not match the artifact manifest")
                model_id = manifest.base_model_id
                revision = manifest.base_model_revision
                max_context_tokens = min(max_context_tokens, manifest.max_context_tokens)
            elif not allow_legacy:
                raise ValueError("adapter is missing edge-delegate-artifact.json")
        backend = TransformersFunctionGemmaBackend(
            model_id=model_id,
            adapter_path=artifact_path,
            device_map=device_map,
            dtype=dtype,
            revision=revision,
            max_context_tokens=max_context_tokens,
            stop_on_tool_end=getattr(self, "stop_on_tool_end", False),
            cpu_threads=settings.get("cpu_threads"),
            merge_adapter=settings.get("merge_adapter", False),
            compile_decode=settings.get("compile_decode", False),
        )
        return backend, retrieval_limit, max_new_tokens

    def export_training_data(
        self,
        *,
        splits: Mapping[str, Sequence[Mapping[str, object]]],
        output_dir: Path,
    ) -> Mapping[str, object]:
        files: dict[str, str] = {}
        for name, records in sorted(splits.items()):
            filename = f"functiongemma-sft-{name}.jsonl"
            path = output_dir / filename
            with path.open("w", encoding="utf-8", newline="\n") as handle:
                for record in records:
                    handle.write(
                        json.dumps(
                            self._training_record(record),
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                        + "\n"
                    )
            files[name] = filename
        return {
            "plugin_id": self.descriptor.plugin_id,
            "format": "functiongemma-chat-sft.v1",
            "prompt_version": getattr(self, "prompt_version", "functiongemma-plan-v0"),
            "loss_target": "assistant_tool_call_only",
            "files": files,
        }

    @staticmethod
    def _training_record(record: Mapping[str, object]) -> dict[str, object]:
        request = PlanningRequest.from_dict(record["request"])
        raw_cards = record["capabilities"]
        if not isinstance(raw_cards, list):
            raise ValueError("training record capabilities must be a list")
        cards = tuple(
            CapabilityCard.from_dict(card, f"$.capabilities[{index}]")
            for index, card in enumerate(raw_cards)
        )
        state = DeviceState.from_dict(record["state"])
        policy = Policy.from_dict(record["policy"])
        plan = PlanIR.from_dict(record["expected_plan"])
        messages: list[dict[str, object]] = list(
            build_planner_messages(request, state, policy, cards)
        )
        messages.append(sft_assistant_message(canonicalize_plan(plan)))
        metadata = record["metadata"]
        if not isinstance(metadata, Mapping):
            raise ValueError("training record metadata must be an object")
        group_id = "|".join(
            str(metadata[name]) for name in ("template_id", "paraphrase_cluster", "device_family")
        )
        return {
            "record_id": record["record_id"],
            "group_id": group_id,
            "expected_route": plan.route.value,
            "messages": messages,
            "tools": [SUBMIT_PLAN_TOOL],
        }

    def train_from_config(
        self,
        *,
        config_path: Path,
        preflight_only: bool,
    ) -> Mapping[str, object]:
        from edge_delegate_lab.models.functiongemma import TrainingConfig, train_lora_adapter

        config = TrainingConfig.from_yaml(config_path)
        if config.plugin_id != self.descriptor.plugin_id:
            raise ValueError(
                f"training config selects {config.plugin_id!r}, not {self.descriptor.plugin_id!r}"
            )
        return train_lora_adapter(
            config,
            compute_capabilities=self.compute_capabilities,
            preflight_only=preflight_only,
        )


plugin = FunctionGemmaModelPlugin()
