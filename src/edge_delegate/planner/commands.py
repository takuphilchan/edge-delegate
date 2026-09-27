"""Closed English command grammar, not a learned intent classifier.

Positive actions require a full-string match. Unknown text never falls through to
model execution. Numeric interpretation stays in the versioned literal parser.
"""

import re
from dataclasses import dataclass

from .numeric import DECIMAL_NUMERIC_POLICY, extract_numeric_literal
from .tasks import TaskDecision

COMMAND_POLICY = "bounded-english.v1"
_FLAGS = re.IGNORECASE | re.ASCII
_TEMPERATURE = r"(?:the )?(?:(?:current|ambient|local) )?temperature"
_TARGET = r"(?:the )?(?:local )?(?:display|screen)"
_READ = re.compile(rf"(?:read|get|tell me) {_TEMPERATURE}", _FLAGS)
_SHOW = re.compile(rf"(?:show|display) {_TEMPERATURE}(?: on {_TARGET})?", _FLAGS)
_PUT = re.compile(rf"put (?P<literal>\S+) on {_TARGET}", _FLAGS)
_NUMBER = re.compile(
    rf"(?:display|show) (?:the (?:number|value) )?(?P<literal>\S+)(?: on {_TARGET})?", _FLAGS
)
_MISSING = re.compile(
    r"(?:display|show|put)(?: (?:it|that|a number|a value|the number|the value))?", _FLAGS
)
_NUMERIC_PARTS = re.compile(
    r"(?:display|show) (?P<parts>[+\-\d.,/ _]+(?: or [+\-\d.,/ _]+)?)", _FLAGS
)


@dataclass(frozen=True)
class CommandInterpretation:
    decision: TaskDecision
    reason: str


def interpret_command(text):
    """Return an action only for the documented grammar; no substring repair."""
    if not isinstance(text, str) or not text or len(text) > 8000:
        return CommandInterpretation(TaskDecision("deny"), "invalid_request")
    # ASCII whitespace only. Do not normalize Unicode lookalikes into accepted commands.
    core = re.sub(r"[ \t\r\n]+", " ", text).strip(" \t\r\n")
    if core[-1:] in {".", "!", "?"}:
        core = core[:-1]
    if core.lower().startswith("please "):
        core = core[7:]
    if core.lower().endswith(" please"):
        core = core[:-7]
        if core.endswith("."):
            core = core[:-1]
    if _READ.fullmatch(core):
        return CommandInterpretation(TaskDecision("read_temperature"), "complete_read_command")
    if _SHOW.fullmatch(core):
        return CommandInterpretation(TaskDecision("show_temperature"), "complete_show_command")
    if _MISSING.fullmatch(core):
        return CommandInterpretation(TaskDecision("clarify"), "missing_parameter_or_reference")
    if _NUMBER.fullmatch(core) or _PUT.fullmatch(core) or _NUMERIC_PARTS.fullmatch(core):
        literal = extract_numeric_literal(text, policy=DECIMAL_NUMERIC_POLICY)
        if literal.value is None:
            return CommandInterpretation(
                TaskDecision("clarify"), literal.reason or "invalid_literal"
            )
        # _NUMERIC_PARTS is only an error/clarification recognizer, not permission to act.
        if not (_NUMBER.fullmatch(core) or _PUT.fullmatch(core)):
            return CommandInterpretation(TaskDecision("clarify"), "unsupported_numeric_phrase")
        return CommandInterpretation(
            TaskDecision("display_number", {"value": literal.value}), "complete_number_command"
        )
    return CommandInterpretation(TaskDecision("deny"), "outside_command_grammar")
