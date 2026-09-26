# Contracts and Safety

[Documentation home](README.md) | [Glossary](glossary.md)

This page owns the runtime data contracts and deterministic safety checks. For component wiring,
read [System architecture](system-architecture.md). For model training, read
[Model lifecycle](model-lifecycle.md).

## Why contracts come before the model

The planner does not receive an open-ended instruction to control a device. It receives four typed inputs and may return only one typed Plan Intermediate Representation (Plan IR). This makes the model's proposal inspectable and keeps authority in deterministic code.

```text
PlanningRequest + CapabilityCard[] + DeviceState + Policy
                         |
                         v
                  planner proposes PlanIR
                         |
                         v
       the same cards, state, and policy validate the proposal
                    /                    \
               rejected              ValidatedPlan
```

## The five runtime contracts

| Contract | What it represents | Security purpose |
| --- | --- | --- |
| `PlanningRequest` | Request ID, natural-language text, locale, bounded metadata | Binds the eventual plan to one caller request. |
| `CapabilityCard` | One available operation, argument/result types, side effect, permissions, approval, preconditions, privacy, and cost | Defines the complete allowlist visible to planning and validation. |
| `DeviceState` | Timestamped snapshot, connectivity, memory, battery, and named values | Prevents plans from assuming unavailable or stale device conditions. |
| `Policy` | Allowed/denied capabilities, granted permissions, approvals, external rules, state age, and resource budget | Keeps authorization outside the model. |
| `PlanIR` | Route, ordered steps, arguments/references, reason codes, confidence, and clarification | Provides a bounded data structure instead of generated code. |

Public JavaScript Object Notation (JSON) Schemas for capability cards, device state, policy,
Plan IR, and external handoff live in [`schemas/`](../schemas/). The Python contract decoders reject
unknown fields rather than silently ignoring them.

## Plan IR example

The local display example composes a read capability with a write capability:

```json
{
  "schema_version": "plan-ir.v0",
  "request_id": "example-display-temperature",
  "route": "local",
  "steps": [
    {
      "step_id": "read_temperature",
      "capability_id": "sensor.temperature.read"
    },
    {
      "step_id": "show_temperature",
      "capability_id": "display.value.show",
      "arguments": {
        "value": {"$ref": "read_temperature"}
      },
      "idempotency_key": "example-show-temperature"
    }
  ],
  "reason_codes": [],
  "confidence": 1.0,
  "clarification": null
}
```

Read the fields as follows:

| Field | Meaning |
| --- | --- |
| `schema_version` | Selects the exact plan contract. Readers and code must not guess across versions. |
| `request_id` | Binds the proposal to the request currently being handled. |
| `route` | States the high-level outcome. `local` means the proposal contains device work that may run locally after validation. |
| `steps` | Lists capability calls in execution order. Each `step_id` is unique within the plan. |
| `capability_id` | Selects one operation from the device's declared capability cards. It is not an arbitrary function name. |
| `arguments` | Supplies typed input values. A `$ref` uses the result of an earlier successful step. |
| `idempotency_key` | Makes retries of a write or physical operation detectable and safe. |
| `reason_codes` | Explains non-action outcomes such as defer or deny; it is empty for this successful local proposal. |
| `confidence` | Records the planner's self-reported confidence for measurement. It cannot override validation. |
| `clarification` | Contains a question only when the route is `clarify`; otherwise it is `null`. |

`{"$ref": "read_temperature"}` may reference only an earlier step. The validator confirms that the referenced result type matches the destination argument type. The write step needs an idempotency key; the read step does not.

The complete executable inputs are in [`examples/local-display/`](../examples/local-display/).

## Validation chain

Validation is layered so an early parsing success cannot be mistaken for an executable plan.

