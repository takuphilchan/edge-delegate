from edge_delegate.planner.tasks import BoundedPlanner, TaskDecision
from edge_delegate_lab.numeric_challenge import challenge_cases, run_challenges


def test_independent_expected_cases_exercise_effects_and_wrong_actions():
    cases = {case["case_id"]: case for case in challenge_cases()}
    planner = BoundedPlanner(
        lambda request, _: TaskDecision(
            cases[request.request_id]["task"],
            {"value": cases[request.request_id]["value"]}
            if cases[request.request_id]["task"] == "display_number"
            else {},
        )
    )
    assert all(case["passed"] for case in run_challenges(planner))
    broken = BoundedPlanner(lambda *_: TaskDecision("display_number", {"value": 12}))
    results = list(run_challenges(broken))
    assert any(case["unexpected_invocation"] for case in results)
    assert any(not case["checks"]["final_state"] for case in results)
