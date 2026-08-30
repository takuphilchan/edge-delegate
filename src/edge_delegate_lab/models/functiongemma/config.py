"""Strict configuration for the FunctionGemma parameter-efficient training recipe."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TrainingConfig:
    schema_version: str
    purpose: str
    plugin_id: str
    base_model_id: str
    train_file: Path
    eval_file: Path
    output_dir: Path
    seed: int = 17
    max_length: int = 2048
    epochs: float = 8.0
    max_steps: int = -1
    learning_rate: float = 5e-5
    per_device_train_batch_size: int = 1
    per_device_eval_batch_size: int = 1
    gradient_accumulation_steps: int = 4
    gradient_checkpointing: bool = False
    precision: str = "bf16"
    attention_backend: str = "eager"
    maximum_vram_fraction: float = 0.88
    lora_rank: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    logging_steps: int = 1
    save_total_limit: int = 2

    @classmethod
    def from_mapping(cls, value: object) -> TrainingConfig:
        if not isinstance(value, dict):
            raise ValueError("training config must be a mapping")
        allowed = set(cls.__dataclass_fields__)
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"unknown training config fields: {', '.join(sorted(unknown))}")
        try:
            config = cls(
                **{
                    **value,
                    "train_file": Path(value["train_file"]),
                    "eval_file": Path(value["eval_file"]),
                    "output_dir": Path(value["output_dir"]),
                }
            )
        except KeyError as exc:
            raise ValueError(f"missing training config field: {exc.args[0]}") from exc
        config._validate()
        return config

    @classmethod
    def from_yaml(cls, path: Path) -> TrainingConfig:
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError(
                "training config support requires the training extra: "
                "python -m pip install -e '.[training]'"
            ) from exc
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls.from_mapping(value)

    def _validate(self) -> None:
        if self.schema_version != "edge-delegate-training.v1":
            raise ValueError("unsupported training config schema_version")
        if self.purpose not in {"pipeline_smoke", "pilot_adapter"}:
            raise ValueError("purpose must be pipeline_smoke or pilot_adapter")
        if not self.plugin_id.strip() or not self.base_model_id.strip():
            raise ValueError("plugin_id and base_model_id must not be empty")
        if self.seed < 0:
            raise ValueError("seed must be non-negative")
        if self.max_length < 256:
            raise ValueError("max_length must be at least 256")
        if self.epochs <= 0:
            raise ValueError("epochs must be positive")
        if self.max_steps == 0 or self.max_steps < -1:
            raise ValueError("max_steps must be -1 or positive")
        if self.learning_rate <= 0:
            raise ValueError("learning_rate must be positive")
        for name in (
            "per_device_train_batch_size",
            "per_device_eval_batch_size",
            "gradient_accumulation_steps",
            "lora_rank",
            "lora_alpha",
            "logging_steps",
            "save_total_limit",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be positive")
        if not 0 <= self.lora_dropout < 1:
            raise ValueError("lora_dropout must be in [0, 1)")
        if self.precision not in {"bf16", "fp16", "fp32"}:
            raise ValueError("precision must be bf16, fp16, or fp32")
        if self.attention_backend not in {"eager", "sdpa"}:
            raise ValueError("attention_backend must be eager or sdpa")
        if not 0.5 <= self.maximum_vram_fraction <= 0.95:
            raise ValueError("maximum_vram_fraction must be between 0.5 and 0.95")
        if self.train_file.resolve() == self.eval_file.resolve():
            raise ValueError("train_file and eval_file must be different")
        if self.output_dir.resolve() in {
            Path.cwd().resolve(),
            self.train_file.resolve(),
            self.eval_file.resolve(),
        }:
            raise ValueError("output_dir must be a dedicated directory")

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        for key in ("train_file", "eval_file", "output_dir"):
            result[key] = str(result[key])
        return result
