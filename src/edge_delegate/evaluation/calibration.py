"""Confidence, calibration, and abstention metrics."""

from __future__ import annotations

from dataclasses import dataclass


def brier_score(confidences: list[float], outcomes: list[bool]) -> float:
    if len(confidences) != len(outcomes):
        raise ValueError("confidence and outcome lengths must match")
    if not confidences:
        return 0.0
    return sum(
        (confidence - float(outcome)) ** 2
        for confidence, outcome in zip(confidences, outcomes, strict=True)
    ) / len(confidences)


def expected_calibration_error(
    confidences: list[float],
    outcomes: list[bool],
    *,
    bins: int = 10,
) -> float:
    if len(confidences) != len(outcomes):
        raise ValueError("confidence and outcome lengths must match")
    if bins < 1:
        raise ValueError("bin count must be positive")
    if not confidences:
        return 0.0
    total = len(confidences)
    error = 0.0
    for bin_index in range(bins):
        lower = bin_index / bins
        upper = (bin_index + 1) / bins
        members = [
            index
            for index, confidence in enumerate(confidences)
            if lower <= confidence <= upper and (bin_index == bins - 1 or confidence < upper)
        ]
        if not members:
            continue
        mean_confidence = sum(confidences[index] for index in members) / len(members)
        accuracy = sum(outcomes[index] for index in members) / len(members)
        error += len(members) / total * abs(mean_confidence - accuracy)
    return error


@dataclass(frozen=True, slots=True)
class SelectivePoint:
    threshold: float
    coverage: float
    accuracy: float


def selective_accuracy(
    confidences: list[float],
    outcomes: list[bool],
    *,
    thresholds: tuple[float, ...] = (0.0, 0.5, 0.7, 0.8, 0.9, 0.95),
) -> tuple[SelectivePoint, ...]:
    if len(confidences) != len(outcomes):
        raise ValueError("confidence and outcome lengths must match")
    total = len(confidences)
    points: list[SelectivePoint] = []
    for threshold in thresholds:
        selected = [
            outcome
            for confidence, outcome in zip(confidences, outcomes, strict=True)
            if confidence >= threshold
        ]
        points.append(
            SelectivePoint(
                threshold=threshold,
                coverage=len(selected) / total if total else 0.0,
                accuracy=sum(selected) / len(selected) if selected else 0.0,
            )
        )
    return tuple(points)
