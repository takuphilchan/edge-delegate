# Architecture

Status: scaffold

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

## To specify next

- Component interfaces and dependency direction
- Failure and retry semantics
- Deployment profiles for MCU-adjacent, mobile, gateway, and desktop hardware
- External connector trust boundary

