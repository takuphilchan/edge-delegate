# Architecture

Status: implemented deterministic core (`0.1.0`)

## Purpose

Define the boundary between probabilistic planning and deterministic validation, policy enforcement, execution, and audit.

## Planned request path

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

## Failure and retry semantics

- Malformed planner output, unknown fields, unknown capabilities, stale state, or failed policy checks fail closed.
- Steps execute sequentially in v0; the first execution failure aborts remaining steps.
- Write and physical steps require an idempotency key before execution.
- Reusing a key with identical capability input returns the recorded result.
- Reusing a key with different input is a conflict and does not invoke the capability.
- Approval grants bind request ID, capability ID, exact canonical plan SHA-256, and expiry.

## Implemented deployment boundary

The current executor targets a deterministic host-side simulator. Physical hardware adapters must implement the same capability boundary and preserve output validation, idempotency, timeout, and audit guarantees. MCU-adjacent packaging and model runtimes are not implemented yet.
