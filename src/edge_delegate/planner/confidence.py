"""Planner confidence validation and abstention decisions."""


def require_probability(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("confidence must be numeric")
    if not 0 <= value <= 1:
        raise ValueError("confidence must be between zero and one")
    return float(value)


def should_abstain(confidence: float, *, threshold: float) -> bool:
    return require_probability(confidence) < require_probability(threshold)
