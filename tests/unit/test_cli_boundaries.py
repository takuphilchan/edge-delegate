"""The edge CLI stays small while model work remains in the host-side lab."""

import json

from edge_delegate.cli import build_parser as build_edge_parser
from edge_delegate_lab.cli import build_parser as build_lab_parser
from edge_delegate_lab.cli import main as lab_main


def _subcommands(parser):
    action = next(action for action in parser._actions if action.dest == "command")
    return set(action.choices)


def test_edge_cli_exposes_only_runtime_safe_commands() -> None:
    assert _subcommands(build_edge_parser()) == {"demo", "validate", "pack-check", "control-demo"}


def test_lab_cli_owns_data_model_and_compute_commands() -> None:
    assert _subcommands(build_lab_parser()) == {
        "artifact-verify",
        "artifact-export",
        "audit-validation",
        "compute-inspect",
        "compute-plan",
        "evaluate",
        "generate-data",
        "review-data",
        "interactive",
        "init-example",
        "model-doctor",
        "models",
        "plan",
        "profile-check",
        "simulate",
        "run",
        "reconcile",
        "benchmark",
        "qualify",
        "train",
    }


def test_models_command_describes_plugin_without_loading_model_weights(capsys) -> None:
    assert lab_main(["models"]) == 0
    result = json.loads(capsys.readouterr().out)

    gemma = next(item for item in result if item["plugin"]["plugin_id"] == "functiongemma")
    assert gemma["compute_capabilities"]["supports_peft"] is True


def test_compute_plan_is_machine_readable(capsys) -> None:
    assert lab_main(["compute-plan", "--plugin", "functiongemma"]) == 0
    result = json.loads(capsys.readouterr().out)

    assert result["schema_version"] == "edge-delegate-compute-plan.v1"
    assert result["effective_batch_size"] == 4
    assert result["maximum_vram_fraction"] == 0.88
