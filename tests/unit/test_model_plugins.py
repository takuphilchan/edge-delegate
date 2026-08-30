"""Dependency-free model plugin, artifact, and compute contract tests."""

from __future__ import annotations

import hashlib

import pytest

from edge_delegate.model_plugins import (
    MODEL_PLUGIN_API_VERSION,
    ComputeRequest,
    GpuInventory,
    HardwareInventory,
    ModelArtifactManifest,
    ModelComputeCapabilities,
    ModelPluginDescriptor,
    ModelPluginRegistry,
    builtin_model_plugins,
    conservative_compute_plan,
)
from edge_delegate.planner import StaticPlanner


class FakeModelPlugin:
    descriptor = ModelPluginDescriptor(
        plugin_id="fake-model",
        package_version="1.0.0",
        display_name="No-ML test plugin",
        supported_protocols=("fake-submit-plan",),
    )
    compute_capabilities = ModelComputeCapabilities(
        supported_precisions=("fp32",),
        supported_attention_backends=("eager",),
        supports_gradient_checkpointing=False,
        supports_quantized_training=False,
        supports_peft=False,
        maximum_context_tokens=2048,
    )

    def create_planner(self, *, artifact_path, settings):
        del artifact_path, settings
        return StaticPlanner({})

    def create_diagnostic_session(self, *, artifact_path, settings):
        del artifact_path, settings
        raise NotImplementedError


def _manifest(
    *,
    adapter_digest: str,
    adapter_path: str = "adapter/model.bin",
    tokenizer_digest: str = "a" * 64,
):
    return ModelArtifactManifest(
        artifact_id="fake-model-test-v1",
        plugin_id="fake-model",
        plugin_api_version=MODEL_PLUGIN_API_VERSION,
        plugin_package_version="1.0.0",
        base_model_id="example/fake-model",
        base_model_revision="revision-123",
        plan_protocol_id="fake-submit-plan",
        plan_protocol_version="1",
        plan_schema="plan-ir.v0",
        tokenizer_files={"tokenizer.json": tokenizer_digest},
        adapter_method="lora",
        adapter_format="test",
        adapter_files={adapter_path: adapter_digest},
        train_dataset_sha256="b" * 64,
        validation_dataset_sha256="c" * 64,
        training_recipe_id="fake-sft",
        training_recipe_version="1",
        max_context_tokens=2048,
        supported_precisions=("bf16", "fp32"),
    )


def test_registry_lists_without_loading_and_loads_only_the_selected_plugin() -> None:
    calls = 0

    def load():
        nonlocal calls
        calls += 1
        return FakeModelPlugin()

    registry = ModelPluginRegistry()
    registry.register_loader("fake-model", load)

    assert registry.plugin_ids() == ("fake-model",)
    assert calls == 0
    assert registry.get("fake-model").descriptor.display_name == "No-ML test plugin"
    assert registry.get("fake-model") is registry.get("fake-model")
    assert calls == 1


def test_builtin_functiongemma_plugin_is_discoverable_without_loading_torch() -> None:
    registry = builtin_model_plugins()

    assert registry.plugin_ids() == ("functiongemma",)
    assert registry.get("functiongemma").descriptor.supported_protocols == (
        "functiongemma-submit-plan",
    )


def test_artifact_manifest_round_trips_and_verifies_adapter_files(tmp_path) -> None:
    adapter = tmp_path / "adapter" / "model.bin"
    adapter.parent.mkdir()
    adapter.write_bytes(b"portable adapter")
    digest = hashlib.sha256(adapter.read_bytes()).hexdigest()
    tokenizer = tmp_path / "tokenizer.json"
    tokenizer.write_bytes(b"portable tokenizer")
    manifest = _manifest(
        adapter_digest=digest,
        tokenizer_digest=hashlib.sha256(tokenizer.read_bytes()).hexdigest(),
    )
    path = tmp_path / "artifact-manifest.json"

    manifest.write(path)
    loaded = ModelArtifactManifest.read(path)
    loaded.ensure_plugin_compatible(FakeModelPlugin().descriptor)
    loaded.verify_files(tmp_path)

    assert loaded == manifest


def test_artifact_manifest_rejects_paths_outside_the_artifact_root() -> None:
    with pytest.raises(ValueError, match="safe relative path"):
        _manifest(adapter_digest="d" * 64, adapter_path="../model.bin")


def test_artifact_manifest_rejects_duplicate_json_keys(tmp_path) -> None:
    path = tmp_path / "edge-delegate-artifact.json"
    path.write_text('{"schema_version":"one","schema_version":"two"}', encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate JSON object key"):
        ModelArtifactManifest.read(path)


def test_conservative_compute_plan_uses_supported_bf16_and_sdpa() -> None:
    inventory = HardwareInventory(
        cpu_logical_cores=16,
        system_memory_bytes=8 * 1024**3,
        gpu=GpuInventory(
            name="Test GPU",
            total_memory_bytes=8 * 1024**3,
            compute_capability=(12, 0),
            bf16_supported=True,
        ),
    )
    capabilities = ModelComputeCapabilities(
        supported_precisions=("bf16", "fp32"),
        supported_attention_backends=("eager", "sdpa"),
        supports_gradient_checkpointing=True,
        supports_quantized_training=False,
        supports_peft=True,
        maximum_context_tokens=4096,
    )

    plan = conservative_compute_plan(
        inventory,
        capabilities,
        ComputeRequest(effective_batch_size=4, max_context_tokens=2048),
    )

    assert plan.device == "cuda:0"
    assert plan.precision == "bf16"
    assert plan.attention_backend == "sdpa"
    assert plan.microbatch_size == 1
    assert plan.gradient_accumulation_steps == 4
    assert plan.dataloader_workers == 2
    assert plan.selection_source == "conservative_default_pending_memory_probe"
