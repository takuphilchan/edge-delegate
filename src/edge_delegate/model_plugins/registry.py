"""Lazy, allowlisted model-plugin discovery."""

from __future__ import annotations

from importlib.metadata import entry_points

from .api import (
    MODEL_PLUGIN_API_VERSION,
    MODEL_PLUGIN_ENTRY_POINT_GROUP,
    InferenceModelPlugin,
    PluginLoader,
)


class ModelPluginRegistry:
    def __init__(self) -> None:
        self._loaders: dict[str, PluginLoader] = {}
        self._instances: dict[str, InferenceModelPlugin] = {}

    def register_loader(self, plugin_id: str, loader: PluginLoader) -> None:
        if plugin_id in self._loaders:
            raise ValueError(f"duplicate model plugin id: {plugin_id}")
        self._loaders[plugin_id] = loader

    def discover_installed(self) -> None:
        for entry_point in entry_points(group=MODEL_PLUGIN_ENTRY_POINT_GROUP):
            self.register_loader(entry_point.name, entry_point.load)

    def plugin_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._loaders))

    def get(self, plugin_id: str) -> InferenceModelPlugin:
        if plugin_id in self._instances:
            return self._instances[plugin_id]
        try:
            loader = self._loaders[plugin_id]
        except KeyError as exc:
            raise KeyError(f"model plugin is not installed or allowlisted: {plugin_id}") from exc
        plugin = loader()
        if not isinstance(plugin, InferenceModelPlugin):
            raise TypeError(f"model plugin {plugin_id!r} does not implement the v1 plugin contract")
        descriptor = plugin.descriptor
        if descriptor.plugin_id != plugin_id:
            raise ValueError(f"model plugin loader {plugin_id!r} returned {descriptor.plugin_id!r}")
        if descriptor.api_version != MODEL_PLUGIN_API_VERSION:
            raise ValueError(
                f"model plugin {plugin_id!r} uses unsupported API {descriptor.api_version!r}"
            )
        self._instances[plugin_id] = plugin
        return plugin
