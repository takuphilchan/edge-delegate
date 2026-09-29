# Architecture

Status: deterministic core, measured planner, and adapter training implemented (`0.3.0`)

## Purpose

Define the boundary between probabilistic planning and deterministic validation, policy enforcement, execution, and audit.

## Request path

1. The coordinator obtains capability cards and a current state snapshot from `DeviceGateway` and
   combines them with the request and configured policy.
2. A planner returns typed, versioned Plan Intermediate Representation (Plan IR). A model planner
   may first retrieve a policy-filtered subset of cards for its prompt.
3. The coordinator binds the plan to the request and validates shape, types, preconditions,
   permissions, approvals, and resource constraints.
4. Missing approval or any other failed check rejects the proposal; the current runtime does not
   acquire approvals itself.
5. Valid `local` and `hybrid` steps enter the executor. The executor verifies the validation
   bindings and repeats deterministic checks against a fresh snapshot before invocation.
6. Valid no-step routes return clarification, defer, deny, or external-required status. Hybrid
   plans execute their local portion and then return external-required status.
7. Planning, validation, and execution events are recorded through the privacy-minimal audit
   interface. No external handoff is transmitted in the current implementation.

## Non-negotiable boundary

The model may propose a plan. It never grants itself permissions, bypasses validation, or directly controls an actuator.

## Dependency direction

- Contracts depend only on the Python standard library.
- Policy and simulation depend on contracts.
- Plan-IR validation depends on contracts and deterministic policy functions.
- Planner adapters depend on contracts but never on the executor.
- Runtime coordination depends on device, audit, clock, and idempotency ports; it must not import the simulator, model lab, datasets, evaluation, training, or external connectors.
- Host-side data, evaluation, model diagnostics, and training live under `edge_delegate_lab` or a selected model plugin.
- External connectors remain outside the local execution boundary.

## Model-plugin boundary

Model families are selected by a stable identifier through the versioned
`edge_delegate.model_plugins.v1` entry-point group. A plugin is a construction-time factory: it
declares compute capabilities and creates a typed planner and diagnostic session. A trainable
plugin additionally owns its model-specific supervised export and trainer. Once a planner is
constructed, the coordinator uses only the shared `Planner` interface and must not branch on a
model family.

Every saved adapter must include a versioned artifact manifest binding the plugin, exact base revision, plan protocol, tokenizer fingerprint, adapter-file fingerprints, dataset fingerprints, recipe, context limit, and precision. New inference loads verify those bindings before attaching an adapter.

## Legacy full-plan FunctionGemma implementation

This section describes the experimental full-plan plugin only. The compact-task plugin uses
select_task and a deterministic compiler. Structured controls and exact command parsing need
no model. See the [current architecture](../docs/system-architecture.md) for all entry paths.

The adapter presents one synthetic `submit_plan(plan_json)` tool. This lets the model propose a complete dependent plan while keeping FunctionGemma's role limited to function calling. The returned string is parsed as strict Plan IR, checked against live contracts, and rejected before execution if any invariant fails. The adapter cannot call capabilities itself.

The backend is replaceable: deterministic tests use a scripted backend, while the optional Transformers backend loads the gated checkpoint lazily. FunctionGemma-specific data export and training live under `edge_delegate_lab/models/functiongemma/`. Model packages and weights are not runtime dependencies of the deterministic core.

This shape follows Google's [FunctionGemma model card](https://ai.google.dev/gemma/docs/functiongemma/model_card), [formatting guidance](https://ai.google.dev/gemma/docs/functiongemma/formatting-and-best-practices), and [full function-calling sequence](https://ai.google.dev/gemma/docs/functiongemma/full-function-calling-sequence-with-functiongemma). The guidance positions FunctionGemma for task-specific function calling and does not describe dependent multi-step workflow planning as a native strength; `submit_plan` makes that limitation measurable without weakening validation.

## Failure and retry semantics

- Malformed planner output, unknown fields, unknown capabilities, stale state, or failed policy checks fail closed.
- Steps execute sequentially in v0; the first execution failure aborts remaining steps.
- Write and physical steps require an idempotency key before execution.
- Reusing a key with identical capability input returns the recorded result.
- Reusing a key with different input is a conflict and does not invoke the capability.
- Approval grants bind request ID, capability ID, exact canonical plan SHA-256, and expiry.

## Implemented deployment boundary

The current executor targets a deterministic host-side simulator. Physical hardware adapters must implement the same capability boundary and preserve output validation, idempotency, timeout, and audit guarantees. Low-Rank Adaptation training and adapter-aware host inference are implemented. Microcontroller-adjacent packaging, physical hardware adapters, external handoff execution, and exported model runtimes are not implemented yet.
