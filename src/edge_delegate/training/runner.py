"""LoRA training orchestration with reproducibility metadata."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from .config import TrainingConfig
from .preflight import load_sft_records, preflight_sft_data
from .template import add_assistant_generation_mask


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


def train_lora_adapter(
    config: TrainingConfig,
    *,
    preflight_only: bool = False,
) -> dict[str, object]:
    """Preflight and optionally train one local FunctionGemma LoRA adapter."""

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
    if preflight.truncation_required:
        raise ValueError(
            "SFT examples exceed max_length; raise the configured limit or reduce the prompt "
            "instead of silently truncating labels"
        )
    base_report: dict[str, object] = {
        "schema_version": "edge-delegate-training-run.v0",
        "purpose": config.purpose,
        "config": config.to_dict(),
        "preflight": preflight.to_dict(),
        "packages": {
            name: version(name)
            for name in ("accelerate", "datasets", "peft", "torch", "transformers", "trl")
        },
    }
    if preflight_only:
        return {**base_report, "status": "preflight_passed"}
    if not torch.cuda.is_available():
        raise RuntimeError("pilot adapter training requires a CUDA GPU")
    if config.precision == "bf16" and not torch.cuda.is_bf16_supported():
        raise RuntimeError("the selected CUDA GPU does not support BF16 training")

    _ensure_fresh_output(config.output_dir)
    set_seed(config.seed)
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    model = AutoModelForCausalLM.from_pretrained(
        config.base_model_id,
        dtype="auto",
        device_map="auto",
        attn_implementation="eager",
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
        per_device_train_batch_size=config.per_device_train_batch_size,
        per_device_eval_batch_size=config.per_device_eval_batch_size,
        gradient_accumulation_steps=config.gradient_accumulation_steps,
        gradient_checkpointing=config.gradient_checkpointing,
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
        bf16=config.precision == "bf16",
        fp16=config.precision == "fp16",
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
    elapsed_seconds = time.perf_counter() - started
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
        "adapter": {
            "path": str(final_adapter),
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
        "train_metrics": _jsonable(train_result.metrics),
        "eval_metrics": _jsonable(evaluation),
    }
    (config.output_dir / "training-run.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return report
