"""Explicit deterministic baseline for low-impact reference commands. No model loaded."""

import time

from edge_delegate import __version__
from edge_delegate.planner.commands import COMMAND_POLICY, interpret_command
from edge_delegate.planner.tasks import BoundedPlanner

from .api import ModelPluginDescriptor
from .compute import ModelComputeCapabilities


class CommandSession:
    def __init__(self):
        self.model_info = {
            "model_id": "bounded-commands",
            "trained": False,
            "qualified": False,
            "planner_kind": "deterministic_grammar",
            "command_policy": COMMAND_POLICY,
            "numeric_policy": "decimal.v1",
        }
        self.planner = BoundedPlanner(self.decide)
        self._last = None

    def decide(self, request, context):
        started = time.perf_counter()
        interpreted = interpret_command(request.text)
        self._last = {
            "latency_ms": (time.perf_counter() - started) * 1000,
            "planner_kind": "deterministic_grammar",
            "model_generation_used": False,
            "command_policy": COMMAND_POLICY,
            "numeric_policy": "decimal.v1",
            "decision": interpreted.decision.to_dict(),
            "reason": interpreted.reason,
        }
        return interpreted.decision

    def last_generation(self, *, include_raw_output):
        # No synthetic model output: these are explicitly command-router diagnostics.
        return None if self._last is None else dict(self._last)

    def selected_capability_ids(self, request, context):
        return tuple(card.capability_id for card in context.capabilities)

    def classify_error(self, error):
        return "command_contract_error"


class BoundedCommandsPlugin:
    descriptor = ModelPluginDescriptor(
        "bounded-commands",
        __version__,
        "Closed command grammar (NOT a trained model)",
        ("bounded-task",),
    )
    compute_capabilities = ModelComputeCapabilities(("fp32",), ("none",), False, False, False, 8000)

    def create_diagnostic_session(self, *, artifact_path, settings):
        if artifact_path is not None:
            raise ValueError("bounded-commands does not load or repair model artifacts")
        if settings != {"numeric_policy": "decimal.v1"}:
            raise ValueError("bounded-commands requires only explicit numeric_policy decimal.v1")
        return CommandSession()

    def create_planner(self, *, artifact_path, settings):
        return self.create_diagnostic_session(
            artifact_path=artifact_path, settings=settings
        ).planner


plugin = BoundedCommandsPlugin()
