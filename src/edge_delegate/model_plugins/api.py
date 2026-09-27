"""Dependency-free contracts for installed local model plugins."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol, runtime_checkable

from edge_delegate.contracts import CapabilityCard, DeviceState, PlanIR, PlanningRequest, Policy
from edge_delegate.planner.base import Planner, PlannerContext

from .compute import ModelComputeCapabilities

MODEL_PLUGIN_API_VERSION = "edge-delegate-model-plugin.v1"
MODEL_PLUGIN_ENTRY_POINT_GROUP = "edge_delegate.model_plugins.v1"
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


def _identifier(value: str, name: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase stable identifier")
    return value


@dataclass(frozen=True, slots=True)
class ArtifactContract:
    """One artifact layout and protocol/schema combination a plugin can load."""

    plan_protocol_id: str
    plan_protocol_version: str
    plan_schema: str
    adapter_method: str
    adapter_format: str
    required_adapter_files: tuple[str, ...]
    required_tokenizer_files: tuple[str, ...]

    def __post_init__(self) -> None:
        _identifier(self.plan_protocol_id, "plan_protocol_id")
        for name in ("plan_protocol_version", "plan_schema", "adapter_method", "adapter_format"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        for names in (self.required_adapter_files, self.required_tokenizer_files):
            if not names:
                raise ValueError("artifact contracts must declare required files")
            for name in names:
                path = PurePosixPath(name)
                if path.is_absolute() or ".." in path.parts or name in {"", "."}:
                    raise ValueError("artifact contract files must use safe relative paths")


@dataclass(frozen=True, slots=True)
class ModelPluginDescriptor:
    plugin_id: str
    package_version: str
    display_name: str
    supported_protocols: tuple[str, ...]
    api_version: str = MODEL_PLUGIN_API_VERSION
    artifact_contracts: tuple[ArtifactContract, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.plugin_id, "plugin_id")
        if self.api_version != MODEL_PLUGIN_API_VERSION:
            raise ValueError(f"unsupported model plugin API: {self.api_version}")
        if not self.package_version.strip() or not self.display_name.strip():
            raise ValueError("plugin package_version and display_name must not be empty")
        if not self.supported_protocols:
            raise ValueError("a model plugin must support at least one plan protocol")
        for protocol in self.supported_protocols:
            _identifier(protocol, "supported protocol")
        for contract in self.artifact_contracts:
            if contract.plan_protocol_id not in self.supported_protocols:
                raise ValueError("artifact contract must use a supported protocol")


@dataclass(frozen=True, slots=True)
class ModelInferenceRequest:
    messages: tuple[Mapping[str, object], ...]
    tools: tuple[Mapping[str, object], ...]
    max_new_tokens: int

    def __post_init__(self) -> None:
        if not self.messages:
            raise ValueError("model inference messages must not be empty")
        if self.max_new_tokens < 1:
            raise ValueError("max_new_tokens must be positive")


@dataclass(frozen=True, slots=True)
class RawGeneration:
    text: str
    metadata: Mapping[str, object]


@runtime_checkable
class PlanProtocol(Protocol):
    @property
    def protocol_id(self) -> str: ...

    def build_request(
        self,
        request: PlanningRequest,
        state: DeviceState,
        policy: Policy,
        capabilities: Sequence[CapabilityCard],
        *,
        max_new_tokens: int,
    ) -> ModelInferenceRequest: ...

    def parse_generation(self, generation: RawGeneration) -> PlanIR: ...


@runtime_checkable
class InferenceEngine(Protocol):
    def generate(self, request: ModelInferenceRequest) -> RawGeneration: ...


@runtime_checkable
class ModelDiagnosticSession(Protocol):
    """Model-specific observability around a model-neutral typed planner."""

    @property
    def planner(self) -> Planner: ...

    @property
    def model_info(self) -> Mapping[str, object]: ...

    def selected_capability_ids(
        self,
        request: PlanningRequest,
        context: PlannerContext,
    ) -> tuple[str, ...]: ...

    def last_generation(self, *, include_raw_output: bool) -> Mapping[str, object] | None: ...

    def classify_error(self, error: Exception) -> str: ...


@runtime_checkable
class WarmableModelSession(Protocol):
    """Optional preparation before serving; must not call devices or external models."""

    def warmup(self) -> Mapping[str, object]: ...


@runtime_checkable
class InferenceModelPlugin(Protocol):
    @property
    def descriptor(self) -> ModelPluginDescriptor: ...

    @property
    def compute_capabilities(self) -> ModelComputeCapabilities: ...

    def create_planner(
        self,
        *,
        artifact_path: str | None,
        settings: Mapping[str, object],
    ) -> Planner: ...

    def create_diagnostic_session(
        self,
        *,
        artifact_path: str | None,
        settings: Mapping[str, object],
    ) -> ModelDiagnosticSession: ...


@runtime_checkable
class TrainableModelPlugin(Protocol):
    """Optional host-side facilities supplied by a model plugin."""

    def export_training_data(
        self,
        *,
        splits: Mapping[str, Sequence[Mapping[str, object]]],
        output_dir: Path,
    ) -> Mapping[str, object]: ...

    def train_from_config(
        self,
        *,
        config_path: Path,
        preflight_only: bool,
    ) -> Mapping[str, object]: ...


type PluginLoader = Callable[[], InferenceModelPlugin]
