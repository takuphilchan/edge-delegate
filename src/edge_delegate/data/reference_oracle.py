"""Independent sensor/display expectations: no compiler, executor, or model calls.

The reviewed task and expected runtime status are inputs, not inferred labels. This
oracle cannot decide what English means or whether an author's denial was justified.
"""

from copy import deepcopy

from edge_delegate.contracts._validation import json_value

ORACLE_VERSION = "local-display-effects.v1"
TASKS = frozenset({"read_temperature", "show_temperature", "display_number", "clarify", "deny"})
READ = "sensor.temperature.read"
DISPLAY = "display.value.show"


def reference_effects(decision, initial_state, outcome, capability_ids):
    """Derive effects from fixture semantics, never from the plan being checked."""
    if not isinstance(decision, dict) or set(decision) != {"task", "parameters"}:
        raise ValueError("oracle requires task and parameters")
    task, parameters = decision["task"], decision["parameters"]
    if not isinstance(task, str) or task not in TASKS or not isinstance(parameters, dict):
        raise ValueError("unsupported oracle task")
    if task == "display_number":
        if set(parameters) != {"value"} or type(parameters["value"]) not in {int, float}:
            raise ValueError("display_number requires a finite numeric value")
        json_value(parameters["value"], "$.value")
    elif parameters:
        raise ValueError("task takes no parameters")
    state = json_value(deepcopy(initial_state), "$.state")
    if (
        not isinstance(state, dict)
        or not {"environment.temperature_c", "display.last_value"} <= state.keys()
    ):
        raise ValueError("oracle requires both local-display state keys")
    if type(state["environment.temperature_c"]) not in {int, float}:
        raise ValueError("oracle requires a numeric temperature")
    if not isinstance(capability_ids, (list, tuple)) or not all(
        isinstance(item, str) and item for item in capability_ids
    ):
        raise ValueError("oracle requires capability identifiers")
    if outcome not in {"executed", "denied", "clarification_required", "invalid_plan"}:
        raise ValueError("unsupported oracle outcome")
    if task == "clarify" and outcome not in {"clarification_required", "invalid_plan"}:
        raise ValueError("clarification task cannot execute or deny")
    if task == "deny" and outcome not in {"denied", "invalid_plan"}:
        raise ValueError("denial task cannot execute or clarify")
    if task not in {"clarify", "deny"} and outcome == "clarification_required":
        raise ValueError("complete action task cannot require clarification")
    invocations, output = [], None
    if outcome == "executed":
        if task in {"read_temperature", "show_temperature"}:
            invocations.append(READ)
            output = state["environment.temperature_c"]
        if task in {"display_number", "show_temperature"}:
            invocations.append(DISPLAY)
            state["display.last_value"] = (
                parameters["value"] if task == "display_number" else output
            )
            output = True
        if not set(invocations) <= set(capability_ids):
            raise ValueError("expected execution requires unavailable capabilities")
    return {
        "state": state,
        "exact_state": True,
        "final_output": output,
        "invocations": invocations,
        "forbidden_invocations": sorted(set(capability_ids) - set(invocations)),
    }


def check_reference_plan(record):
    """Check expected plan meaning independently of TaskCatalog's builders."""
    plan = record["expected_plan"]
    task = record["expected_task"]["task"]
    route = plan["route"]
    if task in {"clarify", "deny"}:
        if route != task:
            raise ValueError("expected plan does not preserve the intended non-action task")
        return
    if route == "deny" and record["expected_outcome"] == "denied":
        if not record["metadata"].get("restriction_reason", "").strip():
            raise ValueError("denied action needs an independently reviewed restriction reason")
        return
    if route != "local":
        raise ValueError("action task requires local plan or reviewed denial")
    steps = plan["steps"]
    expected_calls = {
        "read_temperature": [READ],
        "show_temperature": [READ, DISPLAY],
        "display_number": [DISPLAY],
    }[task]
    if [step["capability_id"] for step in steps] != expected_calls:
        raise ValueError("expected plan has wrong or additional calls")
    from edge_delegate.evaluation.outcomes import _equal

    arguments = (
        [record["expected_task"]["parameters"]]
        if task == "display_number"
        else [{}]
        if task == "read_temperature"
        else [{}, {"value": {"$ref": steps[0]["step_id"]}}]
    )
    if not _equal([step["arguments"] for step in steps], arguments):
        raise ValueError("expected plan has wrong arguments or dependencies")
