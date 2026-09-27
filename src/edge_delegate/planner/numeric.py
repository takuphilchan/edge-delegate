"""Versioned literal extraction, shared by bounded-task plugins, not intent parsing.

The legacy implementation is deliberately frozen for existing artifact deployments.
The decimal policy accepts one standalone ASCII literal; it never evaluates expressions.
"""

import math
import re
from dataclasses import dataclass
from decimal import Decimal

LEGACY_NUMERIC_POLICY = "legacy.v1"
DECIMAL_NUMERIC_POLICY = "decimal.v1"
NUMERIC_POLICIES = (LEGACY_NUMERIC_POLICY, DECIMAL_NUMERIC_POLICY)
_DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]{1,2})?|\.[0-9]{1,2})\Z")
_NUMBER_WORDS = frozenset(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy "
    "eighty ninety hundred thousand million billion trillion dozen half quarter point dot nan inf infinity".split()
)
_CALCULATION_WORDS = frozenset("plus minus times divided multiplied squared cubed percent".split())


def validate_numeric_policy(policy):
    if not isinstance(policy, str) or policy not in NUMERIC_POLICIES:
        raise ValueError(f"numeric_policy must be one of {', '.join(NUMERIC_POLICIES)}")
    return policy


@dataclass(frozen=True, slots=True)
class NumericLiteral:
    policy: str
    value: float | None
    reason: str | None = None


def _legacy_parameter(text):
    # Do not tighten this grammar: old artifacts/settings retain their interpretation.
    matches = re.findall(r"(?<![\w.])[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?!\w)(?!\.(?!\s|$))", text)
    if len(matches) != 1 or re.search(r"\d\s*[,/eE]\s*[+-]?\d", text):
        return None
    value = float(matches[0])
    return value if math.isfinite(value) else None


def extract_numeric_literal(text, *, policy=LEGACY_NUMERIC_POLICY):
    validate_numeric_policy(policy)
    if policy == LEGACY_NUMERIC_POLICY:
        value = _legacy_parameter(text)
        return NumericLiteral(policy, value, "unresolved_literal" if value is None else None)
    if not isinstance(text, str) or len(text) > 8000:
        return NumericLiteral(policy, None, "invalid_text")
    words = set(re.findall(r"[^\W\d_]+", text.casefold()))
    if words & (_NUMBER_WORDS | _CALCULATION_WORDS):
        return NumericLiteral(policy, None, "unsupported_numeric_expression")
    tokens = text.split()
    if any(token in {"+", "-", "\u2212", ".", "*", "/", "=", "^", "%"} for token in tokens):
        return NumericLiteral(policy, None, "unsupported_numeric_expression")
    # Consider whole tokens, including malformed ones; never salvage a valid substring
    # from an exponent, identifier, separator, unit, Unicode digit, or expression.
    candidates = [token for token in tokens if any(char.isnumeric() for char in token)]
    if len(candidates) != 1:
        return NumericLiteral(policy, None, "missing_or_multiple_literals")
    literal = candidates[0]
    # One terminal sentence mark is allowed. Do not strip runs of punctuation.
    if literal[-1:] in {".", "!", "?"}:
        literal = literal[:-1]
    if _DECIMAL.fullmatch(literal) is None:
        return NumericLiteral(policy, None, "unsupported_numeric_format")
    number = Decimal(literal)
    if not Decimal(-1000) <= number <= Decimal(1000):
        return NumericLiteral(policy, None, "numeric_out_of_range")
    # Decimal validates range/precision before conversion: no rounding into range.
    return NumericLiteral(policy, 0.0 if number == 0 else float(number))


def numeric_parameter(text, *, policy=LEGACY_NUMERIC_POLICY):
    """Compatibility convenience: missing/unsupported numeric values return None."""
    return extract_numeric_literal(text, policy=policy).value