| Layer | Representative checks | Failure result |
| --- | --- | --- |
| Bounded parse | Input size/depth, duplicate keys, valid JSON, finite numbers, known fields, supported schema version | No `PlanIR` is produced. |
| Request binding | `plan.request_id == request.request_id` | Coordinator returns `invalid_plan`. |
| Route shape | Local/hybrid steps, clarification text, defer/deny reason codes, external policy | Static issue with code such as `route_shape` or `external_denied`. |
| Capability allowlist | Capability exists, is policy-allowed, and is not denied | Static rejection. |
| Arguments and references | Required/unknown arguments, value types/ranges/enums, reference order, result compatibility | Static rejection. |
| State and preconditions | Snapshot freshness, predicates, connectivity, memory | Static rejection. |
| Authorization | Permissions and exact-plan approval grants | Static rejection. |
| Resource budget | Step count, timeout, total latency, energy, and peak memory | Static rejection. |
| Side effects | Write/physical idempotency requirements | Static rejection. |
| Execution binding | Exact plan, capability-set, and policy fingerprints still match | Executor stops before invocation. |
| Fresh execution preflight | A new device snapshot still passes the deterministic checks | Executor returns a failed execution without invoking a step. |
| Resolved step inputs | Actual reference values satisfy destination types, ranges, and enums | Executor stops before invoking that step. |
| Device and cached outputs | JSON-compatible finite values satisfy the declared result contract | Failed execution; later steps are not attempted and invalid results are not recorded. |

Only `validate_plan(...)` can issue a `ValidatedPlan`; callers cannot construct one directly. The
object records fingerprints for the exact plan, capability set, policy, and state used during
validation. The executor verifies those bindings and checks a fresh snapshot before invoking the
first step.

## Permissions and approvals are different

- A permission is a policy-level grant such as `display.write`.
- An approval is a temporary grant bound to request ID, capability ID, expiration, and the SHA-256 fingerprint of the exact canonical plan.

Changing a step, argument, order, or idempotency key changes the plan fingerprint, so a previously issued approval cannot authorize a modified proposal.

## Execution and replay behavior

The v0 executor is sequential:

1. Resolve references from prior successful step outputs.
2. Validate and copy the resolved arguments, including the destination's range and enum constraints.
3. Fingerprint the capability ID and resolved arguments, then look up the capability-scoped idempotency key.
4. Obtain the recorded result, reject conflicting reuse, or invoke the capability.
5. Validate and copy the result before using it: it must be finite JSON data matching the capability's declared result. A capability with no result may return only `None` (JSON `null`). This check also applies to replayed results.
6. Record only validated new results, then make the result available to later steps.
7. Stop at the first failure; later steps are not attempted.

These checks belong to the executor and apply to every `DeviceGateway`, not just the simulator.
For example, a sensor returning text where it promised a number cannot pass that value to a
display. A valid number outside the display's permitted range is also rejected before the
display is invoked. An output-validation failure cannot undo a physical action that already
happened; it is not evidence that retrying that action is safe.

The in-memory stores make these rules testable. Production hardware will require persistent stores, timeouts/cancellation, and explicit partial-failure handling.

## Audit privacy

Audit events record request ID, event type, outcome, timestamp, route, plan hash, issue count, or step count. They deliberately exclude natural-language request text and step arguments. The current sink is in-memory and intended for testing; retention and persistence remain deployment work.

## Model and connector trust matrix

| Input or component | Trusted to propose? | Trusted to authorize? | Trusted to execute? |
| --- | ---: | ---: | ---: |
| Local planner model | Yes | No | No |
| External model response | Future proposal/context only | No | No |
| Capability card | Describes an operation | Only with policy checks | No |
| Policy and bound approval | No | Yes, deterministically | No |
| Static validator | No | Enforces authorization | No |
| Executor with `ValidatedPlan` | No | No | Yes |

## External processing boundary

`handoff.v0` defines a minimal external request with redacted context, included privacy classes,
removed fields, questions, and expiry. The data type and privacy helpers exist, but the
coordinator does not yet construct a handoff and no connector transmits one. An `external` or
`hybrid` route therefore returns `external_required`; it does not silently call a cloud model.

Before connector wiring, the project still needs redaction, outbound policy enforcement, response constraints, response validation, timeouts/cancellation, and provenance. See [`specs/external-handoff-v0.md`](../specs/external-handoff-v0.md) and [`specs/threat-model.md`](../specs/threat-model.md).

[Previous: System architecture](system-architecture.md) | [Next: Model plugins, artifacts, and compute](model-plugins-and-compute.md)
