"""Human-readable previews, separate from planning and machine result contracts."""

from __future__ import annotations

import json

ROUTE_EXPLANATIONS = {
    "local": "local device steps proposed",
    "hybrid": "local steps and external help proposed; external calls are not implemented",
    "external": "external help requested; external calls are not implemented",
    "clarify": "more information requested",
    "defer": "work postponed",
    "deny": "request declined",
}


def render_result(result: dict[str, object]) -> str:
    """Preserve the existing JSON interface for scripts and detailed inspection."""
    return json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True)


def _text(value: object) -> str:
    # Do not let model-supplied terminal control characters alter the display.
    return "".join(
        char if char.isprintable() or char == "\n" else repr(char)[1:-1] for char in str(value)
    )


def render_query(result: dict[str, object], *, output_format: str = "text") -> str:
    if output_format == "json":
        return render_result(result)
    if output_format != "text":
        raise ValueError(f"unsupported output format: {output_format}")
    lines = [f"Query {result['request']['request_id']}", "Execution: NOT attempted (preview only)"]
    failure = result["failure"]
    if failure is not None:
        lines.extend(
            [
                f"Result: no usable plan ({failure['category']})",
                f"Problem: {failure['message']}",
                "Next: inspect raw output with /raw on or --raw-output; check the model and artifact.",
            ]
        )
    else:
        plan = result["plan"]
        lines.append("Checks: " + ("PASSED" if result["valid"] else "FAILED"))
        lines.append(f"Proposed route: {plan['route']} - {ROUTE_EXPLANATIONS[plan['route']]}")
        for number, step in enumerate(plan["steps"], 1):
            arguments = ", ".join(
                f"{name}=result of {value['$ref']}"
                if isinstance(value, dict) and set(value) == {"$ref"}
                else f"{name}={json.dumps(value, ensure_ascii=False)}"
                for name, value in step["arguments"].items()
            )
            lines.append(f"  {number}. {step['step_id']}: {step['capability_id']}({arguments})")
        if plan["clarification"]:
            lines.append(f"Question: {plan['clarification']}")
        if plan["reason_codes"]:
            lines.append("Reasons: " + ", ".join(plan["reason_codes"]))
        for issue in result["validation"]["issues"]:
            lines.append(f"Problem [{issue['code']}] {issue['path']}: {issue['message']}")
        lines.append("Passing checks does not prove the plan matches your intent.")
    generation = result["generation"]
    if generation is not None:
        lines.append(
            f"Tokens: {generation.get('prompt_tokens', 'unknown')} prompt / "
            f"{generation.get('generated_tokens', 'unknown')} generated"
        )
        if "raw_output" in generation:
            lines.extend(["Raw model output (untrusted text):", str(generation["raw_output"])])
            if generation.get("raw_output_truncated"):
                lines.append("[raw output truncated]")
    return _text("\n".join(lines))


def render_profile(report: dict[str, object], *, output_format: str = "text") -> str:
    if output_format == "json":
        return render_result(report)
    if output_format != "text":
        raise ValueError(f"unsupported output format: {output_format}")
    lines = [
        f"Profile: {report['root']}",
        "Profile files: valid; no model loaded or actions executed",
        f"Policy: {report['policy_id']}",
        f"Snapshot: {report['snapshot']['id']} at {report['snapshot']['observed_at']}",
        f"Connectivity: {report['snapshot']['connectivity']}",
        "Declared capabilities:",
    ]
    for card in report["capabilities"]:
        access = (
            "allowed by capability policy"
            if card["policy_allowed"]
            else "blocked by capability policy"
        )
        lines.append(f"  {card['id']} [{card['side_effect']}; {access}]")
        lines.append(f"    {card['description']}")
        if card["missing_permissions"]:
            lines.append("    Missing permissions: " + ", ".join(card["missing_permissions"]))
    lines.extend(f"Warning: {warning}" for warning in report["warnings"])
    lines.append(str(report["note"]))
    return _text("\n".join(lines))


def render_simulation(result: dict[str, object], *, output_format: str = "text") -> str:
    if output_format == "json":
        return render_result(result)
    if output_format != "text":
        raise ValueError(f"unsupported output format: {output_format}")
    lines = [
        "Device: local-display SIMULATOR (no physical hardware)",
        f"Runtime outcome: {result['status']}",
        f"Device invocations: {result['invocation_count']}",
    ]
    if result["plan"] is not None:
        lines.append(f"Proposed route: {result['plan']['route']}")
    if result["message"]:
        lines.append(f"Message: {result['message']}")
    if result["validation"] is not None:
        for issue in result["validation"]["issues"]:
            lines.append(f"Problem [{issue['code']}] {issue['path']}: {issue['message']}")
    if result["execution"] is not None:
        for step in result["execution"]["steps"]:
            lines.append(f"  {step['step_id']}: {step['status']} -> {json.dumps(step['result'])}")
        if result["execution"]["error"]:
            lines.append(f"Execution error: {result['execution']['error']}")
    lines.extend(
        [
            f"Before: {json.dumps(result['state_before'], sort_keys=True)}",
            f"After:  {json.dumps(result['state_after'], sort_keys=True)}",
            "External calls: none. Intent correctness: not evaluated.",
            "Successful execution does not prove the model understood your request.",
        ]
    )
    return _text("\n".join(lines))


def render_gateway(report: dict[str, object], *, output_format: str = "text") -> str:
    """Readable actual execution, without confusing cached results with new actions."""
    if output_format == "json":
        return json.dumps(report, sort_keys=True, default=str)
    if output_format != "text":
        raise ValueError(f"unsupported output format: {output_format}")
    result = report["result"]
    lines = [f"Request: {result['request_id']}", f"Outcome: {result['status']}"]
    if result.get("message"):
        lines.append(f"Message: {result['message']}")
    plan = result.get("plan")
    if plan and plan.get("clarification"):
        lines.append(f"Question: {plan['clarification']}")
    validation = result.get("validation")
    if validation:
        for issue in validation.get("issues", []):
            lines.append(f"Check [{issue['code']}]: {issue['message']}")
    execution = result.get("execution")
    if execution:
        for step in execution["steps"]:
            lines.append(
                f"  {step['capability_id']}: {step['status']} -> {json.dumps(step['result'])}"
            )
            if step.get("error"):
                lines.append(f"    {step['error']}")
        if execution.get("error"):
            lines.append(f"Execution detail: {execution['error']}")
        if any(step["status"] == "replayed" for step in execution["steps"]):
            lines.append(
                "Replayed steps use recorded results; those device actions were not repeated."
            )
    if result["status"] == "request_conflict":
        lines.append("Use the original input to retry; use a new request ID for different work.")
    if result["status"] == "execution_unknown":
        lines.append(
            "An action may have happened. Reconcile this request; do not blindly retry with a new ID."
        )
    lines.append(f"Request time: {report['total_latency_ms']:.1f} ms (excludes model loading)")
    lines.append(
        "Intent correctness: not evaluated. Physical-device qualification: not established."
    )
    return _text("\n".join(lines))
