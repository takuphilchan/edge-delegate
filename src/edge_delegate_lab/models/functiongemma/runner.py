"""FunctionGemma LoRA orchestration with reproducibility and compute metadata."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from edge_delegate import __version__
from edge_delegate.model_plugins import (
    MODEL_PLUGIN_API_VERSION,
    ComputeRequest,
    ComputeTelemetry,
    ModelArtifactManifest,
    ModelComputeCapabilities,
    conservative_compute_plan,
    detect_hardware_inventory,
)

from .config import TrainingConfig
from .preflight import load_sft_records, preflight_sft_data
from .template import add_assistant_generation_mask, validate_assistant_loss_masks


def _jsonable(value: object) -> object:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return str(value)


def _ensure_fresh_output(path: Path) -> None:
    if path.exists() and any(path.iterdir()):
        raise ValueError(f"training output directory is not empty: {path}; use a new run directory")
    path.mkdir(parents=True, exist_ok=True)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def train_lora_adapter(
    config: TrainingConfig,
    *,
    compute_capabilities: ModelComputeCapabilities,
    preflight_only: bool = False,
) -> dict[str, object]:
    """Preflight and optionally train one plugin-owned LoRA adapter."""

    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig
        from transformers import AutoModelForCausalLM, AutoTokenizer, set_seed
        from trl import SFTConfig, SFTTrainer
    except ImportError as exc:
        raise RuntimeError(
            "adapter training requires: python -m pip install -e '.[training]'"
        ) from exc

    train_records = load_sft_records(config.train_file)
    eval_records = load_sft_records(config.eval_file)
    tokenizer = AutoTokenizer.from_pretrained(config.base_model_id)
    if not isinstance(tokenizer.chat_template, str):
        raise ValueError("base model does not provide a training chat template")
    tokenizer.chat_template = add_assistant_generation_mask(tokenizer.chat_template)
    preflight = preflight_sft_data(
        train_records,
        eval_records,
        max_length=config.max_length,
        tokenizer=tokenizer,
    )
    assistant_loss_mask = validate_assistant_loss_masks(
        [*train_records, *eval_records],
        tokenizer,
    )
    if preflight.truncation_required:
        raise ValueError(
            "SFT examples exceed max_length; raise the configured limit or reduce the prompt "
            "instead of silently truncating labels"
        )
    inventory = detect_hardware_inventory()
    compute_plan = conservative_compute_plan(
        inventory,
        compute_capabilities,
        ComputeRequest(
            effective_batch_size=(
                config.per_device_train_batch_size * config.gradient_accumulation_steps
            ),
            max_context_tokens=config.max_length,
            requested_precision=config.precision,
            requested_attention_backend=config.attention_backend,
            requested_gradient_checkpointing=config.gradient_checkpointing,
            maximum_vram_fraction=config.maximum_vram_fraction,
        ),
    )
    base_report: dict[str, object] = {
        "schema_version": "edge-delegate-training-run.v1",
        "purpose": config.purpose,
        "plugin_id": config.plugin_id,
        "config": config.to_dict(),
        "preflight": {
            **preflight.to_dict(),
            "assistant_loss_mask": assistant_loss_mask,
        },
        "hardware_inventory": asdict(inventory),
        "resolved_compute_plan": compute_plan.to_dict(),
        "packages": {
            name: version(name)
            for name in ("accelerate", "datasets", "peft", "torch", "transformers", "trl")
        },
    }
    if preflight_only:
        return {**base_report, "status": "preflight_passed"}
    if not torch.cuda.is_available():
        raise RuntimeError("pilot adapter training requires a CUDA GPU")
    if compute_plan.precision == "bf16" and not torch.cuda.is_bf16_supported():
        raise RuntimeError("the selected CUDA GPU does not support BF16 training")

    _ensure_fresh_output(config.output_dir)
    set_seed(config.seed)
    torch.cuda.empty_cache()
    torch.cuda.set_per_process_memory_fraction(compute_plan.maximum_vram_fraction, device=0)
    torch.cuda.reset_peak_memory_stats()
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    model_dtype = {
        "bf16": torch.bfloat16,
        "fp16": torch.float16,
        "fp32": torch.float32,
    }[compute_plan.precision]
    model = AutoModelForCausalLM.from_pretrained(
        config.base_model_id,
        dtype=model_dtype,
        device_map="auto",
        attn_implementation=compute_plan.attention_backend,
    )
    model_revision = getattr(model.config, "_commit_hash", None)
    peft_config = LoraConfig(
        task_type="CAUSAL_LM",
        target_modules="all-linear",
        r=config.lora_rank,
        lora_alpha=config.lora_alpha,
        lora_dropout=config.lora_dropout,
        bias="none",
    )
    training_args = SFTConfig(
        output_dir=str(config.output_dir),
        max_length=config.max_length,
        packing=False,
        assistant_only_loss=True,
        num_train_epochs=config.epochs,
        max_steps=config.max_steps,
        per_device_train_batch_size=compute_plan.microbatch_size,
        per_device_eval_batch_size=config.per_device_eval_batch_size,
        gradient_accumulation_steps=compute_plan.gradient_accumulation_steps,
        gradient_checkpointing=compute_plan.gradient_checkpointing,
        dataloader_num_workers=compute_plan.dataloader_workers,
        dataloader_pin_memory=compute_plan.pin_memory,
        optim="adamw_torch_fused",
        logging_steps=config.logging_steps,
        logging_first_step=True,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=config.save_total_limit,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        learning_rate=config.learning_rate,
        lr_scheduler_type="constant",
        bf16=compute_plan.precision == "bf16",
        fp16=compute_plan.precision == "fp16",
        seed=config.seed,
        data_seed=config.seed,
        report_to="tensorboard",
        run_name=config.output_dir.name,
        push_to_hub=False,
    )
    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=Dataset.from_list(train_records),
        eval_dataset=Dataset.from_list(eval_records),
        processing_class=tokenizer,
        peft_config=peft_config,
    )
    train_result = trainer.train()
    evaluation = trainer.evaluate()
    final_adapter = config.output_dir / "final-adapter"
    trainer.save_model(str(final_adapter))
    tokenizer.save_pretrained(final_adapter)
    if not isinstance(model_revision, str) or not model_revision:
        raise RuntimeError("base model revision could not be resolved for the artifact manifest")
    tokenizer_files = {}
    for name in (
        "added_tokens.json",
        "chat_template.jinja",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
    ):
        path = final_adapter / name
        if path.is_file():
            tokenizer_files[name] = _file_sha256(path)
    for required in ("tokenizer.json", "tokenizer_config.json"):
        if required not in tokenizer_files:
            raise RuntimeError(f"saved adapter is missing {required}")
    adapter_files = {}
    for name in ("adapter_config.json", "adapter_model.safetensors"):
        path = final_adapter / name
        if not path.is_file():
            raise RuntimeError(f"saved adapter is missing {name}")
        adapter_files[name] = _file_sha256(path)
    artifact_manifest = ModelArtifactManifest(
        artifact_id=config.output_dir.name,
        plugin_id="functiongemma",
        plugin_api_version=MODEL_PLUGIN_API_VERSION,
        plugin_package_version=__version__,
        base_model_id=config.base_model_id,
        base_model_revision=model_revision,
        plan_protocol_id="functiongemma-submit-plan",
        plan_protocol_version="1",
        plan_schema="plan-ir.v0",
        tokenizer_files=tokenizer_files,
        adapter_method="lora",
        adapter_format="peft",
        adapter_files=adapter_files,
        train_dataset_sha256=preflight.train_sha256,
        validation_dataset_sha256=preflight.eval_sha256,
        training_recipe_id="transformers-peft-sft",
        training_recipe_version="1",
        max_context_tokens=config.max_length,
        supported_precisions=(compute_plan.precision,),
    )
    artifact_manifest_path = final_adapter / "edge-delegate-artifact.json"
    artifact_manifest.write(artifact_manifest_path)
    elapsed_seconds = time.perf_counter() - started
    train_metrics = _jsonable(train_result.metrics)
    tokens_per_second_value = train_result.metrics.get("train_tokens_per_second")
    tokens_per_second = (
        float(tokens_per_second_value)
        if isinstance(tokens_per_second_value, (int, float))
        else None
    )
    telemetry = ComputeTelemetry(
        duration_seconds=elapsed_seconds,
        peak_gpu_allocated_bytes=int(torch.cuda.max_memory_allocated()),
        peak_gpu_reserved_bytes=int(torch.cuda.max_memory_reserved()),
        peak_cpu_rss_bytes=None,
        tokens_per_second=tokens_per_second,
    )
    report = {
        **base_report,
        "status": "completed",
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "base_model_revision": model_revision,
        "hardware": {
            "device_name": torch.cuda.get_device_name(0),
            "peak_gpu_memory_bytes": int(torch.cuda.max_memory_allocated()),
        },
        "compute_telemetry": telemetry.to_dict(),
        "adapter": {
            "path": str(final_adapter),
            "manifest": str(artifact_manifest_path),
            "target_modules": "all-linear",
            "trainable_parameters": sum(
                parameter.numel()
                for parameter in trainer.model.parameters()
                if parameter.requires_grad
            ),
            "total_parameters": sum(parameter.numel() for parameter in trainer.model.parameters()),
        },
        "duration_seconds": elapsed_seconds,
        "checkpoint_selection": {
            "best_checkpoint": trainer.state.best_model_checkpoint,
            "best_eval_loss": trainer.state.best_metric,
            "completed_epoch": trainer.state.epoch,
        },
        "train_metrics": train_metrics,
        "eval_metrics": _jsonable(evaluation),
    }
    (config.output_dir / "training-run.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return report
