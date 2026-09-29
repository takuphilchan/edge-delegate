# Results and failure semantics

[Documentation home](../README.md) | [SDK](control-sdk.md) | [Recovery](../how-to/reconcile.md)

Read the envelope before interpreting a field named status. A proposed route, validation result,
runtime outcome and individual operation receipt answer different questions.

## Envelopes

| schema_version | Meaning |
| --- | --- |
| edge-control-preview.v1 | Target plus gateway preview; no execution |
| edge-control-result.v1 | Target plus gateway execution result |
| edge-control-response.v1 | Non-action response such as clarification or denial |
| edge-gateway-preview.v1 | Proposed plan and validation with execution_attempted false |
| edge-gateway-result.v1 | Runtime result and request timing; not intent certification |
| edge-gateway-reconciliation.v1 | Receipt lookup; no resumed task or automatic completion proof |
| plan-ir.v0 | Proposed route/steps, not authority to execute |

The control-demo CLI adds mode, software_only, trained_model and current software state around
the response. It is not itself a new gateway schema. JSON booleans are real booleans, not strings.

## Proposal and validation

Plan routes are local, hybrid, external, clarify, defer and deny. A route describes proposed
handling, not whether actions happened. External/hybrid routes do not cause cloud calls in the
current implementation.

An empty validation issues list means checks passed against that context. It does not prove
intent correctness, physical effects or fresh state forever. Execution checks again.

## Runtime outcomes

| Status | Meaning / next step |
| --- | --- |
| executed | Proposed local operations completed; inspect step receipts and returned values |
| clarification_required | No local work; submit a complete clarified request, not a chat fragment |
| denied / deferred | Declined / deferred; do not treat as completion |
| external_required | External work would be required; no external connector was invoked |
| invalid_plan | Proposal failed validation; inspect issues, do not bypass checks |
| planner_failed | Planner could not supply a valid proposal |
| execution_failed | Local execution failed; inspect completed steps; no implied rollback |
| execution_unknown | At least one operation has an uncertain outcome; reconcile before new work |
| request_conflict | Reused request identity conflicts with recorded input, device or plan |

A hybrid plan can have completed local steps and still return external_required. Status alone
therefore cannot establish that no action occurred. Inspect the execution details.

## Step receipts

| Step status | Meaning |
| --- | --- |
| succeeded | Confirmed result for this dispatch |
| replayed | Previously recorded result returned; not another dispatch or a fresh read |
| failed | Runtime reports failure; inspect its error and earlier steps |
| unknown | Operation may have completed; lack of acknowledgement is not proof of no effect |

The execution-level status can be succeeded, failed or unknown. There is no atomic rollback
across steps or devices. Reconciliation returns not_found, unknown or reconciled and reports
device_actions_dispatched: 0 and task_completion_verified: false. Even reconciled is not a
promise that every dependent step ran or that visible physical effects matched intent.

## Exit codes

For control-demo: 0 means a valid preview or successful execution; 2 means non-action
clarification/denial or unsuccessful validation/execution; 1 means a caught input/setup error.
Other commands have their own semantics: inspect their help and reports. Do not apply this
mapping to all training/evaluation commands.

For the lab simulate command: 0 means local simulated execution completed, 2 means it did
not complete, 1 means setup/input failure. Simulation is not physical execution.

## Latency and qualification flags

Gateway total_latency_ms measures request handling, excluding caller-owned model loading.
Null stage timings mean unmeasured, not zero cost. The control path does not use model inference.
physical_device_qualified: false means exactly that; software success cannot flip it into a
hardware claim. A small smoke run is not the preregistered release benchmark.
