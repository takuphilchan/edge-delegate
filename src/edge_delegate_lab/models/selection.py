"""Select retained compact-model checkpoints on canonical validation task outcomes."""

import gc
import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path

from edge_delegate.data import build_record_world, validate_records
from edge_delegate.evaluation import EvaluationRunner
from edge_delegate.model_plugins.artifact import ModelArtifactManifest


def select_task_checkpoint(plugin, run_dir, validation_file):
    import torch

    from edge_delegate_lab.jsonio import load_jsonl

    root = Path(run_dir).resolve()
    records = load_jsonl(Path(validation_file))
    gc.collect()
    torch.cuda.empty_cache()
    validate_records(records)
    base = ModelArtifactManifest.read(root / "final-adapter" / "edge-delegate-artifact.json")
    candidates = sorted(path for path in root.glob("checkpoint-*") if path.is_dir())
    if not candidates:
        candidates = [root / "final-adapter"]
    reports = []
    for path in candidates:
        files = {}
        for name in (*base.adapter_files, *base.tokenizer_files):
            item = path / name
            if not item.is_file():
                source = root / "final-adapter" / name
                if name in base.adapter_files:
                    raise ValueError("checkpoint lacks adapter weights/configuration")
                shutil.copy2(source, item)
            files[name] = hashlib.sha256(item.read_bytes()).hexdigest()
        manifest = replace(
            base,
            artifact_id=path.name,
            adapter_files={name: files[name] for name in base.adapter_files},
            tokenizer_files={name: files[name] for name in base.tokenizer_files},
        )
        manifest.write(path / "edge-delegate-artifact.json")
        session = plugin.create_diagnostic_session(artifact_path=str(path), settings={})
        report = EvaluationRunner(session.planner, execution_harness=build_record_world).evaluate(
            records
        )
        report["checkpoint"] = path.name
        (path / "task-validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        reports.append(report)
        del session
        gc.collect()
        torch.cuda.empty_cache()
    winner = max(
        reports,
        key=lambda report: (
            report["metrics"]["task_success_rate"] or 0,
            -report["metrics"]["wrong_but_permitted_count"],
            report["checkpoint"],
        ),
    )
    selected = root / "selected-adapter"
    selected.mkdir(exist_ok=False)
    source = root / winner["checkpoint"]
    manifest = ModelArtifactManifest.read(source / "edge-delegate-artifact.json")
    for name in (*manifest.adapter_files, *manifest.tokenizer_files, "edge-delegate-artifact.json"):
        shutil.copy2(source / name, selected / name)
    result = {
        "selection_metric": "validation_task_success_then_fewer_wrong_actions",
        "selected_checkpoint": winner["checkpoint"],
        "artifact": str(selected),
        "validation_dataset_sha256": winner["dataset_sha256"],
        "qualified": False,
        "candidates": [
            {"checkpoint": report["checkpoint"], "metrics": report["metrics"]} for report in reports
        ],
    }
    (root / "task-selection.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
