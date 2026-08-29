"""Regression tests for planner-output shapes that previously bypass weak validators."""

from edge_delegate.contracts import PlanIR, PlanStep, Route, StepReference
from edge_delegate.ir import check_plan


def test_duplicate_step_identifiers_are_rejected(demo_world, demo_policy) -> None:
    plan = PlanIR(
        request_id="req-duplicate",
        route=Route.LOCAL,
        steps=(
            PlanStep(step_id="same", capability_id="sensor.temperature.read"),
            PlanStep(step_id="same", capability_id="sensor.temperature.read"),
        ),
    )
    report = check_plan(
        plan,
        demo_world.capability_cards,
        demo_world.snapshot(),
        demo_policy,
        now=demo_world.clock.now(),
    )
    assert "duplicate_step" in {issue.code for issue in report.issues}


def test_forward_references_are_rejected(demo_world, demo_policy) -> None:
    plan = PlanIR(
        request_id="req-forward-ref",
        route=Route.LOCAL,
        steps=(
            PlanStep(
                step_id="show",
                capability_id="display.value.show",
                arguments={"value": StepReference("read")},
                idempotency_key="forward-ref",
            ),
            PlanStep(step_id="read", capability_id="sensor.temperature.read"),
        ),
    )
    report = check_plan(
        plan,
        demo_world.capability_cards,
        demo_world.snapshot(),
        demo_policy,
        now=demo_world.clock.now(),
    )
    assert "invalid_reference" in {issue.code for issue in report.issues}


def test_duplicate_idempotency_keys_are_rejected_before_execution(
    demo_world, demo_policy
) -> None:
    plan = PlanIR(
        request_id="req-duplicate-key",
        route=Route.LOCAL,
        steps=(
            PlanStep(
                step_id="show_one",
                capability_id="display.value.show",
                arguments={"value": 1},
                idempotency_key="same-key",
            ),
            PlanStep(
                step_id="show_two",
                capability_id="display.value.show",
                arguments={"value": 2},
                idempotency_key="same-key",
            ),
        ),
    )
    report = check_plan(
        plan,
        demo_world.capability_cards,
        demo_world.snapshot(),
        demo_policy,
        now=demo_world.clock.now(),
    )
    assert "duplicate_idempotency" in {issue.code for issue in report.issues}
