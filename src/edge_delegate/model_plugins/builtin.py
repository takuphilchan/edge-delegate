"""Lazy registry for model plugins shipped in this repository."""

from __future__ import annotations

from .registry import ModelPluginRegistry


def _functiongemma_plugin():
    from .functiongemma import plugin

    return plugin


def builtin_model_plugins() -> ModelPluginRegistry:
    registry = ModelPluginRegistry()
    registry.register_loader("functiongemma", _functiongemma_plugin)
    return registry


def available_model_plugins() -> ModelPluginRegistry:
    """Discover installed entry points, with built-ins as source-tree fallbacks."""

    registry = ModelPluginRegistry()
    registry.discover_installed()
    if "functiongemma" not in registry.plugin_ids():
        registry.register_loader("functiongemma", _functiongemma_plugin)
    return registry
