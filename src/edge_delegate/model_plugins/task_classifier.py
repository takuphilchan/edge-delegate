"""Small character-ngram classifier. JSON weights; no pickle or runtime ML dependency."""

import hashlib
import json
import math
import time
from collections import Counter
from pathlib import Path

from edge_delegate import __version__
from edge_delegate.planner.numeric import (
    LEGACY_NUMERIC_POLICY,
    extract_numeric_literal,
    validate_numeric_policy,
)
from edge_delegate.planner.numeric import numeric_parameter as numeric_parameter
from edge_delegate.planner.tasks import BoundedPlanner, TaskDecision

from .api import ArtifactContract, ModelPluginDescriptor
from .artifact import ModelArtifactManifest
from .compute import ModelComputeCapabilities

LABELS = ("read_temperature", "display_number", "show_temperature", "clarify", "deny")
DIMENSION = 4096
FEATURE_SPEC = {
    "ngrams": [3, 4, 5],
    "dimension": DIMENSION,
    "hash": "blake2s-4-little",
    "normalization": "lowercase-whitespace-l2.v1",
}


def features(text):
    text = " " + " ".join(text.lower().split()) + " "
    counts = Counter()
    for size in (3, 4, 5):
        for offset in range(max(0, len(text) - size + 1)):
            digest = hashlib.blake2s(text[offset : offset + size].encode(), digest_size=4).digest()
            counts[int.from_bytes(digest, "little") % DIMENSION] += 1
    norm = math.sqrt(sum(value * value for value in counts.values())) or 1
    return {key: value / norm for key, value in counts.items()}


class ClassifierSession:
    def __init__(self, artifact_path, *, numeric_policy=LEGACY_NUMERIC_POLICY):
        started = time.perf_counter()
        self.numeric_policy = validate_numeric_policy(numeric_policy)
        if artifact_path is None:
            raise ValueError("task-classifier requires a trained artifact directory")
        root = Path(artifact_path)
        manifest = ModelArtifactManifest.read(root / "edge-delegate-artifact.json")
        manifest.verify_files(root, descriptor=TaskClassifierPlugin.descriptor)
        if json.loads((root / "features.json").read_text(encoding="utf-8")) != FEATURE_SPEC:
            raise ValueError("classifier feature recipe does not match this implementation")
        path = Path(artifact_path) / "classifier.json"
        with path.open("rb") as handle:
            payload = handle.read(4 * 1024 * 1024 + 1)
        if len(payload) > 4 * 1024 * 1024:
            raise ValueError("classifier artifact exceeds limit")

        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError("duplicate classifier artifact field")
                result[key] = value
            return result

        data = json.loads(payload, object_pairs_hook=pairs)
        if data.get("protocol") != "bounded-task.v1" or data.get("labels") != list(LABELS):
            raise ValueError("incompatible classifier artifact")
        self.weights, self.bias = data["weights"], data["bias"]
        self.threshold = data["threshold"]
        if len(self.weights) != len(LABELS) or len(self.bias) != len(LABELS):
            raise ValueError("invalid classifier dimensions")
        if any(len(row) != DIMENSION for row in self.weights):
            raise ValueError("invalid classifier feature dimension")
        numbers = [self.threshold, *self.bias, *(value for row in self.weights for value in row)]
        if not all(type(value) in {int, float} and math.isfinite(value) for value in numbers):
            raise ValueError("nonfinite or invalid classifier weights")
        if not 0 <= self.threshold <= 1:
            raise ValueError("invalid abstention threshold")
        self.model_info = {
            "model_id": "task-classifier",
            "device": "cpu",
            "dtype": "float64",
            "load_time_ms": (time.perf_counter() - started) * 1000,
            "artifact_sha256": hashlib.sha256(payload).hexdigest(),
            "qualified": False,
            "numeric_policy": self.numeric_policy,
        }
        self.planner = BoundedPlanner(self.decide)
        self._last = None

    def decide(self, request, context):
        started = time.perf_counter()
        sparse = features(request.text)
        scores = [
            bias + sum(row[index] * value for index, value in sparse.items())
            for row, bias in zip(self.weights, self.bias, strict=True)
        ]
        maximum = max(scores)
        probabilities = [math.exp(score - maximum) for score in scores]
        total = sum(probabilities)
        index = max(range(len(scores)), key=scores.__getitem__)
        confidence = probabilities[index] / total
        task = LABELS[index] if confidence >= self.threshold else "clarify"
        parameters = {}
        numeric_check = None
        if task == "display_number":
            numeric_check = extract_numeric_literal(request.text, policy=self.numeric_policy)
            value = numeric_check.value
            if value is None:
                task = "clarify"
            else:
                parameters["value"] = value
        self._last = {
            "latency_ms": (time.perf_counter() - started) * 1000,
            "classifier_probability": confidence,
            "calibrated": False,
            "numeric_policy": self.numeric_policy,
            "numeric_check": None if numeric_check is None else numeric_check.reason or "accepted",
            "raw_output": json.dumps({"task": task, "parameters": parameters}),
        }
        return TaskDecision(task, parameters)

    def selected_capability_ids(self, request, context):
        return tuple(card.capability_id for card in context.capabilities)

    def last_generation(self, *, include_raw_output):
        return (
            None
            if self._last is None
            else {
                key: value
                for key, value in self._last.items()
                if include_raw_output or key != "raw_output"
            }
        )

    def classify_error(self, error):
        return "task_decision_error"


class TaskClassifierPlugin:
    descriptor = ModelPluginDescriptor(
        "task-classifier",
        __version__,
        "Bounded character-ngram classifier",
        ("bounded-task",),
        artifact_contracts=(
            ArtifactContract(
                "bounded-task",
                "1",
                "plan-ir.v0",
                "supervised",
                "json",
                ("classifier.json",),
                ("features.json",),
            ),
        ),
    )
    compute_capabilities = ModelComputeCapabilities(("fp32",), ("none",), False, False, False, 8000)

    def create_diagnostic_session(self, *, artifact_path, settings):
        if set(settings) - {"numeric_policy"}:
            raise ValueError("task-classifier only supports the numeric_policy inference setting")
        return ClassifierSession(
            artifact_path, numeric_policy=settings.get("numeric_policy", LEGACY_NUMERIC_POLICY)
        )

    def create_planner(self, *, artifact_path, settings):
        return self.create_diagnostic_session(
            artifact_path=artifact_path, settings=settings
        ).planner

    def export_training_data(self, *, splits, output_dir):
        files = {}
        for name, records in splits.items():
            path = output_dir / f"task-classifier-{name}.jsonl"
            with path.open("w", encoding="utf-8") as handle:
                for record in records:
                    if "expected_task" not in record:
                        raise ValueError("task classifier requires bounded-task dataset")
                    handle.write(json.dumps(record) + "\n")
            files[name] = path.name
        return {"plugin_id": "task-classifier", "files": files}

    def train_from_config(self, *, config_path, preflight_only):
        from edge_delegate_lab.models.classifier import train

        return train(config_path, preflight_only=preflight_only)


plugin = TaskClassifierPlugin()
