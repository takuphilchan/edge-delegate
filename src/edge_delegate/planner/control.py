"""Deterministic single-target control compiler and exact command frontend.

No model, implicit target, unit guessing, relative commands, or partial matches.
"""

import hashlib
import json
import re

from edge_delegate.contracts import PlanIR, PlanStep, Route
from edge_delegate.contracts.capability import ValueKind, ValueSpec
from edge_delegate.contracts.control import ControlRequest

from .base import PlannerOutputError
from .control_catalog import ControlAction, ControlCatalog

LIGHT_ACTIONS = frozenset(
    {
        "light.power.set",
        "light.power.read",
        "light.brightness.set",
        "light.brightness.read",
    }
)


def light_catalog():
    return ControlCatalog(
        "light-controls.v1",
        tuple(
            ControlAction(
                action,
                action,
                (
                    {}
                    if action.endswith(".read")
                    else {"on": ValueSpec(ValueKind.BOOLEAN)}
                    if action == "light.power.set"
                    else {"percent": ValueSpec(ValueKind.INTEGER, minimum=0, maximum=100)}
                ),
                "Boolean power; integer brightness percent 0-100; setting brightness never changes power.",
            )
            for action in sorted(LIGHT_ACTIONS)
        ),
    )


def validate_light_action(action, parameters):
    if action not in LIGHT_ACTIONS:
        raise ValueError("unsupported light action")
    if action.endswith(".read"):
        valid = not parameters
    elif action == "light.power.set":
        valid = set(parameters) == {"on"} and type(parameters["on"]) is bool
    else:
        valid = (
            set(parameters) == {"percent"}
            and type(parameters["percent"]) is int
            and 0 <= parameters["percent"] <= 100
        )
    if not valid:
        raise ValueError("invalid light parameters: power is boolean; brightness is integer 0-100")


class ControlPlanner:
    """An internal bridge into the unchanged validated Plan-IR runtime."""

    def __init__(self, target, catalog):
        self.target = target
        self.catalog = catalog

    def plan(self, request, context):
        del context
        try:
            control = ControlRequest.from_dict(json.loads(request.text))
            if control.catalog_sha256 != self.catalog.fingerprint:
                raise ValueError("control catalog changed")
            action = self.catalog.validate(control.action, control.parameters)
            if control.target != self.target or control.request_id != request.request_id:
                raise ValueError("control target/request binding mismatch")
        except (ValueError, TypeError, KeyError) as exc:
            raise PlannerOutputError(str(exc)) from exc
        # The plan fingerprint (and hence any approval) includes the target binding.
        step_id = "control_" + control.target.binding_sha256[:48]
        operation_key = hashlib.sha256(request.text.encode()).hexdigest()
        return PlanIR(
            request_id=request.request_id,
            route=Route.LOCAL,
            steps=(
                PlanStep(
                    step_id,
                    action.capability_id,
                    dict(control.parameters),
                    timeout_ms=500,
                    idempotency_key=operation_key,
                ),
            ),
        )


class ControlInputError(ValueError):
    def __init__(self, message, status="denied"):
        super().__init__(message)
        self.status = status


def parse_light_command(text):
    """Return an unresolved name/action/parameters; resolution is a separate boundary."""
    if not isinstance(text, str) or not text.strip() or len(text) > 8000:
        raise ControlInputError("Enter a bounded light command.")
    text = " ".join(text.strip().split())
    if text.endswith("."):
        text = text[:-1]
    # Names are literal registered names. Quotes and compound syntax are not repaired.
    target = r"(?P<target>[a-zA-Z0-9][a-zA-Z0-9 _-]{0,127}?)"
    match = re.fullmatch(rf"turn (?:the )?{target} (?P<power>on|off)", text, re.I | re.ASCII)
    if match:
        return match["target"], "light.power.set", {"on": match["power"].lower() == "on"}
    match = re.fullmatch(
        rf"set (?:the )?{target} to (?P<value>[0-9]{{1,3}})(?: percent|%)",
        text,
        re.I | re.ASCII,
    )
    if match:
        value = int(match["value"])
        if value > 100:
            raise ControlInputError(
                "Brightness must be an integer from 0 to 100 percent.", "clarification_required"
            )
        return match["target"], "light.brightness.set", {"percent": value}
    match = re.fullmatch(
        rf"read (?:the )?{target} (?P<field>power|brightness)",
        text,
        re.I | re.ASCII,
    )
    if match:
        return match["target"], f"light.{match['field'].lower()}.read", {}
    raise ControlInputError("Unsupported command. Use an explicit device and one light action.")
