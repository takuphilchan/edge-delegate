"""Reproducible, guarded adapter training for the local planner."""

from .config import TrainingConfig
from .preflight import SFTPreflight, load_sft_records, preflight_sft_data
from .runner import train_lora_adapter
from .template import add_assistant_generation_mask

__all__ = [
    "SFTPreflight",
    "TrainingConfig",
    "add_assistant_generation_mask",
    "load_sft_records",
    "preflight_sft_data",
    "train_lora_adapter",
]
