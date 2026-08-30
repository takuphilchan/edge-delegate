"""Portable, strictly validated model-artifact manifest."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .api import MODEL_PLUGIN_API_VERSION, ModelPluginDescriptor

ARTIFACT_SCHEMA_VERSION = "edge-delegate-model-artifact.v1"
MAX_ARTIFACT_MANIFEST_BYTES = 1024 * 1024
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


def _nonempty(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string")
    return value


def _sha256(value: object, path: str) -> str:
    result = _nonempty(value, path)
    if not _SHA256.fullmatch(result):
        raise ValueError(f"{path} must be a lowercase SHA-256 digest")
    return result


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be an object")
    return value


def _exact_fields(value: Mapping[str, object], fields: set[str], path: str) -> None:
    missing = fields - set(value)
    unknown = set(value) - fields
    if missing:
        raise ValueError(f"{path} missing fields: {', '.join(sorted(missing))}")
    if unknown:
        raise ValueError(f"{path} unknown fields: {', '.join(sorted(unknown))}")


def _reject_constant(value: str):
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def _without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class ModelArtifactManifest:
    artifact_id: str
    plugin_id: str
    plugin_api_version: str
    plugin_package_version: str
    base_model_id: str
    base_model_revision: str
    plan_protocol_id: str
    plan_protocol_version: str
    plan_schema: str
    tokenizer_files: Mapping[str, str]
    adapter_method: str
    adapter_format: str
    adapter_files: Mapping[str, str]
    train_dataset_sha256: str
    validation_dataset_sha256: str
    training_recipe_id: str
    training_recipe_version: str
    max_context_tokens: int
    supported_precisions: tuple[str, ...]
    schema_version: str = ARTIFACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != ARTIFACT_SCHEMA_VERSION:
            raise ValueError(f"unsupported artifact schema: {self.schema_version}")
        if self.plugin_api_version != MODEL_PLUGIN_API_VERSION:
            raise ValueError(f"unsupported plugin API: {self.plugin_api_version}")
        for name in (
            "artifact_id",
            "plugin_id",
            "plugin_package_version",
            "base_model_id",
            "base_model_revision",
            "plan_protocol_id",
            "plan_protocol_version",
            "plan_schema",
            "adapter_method",
            "adapter_format",
            "training_recipe_id",
            "training_recipe_version",
        ):
            _nonempty(getattr(self, name), name)
        _sha256(self.train_dataset_sha256, "train_dataset_sha256")
        _sha256(self.validation_dataset_sha256, "validation_dataset_sha256")
        if self.max_context_tokens < 1:
            raise ValueError("max_context_tokens must be positive")
        if not self.supported_precisions:
            raise ValueError("supported_precisions must not be empty")
        self._validate_file_map(self.tokenizer_files, "tokenizer_files")
        self._validate_file_map(self.adapter_files, "adapter_files")

    @staticmethod
    def _validate_file_map(files: Mapping[str, str], name: str) -> None:
        if not files:
            raise ValueError(f"{name} must not be empty")
        for relative, digest in files.items():
            path = PurePosixPath(relative)
            if path.is_absolute() or ".." in path.parts or relative in {"", "."}:
                raise ValueError(f"{name} must contain only safe relative paths: {relative!r}")
            _sha256(digest, f"{name}.{relative}")

    def ensure_plugin_compatible(self, descriptor: ModelPluginDescriptor) -> None:
        if descriptor.plugin_id != self.plugin_id:
            raise ValueError("artifact model plugin does not match the selected plugin")
        if descriptor.api_version != self.plugin_api_version:
            raise ValueError("artifact model-plugin API is incompatible")
        if self.plan_protocol_id not in descriptor.supported_protocols:
            raise ValueError("artifact plan protocol is not supported by the selected plugin")

    def verify_files(self, root: Path) -> None:
        root = root.resolve()
        self._verify_file_map(root, self.tokenizer_files, "tokenizer")
        self._verify_file_map(root, self.adapter_files, "adapter")

    @staticmethod
    def _verify_file_map(
        root: Path,
        files: Mapping[str, str],
        kind: str,
    ) -> None:
        for relative, expected in files.items():
            path = (root / PurePosixPath(relative)).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise ValueError(f"artifact {kind} file is missing or outside its root: {relative}")
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != expected:
                raise ValueError(f"artifact {kind} file digest does not match: {relative}")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "artifact_id": self.artifact_id,
            "plugin": {
                "id": self.plugin_id,
                "api_version": self.plugin_api_version,
                "package_version": self.plugin_package_version,
            },
            "base_model": {"id": self.base_model_id, "revision": self.base_model_revision},
            "plan_protocol": {
                "id": self.plan_protocol_id,
                "version": self.plan_protocol_version,
            },
            "plan_schema": self.plan_schema,
            "tokenizer": {"files": dict(sorted(self.tokenizer_files.items()))},
            "adapter": {
                "method": self.adapter_method,
                "format": self.adapter_format,
                "files": dict(sorted(self.adapter_files.items())),
            },
            "dataset": {
                "train_sha256": self.train_dataset_sha256,
                "validation_sha256": self.validation_dataset_sha256,
            },
            "training_recipe": {
                "id": self.training_recipe_id,
                "version": self.training_recipe_version,
            },
            "runtime": {
                "max_context_tokens": self.max_context_tokens,
                "supported_precisions": list(self.supported_precisions),
            },
        }

    @classmethod
    def from_dict(cls, raw: object) -> ModelArtifactManifest:
        data = _mapping(raw, "$")
        _exact_fields(
            data,
            {
                "schema_version",
                "artifact_id",
                "plugin",
                "base_model",
                "plan_protocol",
                "plan_schema",
                "tokenizer",
                "adapter",
                "dataset",
                "training_recipe",
                "runtime",
            },
            "$",
        )
        plugin = _mapping(data["plugin"], "$.plugin")
        base = _mapping(data["base_model"], "$.base_model")
        protocol = _mapping(data["plan_protocol"], "$.plan_protocol")
        tokenizer = _mapping(data["tokenizer"], "$.tokenizer")
        adapter = _mapping(data["adapter"], "$.adapter")
        dataset = _mapping(data["dataset"], "$.dataset")
        recipe = _mapping(data["training_recipe"], "$.training_recipe")
        runtime = _mapping(data["runtime"], "$.runtime")
        _exact_fields(plugin, {"id", "api_version", "package_version"}, "$.plugin")
        _exact_fields(base, {"id", "revision"}, "$.base_model")
        _exact_fields(protocol, {"id", "version"}, "$.plan_protocol")
        _exact_fields(tokenizer, {"files"}, "$.tokenizer")
        _exact_fields(adapter, {"method", "format", "files"}, "$.adapter")
        _exact_fields(dataset, {"train_sha256", "validation_sha256"}, "$.dataset")
        _exact_fields(recipe, {"id", "version"}, "$.training_recipe")
        _exact_fields(runtime, {"max_context_tokens", "supported_precisions"}, "$.runtime")
        files = _mapping(adapter["files"], "$.adapter.files")
        tokenizer_files = _mapping(tokenizer["files"], "$.tokenizer.files")
        precisions = runtime["supported_precisions"]
        if not isinstance(precisions, list) or not all(
            isinstance(item, str) for item in precisions
        ):
            raise ValueError("$.runtime.supported_precisions must be a string array")
        max_context = runtime["max_context_tokens"]
        if not isinstance(max_context, int) or isinstance(max_context, bool):
            raise ValueError("$.runtime.max_context_tokens must be an integer")
        return cls(
            schema_version=_nonempty(data["schema_version"], "$.schema_version"),
            artifact_id=_nonempty(data["artifact_id"], "$.artifact_id"),
            plugin_id=_nonempty(plugin["id"], "$.plugin.id"),
            plugin_api_version=_nonempty(plugin["api_version"], "$.plugin.api_version"),
            plugin_package_version=_nonempty(plugin["package_version"], "$.plugin.package_version"),
            base_model_id=_nonempty(base["id"], "$.base_model.id"),
            base_model_revision=_nonempty(base["revision"], "$.base_model.revision"),
            plan_protocol_id=_nonempty(protocol["id"], "$.plan_protocol.id"),
            plan_protocol_version=_nonempty(protocol["version"], "$.plan_protocol.version"),
            plan_schema=_nonempty(data["plan_schema"], "$.plan_schema"),
            tokenizer_files={
                str(path): _sha256(digest, f"$.tokenizer.files.{path}")
                for path, digest in tokenizer_files.items()
            },
            adapter_method=_nonempty(adapter["method"], "$.adapter.method"),
            adapter_format=_nonempty(adapter["format"], "$.adapter.format"),
            adapter_files={
                str(path): _sha256(digest, f"$.adapter.files.{path}")
                for path, digest in files.items()
            },
            train_dataset_sha256=_sha256(dataset["train_sha256"], "$.dataset.train_sha256"),
            validation_dataset_sha256=_sha256(
                dataset["validation_sha256"], "$.dataset.validation_sha256"
            ),
            training_recipe_id=_nonempty(recipe["id"], "$.training_recipe.id"),
            training_recipe_version=_nonempty(recipe["version"], "$.training_recipe.version"),
            max_context_tokens=max_context,
            supported_precisions=tuple(precisions),
        )

    @classmethod
    def read(cls, path: Path) -> ModelArtifactManifest:
        payload = path.read_bytes()
        if len(payload) > MAX_ARTIFACT_MANIFEST_BYTES:
            raise ValueError("artifact manifest exceeds the size limit")
        return cls.from_dict(
            json.loads(
                payload.decode("utf-8"),
                object_pairs_hook=_without_duplicates,
                parse_constant=_reject_constant,
            )
        )

    def write(self, path: Path) -> None:
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
