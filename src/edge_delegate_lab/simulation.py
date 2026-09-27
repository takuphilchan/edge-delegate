"""Compose a model-neutral planner with the real runtime and an explicit fake device."""

from dataclasses import asdict

from edge_delegate.contracts import PlanningRequest
from edge_delegate.planner import Planner
from edge_delegate.runtime import Coordinator, Executor
from edge_delegate.simulator.examples import local_display


def run_simulation(planner: Planner, request: PlanningRequest) -> dict[str, object]:
    world, policy = local_display()
    before = dict(world.snapshot().values)
    attempted = []
    result = Coordinator(
        planner=planner, world=world, policy=policy, executor=Executor(on_invoke=attempted.append)
    ).handle(request)
    return {
        "schema_version": "edge-delegate-simulation.v1",
        "scenario": "local-display",
        "device_kind": "simulator",
        "request": request.to_dict(),
        "status": result.status.value,
        "message": result.message,
        "plan": None if result.plan is None else result.plan.to_dict(),
        "validation": None
        if result.validation is None
        else {
            "valid": result.validation.valid,
            "issues": [
                {"code": issue.code, "path": issue.path, "message": issue.message}
                for issue in result.validation.issues
            ],
        },
        "execution": None
        if result.execution is None
        else {
            "status": result.execution.status.value,
            "error": result.execution.error,
            "final_output": result.execution.final_output,
            "steps": [
                {
                    "step_id": step.step_id,
                    "capability_id": step.capability_id,
                    "status": step.status.value,
                    "result": step.result,
                    "error": step.error,
                }
                for step in result.execution.steps
            ],
        },
        "state_before": before,
        "state_after": dict(world.snapshot().values),
        "invocation_count": len(world.invocations),
        "invocations": [asdict(invocation) for invocation in world.invocations],
        "attempted_invocations": attempted,
        "external_call_attempted": False,
        "intent_correctness": "not_evaluated",
    }
