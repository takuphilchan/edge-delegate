"""Host-only classifier training; runtime artifacts contain plain numeric JSON."""

import hashlib
import json
import time
from pathlib import Path

from edge_delegate.model_plugins.task_classifier import DIMENSION, LABELS, features


def train(config_path, *, preflight_only=False):
    import torch

    from edge_delegate_lab.jsonio import load_jsonl

    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    required = {"plugin_id", "train_file", "eval_file", "output_dir"}
    if not required <= set(config) or set(config) - required - {"epochs", "seed"}:
        raise ValueError("invalid classifier training configuration")
    if config["plugin_id"] != "task-classifier":
        raise ValueError("wrong classifier plugin")
    train_records = load_jsonl(Path(config["train_file"]))
    validation = load_jsonl(Path(config["eval_file"]))
    from edge_delegate.data import validate_records

    validate_records(train_records)
    validate_records(validation)
    if not train_records or not validation:
        raise ValueError("training and validation must be nonempty")

    def groups(records):
        return {record["metadata"]["scenario_group"] for record in records}

    if groups(train_records) & groups(validation):
        raise ValueError("training and validation scenario groups overlap")
    for records in (train_records, validation):
        if {record["expected_task"]["task"] for record in records} != set(LABELS):
            raise ValueError("all task labels must be represented")
    report = {
        "plugin_id": "task-classifier",
        "train_count": len(train_records),
        "validation_count": len(validation),
        "qualified": False,
        "train_sha256": hashlib.sha256(Path(config["train_file"]).read_bytes()).hexdigest(),
        "validation_sha256": hashlib.sha256(Path(config["eval_file"]).read_bytes()).hexdigest(),
    }
    if preflight_only:
        return {**report, "status": "preflight_passed"}
    output = Path(config["output_dir"])
    if output.exists() and any(output.iterdir()):
        raise ValueError("training output must be new/empty")
    epochs = config.get("epochs", 200)
    if type(epochs) is not int or not 1 <= epochs <= 2000:
        raise ValueError("epochs must be 1..2000")
    torch.manual_seed(config.get("seed", 17))
    torch.set_num_threads(min(4, torch.get_num_threads()))

    def tensors(records):
        matrix = torch.zeros((len(records), DIMENSION))
        for index, record in enumerate(records):
            sparse = features(record["request"]["text"])
            for column, value in sparse.items():
                matrix[index, column] = value
        return matrix, torch.tensor([LABELS.index(r["expected_task"]["task"]) for r in records])

    started = time.perf_counter()
    inputs, labels = tensors(train_records)
    eval_inputs, eval_labels = tensors(validation)
    model = torch.nn.Linear(DIMENSION, len(LABELS))
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.05, weight_decay=0.001)
    best = None
    best_score = (-1.0, float("-inf"))
    selections = []
    for epoch in range(epochs):
        optimizer.zero_grad()
        loss = torch.nn.functional.cross_entropy(model(inputs), labels)
        loss.backward()
        optimizer.step()
        with torch.no_grad():
            logits = model(eval_inputs)
            accuracy = float((logits.argmax(1) == eval_labels).float().mean())
        if (epoch + 1) % 10 != 0 and epoch + 1 != epochs:
            continue
        from edge_delegate.data import build_record_world
        from edge_delegate.evaluation import EvaluationRunner
        from edge_delegate.model_plugins.task_classifier import numeric_parameter
        from edge_delegate.planner.tasks import BoundedPlanner, TaskDecision

        probabilities = logits.softmax(dim=-1)
        decisions = {}
        for record, row in zip(validation, probabilities.tolist(), strict=True):
            task = (
                LABELS[max(range(len(row)), key=row.__getitem__)] if max(row) >= 0.5 else "clarify"
            )
            parameters = {}
            if task == "display_number":
                value = numeric_parameter(record["request"]["text"])
                if value is None:
                    task = "clarify"
                else:
                    parameters["value"] = value
            decisions[record["record_id"]] = TaskDecision(task, parameters)
        task_planner = BoundedPlanner(
            lambda request, context, selected=decisions: selected[request.request_id]
        )
        task_report = EvaluationRunner(task_planner, execution_harness=build_record_world).evaluate(
            validation
        )
        metrics = task_report["metrics"]
        score = (metrics["task_success_rate"], -metrics["wrong_but_permitted_count"])
        selections.append(
            {
                "epoch": epoch + 1,
                "task_success_rate": score[0],
                "wrong_but_permitted_count": metrics["wrong_but_permitted_count"],
            }
        )
        if score > best_score:
            best_score = score
            best = {
                "weights": model.weight.detach().tolist(),
                "bias": model.bias.detach().tolist(),
                "epoch": epoch + 1,
                "intent_accuracy": accuracy,
            }
    output.mkdir(parents=True, exist_ok=True)
    artifact = output / "final-adapter"
    artifact.mkdir()
    data = {
        "protocol": "bounded-task.v1",
        "labels": list(LABELS),
        "threshold": 0.5,
        "weights": best["weights"],
        "bias": best["bias"],
        "catalog": "local-display.v1",
        "qualified": False,
    }
    (artifact / "classifier.json").write_text(json.dumps(data, allow_nan=False), encoding="utf-8")
    (artifact / "features.json").write_text(
        json.dumps(
            {
                "ngrams": [3, 4, 5],
                "dimension": DIMENSION,
                "hash": "blake2s-4-little",
                "normalization": "lowercase-whitespace-l2.v1",
            }
        ),
        encoding="utf-8",
    )
    from edge_delegate import __version__
    from edge_delegate.model_plugins.api import MODEL_PLUGIN_API_VERSION
    from edge_delegate.model_plugins.artifact import ModelArtifactManifest

    def file_hash(name):
        return hashlib.sha256((artifact / name).read_bytes()).hexdigest()

    ModelArtifactManifest(
        artifact_id=output.name,
        plugin_id="task-classifier",
        plugin_api_version=MODEL_PLUGIN_API_VERSION,
        plugin_package_version=__version__,
        base_model_id="edge-delegate/char-ngram-linear",
        base_model_revision="features-v1",
        plan_protocol_id="bounded-task",
        plan_protocol_version="1",
        plan_schema="plan-ir.v0",
        tokenizer_files={"features.json": file_hash("features.json")},
        adapter_method="supervised",
        adapter_format="json",
        adapter_files={"classifier.json": file_hash("classifier.json")},
        train_dataset_sha256=report["train_sha256"],
        validation_dataset_sha256=report["validation_sha256"],
        training_recipe_id="char-ngram-linear",
        training_recipe_version="1",
        max_context_tokens=8000,
        supported_precisions=("fp32",),
    ).write(artifact / "edge-delegate-artifact.json")
    report.update(
        status="completed",
        duration_seconds=time.perf_counter() - started,
        artifact=str(artifact),
        selected_epoch=best["epoch"],
        validation_intent_accuracy=best["intent_accuracy"],
        validation_task_success_rate=best_score[0],
        checkpoint_scores=selections,
        selection_metric="validation_task_success_then_fewer_wrong_actions",
    )
    (output / "training-run.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
