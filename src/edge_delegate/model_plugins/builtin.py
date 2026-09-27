"""Lazy registry for model plugins shipped in this repository."""

from __future__ import annotations

from .registry import ModelPluginRegistry


def _functiongemma_plugin():
    from .functiongemma import plugin

    return plugin


def _task_classifier_plugin():
    from .task_classifier import plugin

    return plugin


def _functiongemma_tasks_plugin():
    from .functiongemma_tasks import plugin

    return plugin


def _bounded_commands_plugin():
    from .bounded_commands import plugin

    return plugin


LOADERS = {
    "functiongemma": _functiongemma_plugin,
    "task-classifier": _task_classifier_plugin,
    "functiongemma-tasks": _functiongemma_tasks_plugin,
    "bounded-commands": _bounded_commands_plugin,
}


def builtin_model_plugins() -> ModelPluginRegistry:
    registry = ModelPluginRegistry()
    for name, loader in LOADERS.items():
        registry.register_loader(name, loader)
    return registry


def available_model_plugins() -> ModelPluginRegistry:
    """Discover installed entry points, with built-ins as source-tree fallbacks."""

    registry = ModelPluginRegistry()
    registry.discover_installed()
    for name, loader in LOADERS.items():
        if name not in registry.plugin_ids():
            registry.register_loader(name, loader)
    return registry
