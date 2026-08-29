# Architecture

Status: deterministic core and prompt-planner baseline implemented (`0.2.0`)

## Purpose

Define the boundary between probabilistic planning and deterministic validation, policy enforcement, execution, and audit.

## Request path

1. Read a request, capability card, device state, and policy.
2. Retrieve only capabilities relevant to the request.
3. Produce a versioned plan IR and a route decision.
4. Validate syntax, types, preconditions, permissions, and resource constraints.
5. Ask for clarification or approval when required.
6. Execute locally, combine local and external work, or produce a minimal external handoff.
7. Record a privacy-aware audit event and outcome.

## Non-negotiable boundary

The model may propose a plan. It never grants itself permissions, bypasses validation, or directly controls an actuator.

## Dependency direction

- Contracts depend only on the Python standard library.
- Policy and simulation depend on contracts.
- IR validation depends on contracts and deterministic policy functions.
- Planner adapters depend on contracts but never on the executor.
- Runtime coordination composes planner, validation, simulation or hardware adapters, and audit.
- External connectors remain outside the local execution boundary.

## FunctionGemma boundary

The adapter presents one synthetic `submit_plan(plan_json)` tool. This lets the model propose a complete dependent plan while keeping FunctionGemma's role limited to function calling. The returned string is parsed as strict Plan IR, checked against live contracts, and rejected before execution if any invariant fails. The adapter cannot call capabilities itself.

The backend is replaceable: deterministic tests use a scripted backend, while the optional Transformers backend loads the gated checkpoint lazily. Model packages and weights are not runtime dependencies of the deterministic core.

This shape follows Google's [FunctionGemma model card](https://ai.google.dev/gemma/docs/functiongemma/model_card), [formatting guidance](https://ai.google.dev/gemma/docs/functiongemma/formatting-and-best-practices), and [full function-calling sequence](https://ai.google.dev/gemma/docs/functiongemma/full-function-calling-sequence-with-functiongemma). The guidance positions FunctionGemma for task-specific function calling and does not describe dependent multi-step workflow planning as a native strength; `submit_plan` makes that limitation measurable without weakening validation.

## Failure and retry semantics

- Malformed planner output, unknown fields, unknown capabilities, stale state, or failed policy checks fail closed.
- Steps execute sequentially in v0; the first execution failure aborts remaining steps.
- Write and physical steps require an idempotency key before execution.
- Reusing a key with identical capability input returns the recorded result.
- Reusing a key with different input is a conflict and does not invoke the capability.
- Approval grants bind request ID, capability ID, exact canonical plan SHA-256, and expiry.

## Implemented deployment boundary

The current executor targets a deterministic host-side simulator. Physical hardware adapters must implement the same capability boundary and preserve output validation, idempotency, timeout, and audit guarantees. MCU-adjacent packaging, external handoff execution, training, and exported model runtimes are not implemented yet.
