"""Model-neutral compute inventory, capability, and resolved-plan contracts."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class GpuInventory:
    name: str
    total_memory_bytes: int
    compute_capability: tuple[int, int] | None
    bf16_supported: bool

    def __post_init__(self) -> None:
        if not self.name.strip() or self.total_memory_bytes < 1:
            raise ValueError("GPU name and positive memory capacity are required")


@dataclass(frozen=True, slots=True)
class HardwareInventory:
    cpu_logical_cores: int
    system_memory_bytes: int
    gpu: GpuInventory | None = None
    torch_version: str | None = None
    cuda_runtime_version: str | None = None
    schema_version: str = "edge-delegate-hardware-inventory.v1"

    def __post_init__(self) -> None:
        if self.cpu_logical_cores < 1 or self.system_memory_bytes < 1:
            raise ValueError("positive CPU and system-memory capacities are required")


@dataclass(frozen=True, slots=True)
class ModelComputeCapabilities:
    supported_precisions: tuple[str, ...]
    supported_attention_backends: tuple[str, ...]
    supports_gradient_checkpointing: bool
    supports_quantized_training: bool
    supports_peft: bool
    maximum_context_tokens: int

    def __post_init__(self) -> None:
        if not self.supported_precisions or not self.supported_attention_backends:
            raise ValueError("model compute capabilities must declare precision and attention")
        if self.maximum_context_tokens < 1:
            raise ValueError("maximum_context_tokens must be positive")


@dataclass(frozen=True, slots=True)
class ComputeRequest:
    effective_batch_size: int
    max_context_tokens: int
    requested_precision: str = "auto"
    requested_attention_backend: str = "auto"
    requested_gradient_checkpointing: bool | None = None
    maximum_vram_fraction: float = 0.88

    def __post_init__(self) -> None:
        if self.effective_batch_size < 1 or self.max_context_tokens < 1:
            raise ValueError("batch size and context length must be positive")
        if not 0.5 <= self.maximum_vram_fraction <= 0.95:
            raise ValueError("maximum_vram_fraction must be between 0.5 and 0.95")


@dataclass(frozen=True, slots=True)
class ResolvedComputePlan:
    device: str
    precision: str
    attention_backend: str
    microbatch_size: int
    gradient_accumulation_steps: int
    effective_batch_size: int
    gradient_checkpointing: bool
    dataloader_workers: int
    pin_memory: bool
    maximum_vram_fraction: float
    selection_source: str
    schema_version: str = "edge-delegate-compute-plan.v1"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ComputeTelemetry:
    duration_seconds: float
    peak_gpu_allocated_bytes: int | None
    peak_gpu_reserved_bytes: int | None
    peak_cpu_rss_bytes: int | None
    tokens_per_second: float | None
    gpu_utilization_p50: float | None = None
    gpu_utilization_p95: float | None = None
    maximum_temperature_c: float | None = None
    average_power_watts: float | None = None
    schema_version: str = "edge-delegate-compute-telemetry.v1"

    def __post_init__(self) -> None:
        if self.duration_seconds < 0:
            raise ValueError("duration_seconds must not be negative")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _system_memory_bytes() -> int:
    try:
        pages = int(os.sysconf("SC_PHYS_PAGES"))
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
    except (AttributeError, OSError, ValueError):
        try:
            import psutil
        except ImportError:
            return 1
        return max(1, int(psutil.virtual_memory().total))
    return max(1, pages * page_size)


def detect_hardware_inventory() -> HardwareInventory:
    """Inspect CPU, memory, and optional CUDA without loading model weights."""

    gpu = None
    torch_version = None
    cuda_runtime = None
    try:
        import torch
    except ImportError:
        torch = None
    if torch is not None:
        torch_version = str(torch.__version__)
        cuda_runtime = None if torch.version.cuda is None else str(torch.version.cuda)
        if torch.cuda.is_available():
            properties = torch.cuda.get_device_properties(0)
            gpu = GpuInventory(
                name=properties.name,
                total_memory_bytes=int(properties.total_memory),
                compute_capability=tuple(torch.cuda.get_device_capability(0)),
                bf16_supported=bool(torch.cuda.is_bf16_supported()),
            )
    return HardwareInventory(
        cpu_logical_cores=max(1, os.cpu_count() or 1),
        system_memory_bytes=_system_memory_bytes(),
        gpu=gpu,
        torch_version=torch_version,
        cuda_runtime_version=cuda_runtime,
    )


def conservative_compute_plan(
    inventory: HardwareInventory,
    capabilities: ModelComputeCapabilities,
    request: ComputeRequest,
) -> ResolvedComputePlan:
    """Resolve a reproducible safe baseline before active memory probing."""

    if request.max_context_tokens > capabilities.maximum_context_tokens:
        raise ValueError("requested context exceeds the model plugin limit")
    device = "cuda:0" if inventory.gpu is not None else "cpu"
    if request.requested_precision == "auto":
        precision = "fp32"
        if (
            inventory.gpu is not None
            and inventory.gpu.bf16_supported
            and "bf16" in capabilities.supported_precisions
        ):
            precision = "bf16"
        elif inventory.gpu is not None and "fp16" in capabilities.supported_precisions:
            precision = "fp16"
        elif "fp32" not in capabilities.supported_precisions:
            raise ValueError("no supported precision is compatible with the hardware")
    else:
        precision = request.requested_precision
        if precision not in capabilities.supported_precisions:
            raise ValueError("requested precision is not supported by the model plugin")
        if precision == "bf16" and (inventory.gpu is None or not inventory.gpu.bf16_supported):
            raise ValueError("BF16 was requested but is not supported by the hardware")
    if request.requested_attention_backend == "auto":
        attention = (
            "sdpa"
            if inventory.gpu is not None and "sdpa" in capabilities.supported_attention_backends
            else capabilities.supported_attention_backends[0]
        )
    else:
        attention = request.requested_attention_backend
        if attention not in capabilities.supported_attention_backends:
            raise ValueError("requested attention backend is not supported by the model plugin")
    microbatch = 1
    gradient_checkpointing = bool(request.requested_gradient_checkpointing)
    if gradient_checkpointing and not capabilities.supports_gradient_checkpointing:
        raise ValueError("gradient checkpointing is not supported by the model plugin")
    return ResolvedComputePlan(
        device=device,
        precision=precision,
        attention_backend=attention,
        microbatch_size=microbatch,
        gradient_accumulation_steps=request.effective_batch_size,
        effective_batch_size=request.effective_batch_size,
        gradient_checkpointing=gradient_checkpointing,
        dataloader_workers=min(2, max(0, inventory.cpu_logical_cores - 1)),
        pin_memory=inventory.gpu is not None,
        maximum_vram_fraction=request.maximum_vram_fraction,
        selection_source="conservative_default_pending_memory_probe",
    )
