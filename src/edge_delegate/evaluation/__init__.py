"""Software, model, safety, and hardware evaluation."""

from .calibration import (
    SelectivePoint,
    brier_score,
    expected_calibration_error,
    selective_accuracy,
)
from .execution import PlanComparison, compare_plans
from .model_doctor import DoctorCaseResult, ModelDoctor, select_controlled_records
from .runner import CaseResult, EvaluationRunner

__all__ = [
    "CaseResult",
    "DoctorCaseResult",
    "EvaluationRunner",
    "ModelDoctor",
    "PlanComparison",
    "SelectivePoint",
    "brier_score",
    "compare_plans",
    "expected_calibration_error",
    "select_controlled_records",
    "selective_accuracy",
]
