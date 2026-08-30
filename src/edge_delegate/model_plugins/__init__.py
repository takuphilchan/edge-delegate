"""Versioned local-model plugin, artifact, and compute contracts."""

from .api import (
    MODEL_PLUGIN_API_VERSION,
    MODEL_PLUGIN_ENTRY_POINT_GROUP,
    InferenceEngine,
    InferenceModelPlugin,
    ModelDiagnosticSession,
    ModelInferenceRequest,
    ModelPluginDescriptor,
    PlanProtocol,
    RawGeneration,
    TrainableModelPlugin,
)
from .artifact import ARTIFACT_SCHEMA_VERSION, ModelArtifactManifest
from .builtin import available_model_plugins, builtin_model_plugins
from .compute import (
    ComputeRequest,
    ComputeTelemetry,
    GpuInventory,
    HardwareInventory,
    ModelComputeCapabilities,
    ResolvedComputePlan,
    conservative_compute_plan,
    detect_hardware_inventory,
)
from .registry import ModelPluginRegistry

__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
    "MODEL_PLUGIN_API_VERSION",
    "MODEL_PLUGIN_ENTRY_POINT_GROUP",
    "ComputeRequest",
    "ComputeTelemetry",
    "GpuInventory",
    "HardwareInventory",
    "InferenceEngine",
    "InferenceModelPlugin",
    "ModelArtifactManifest",
    "ModelComputeCapabilities",
    "ModelDiagnosticSession",
    "ModelInferenceRequest",
    "ModelPluginDescriptor",
    "ModelPluginRegistry",
    "PlanProtocol",
    "RawGeneration",
    "ResolvedComputePlan",
    "TrainableModelPlugin",
    "available_model_plugins",
    "builtin_model_plugins",
    "conservative_compute_plan",
    "detect_hardware_inventory",
]
