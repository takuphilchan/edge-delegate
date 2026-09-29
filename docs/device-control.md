# Device-control command guide

This is the first device-control implementation batch, not the completed production
roadmap. It adds a public structured SDK and exact English commands for two independent
software lights. No model weights, GPU, network, or physical board are used.

The trained temperature plugins are unchanged. Their quality scores do not improve
because this deterministic control path passes tests.

## Try it

Follow the [first-use tutorial](try-it.md) for installation, preview, execution, ambiguity and
replay. This page lists exact commands and control-specific constraints, not a second quickstart.
For automatic developer regression tests, use `bash scripts/test-control.sh` from an activated
development environment. It changes only temporary software state.

## Supported exact commands

| Command | Effect |
| --- | --- |
| `Turn the workbench light on.` | Set workbench power to true |
| `Turn the inspection light off.` | Set inspection power to false |
| `Set the inspection light to 40 percent.` | Set brightness to integer 40/100 |
| `Set the workbench light to 0%.` | Set brightness to zero, without changing power |
| `Read the inspection light brightness.` | Return the current integer brightness |
| `Read the workbench light power.` | Return the current boolean power |
| `Set the light to 40 percent.` | Ask which light; no operation |

Names are case-insensitive exact matches, not fuzzy guesses. Both demo devices share the
alias `light`, which deliberately cannot resolve to one target. Unknown names also ask for
clarification. This initial grammar does not understand pronouns, word-number values,
decimals, relative adjustments, toggles, or compound commands. Unsupported wording never
falls through to model execution. The CLI exits 2 for clarification, denial, or failed
validation/execution; successful previews and confirmed executions exit 0.

## Public Python SDK

The [SDK reference](reference/control-sdk.md) owns the complete example, method signatures,
parameter types, lifecycle and exceptions. Import from `edge_delegate.application`; no lab
imports or model weights are needed. Persist typed requests for identity-safe recovery.

## How execution connects

`ControlSession.request` resolves the name to a stable device/endpoint plus a fingerprint
of its registration, capabilities, and policy (excluding request-scoped approval grants).
The request also binds the explicit catalog fingerprint, including parameter rules and
semantics. Changing an action mapping or numeric bounds invalidates old control requests.
`ControlPlanner` compiles the typed request into one legacy Plan IR step. The target affects
the plan fingerprint, so an approval cannot be copied to another device's otherwise identical
action. The existing validator, coordinator, executor, and durable journal still decide
whether an operation can run. The structured SDK does not bypass them.

Each device has a `GatewaySession`, but all share one authoritative journal. Bound adapter
wrappers check identity/configuration at snapshot, dispatch, and reconciliation boundaries.
Registry membership is fixed for the session. Changed names, capabilities, or policy require
a new binding; replacement devices cannot receive old requests. Request-scoped grants can
be added in a new session without changing the target binding; the runtime checks their
plan fingerprint and expiry. Adapters/plugins remain trusted installed code.

Control envelopes use `edge-control-request.v1`, `edge-control-preview.v1`, and
`edge-control-result.v1`; non-action command responses use `edge-control-response.v1`.
Legacy `plan-ir.v0`, gateway result schemas, and temperature commands are unchanged.
This is a single-target bridge, **not** a new multi-device Plan IR or trained decision protocol.

`ControlSession` takes an explicitly installed `ControlCatalog`; it contains no light-family
branches. `ControlAction` definitions map action IDs to capability IDs with typed parameter
constraints and versioned semantics. Both are public in `edge_delegate.planner.control_catalog`.
An optional installed `command_parser` handles text; structured-only clients need none.
Catalog declarations never grant device permissions. The current request envelope permits
boolean/integer parameters only; future modes, units and richer values require explicit contract
work, not unvalidated passthrough. Generic production pack loading remains a later milestone.

## Recovery and limitations

On a lost acknowledgement, execution returns `execution_unknown`. New operations on that
device are blocked until its recorded operation is resolved. Use:

```python
control.reconcile(target=request.target, request_id=request.request_id)
```

Reconciliation only inspects receipts. It never blindly repeats a write. Recreate the same
registration to recover old work; do not rename devices or replace policies to make an
uncertain request disappear. Do not delete journals/device databases as a recovery strategy.

The emulator commits state and its receipt together in SQLite. This is stronger than many
physical devices can guarantee and is not evidence of exactly-once physical execution.
Database readback confirms software state only, not visible light output.

Currently there is one endpoint per device, one target per request, sequential admission,
and short operations only. This batch does not add a supervised service, whole-request
deadlines, arbitrary parameter types, jobs, logger/display extensions, automations, model training,
generalized task packs, or physical support. The 500 ms execution-step limit remains.
See the [roadmap](roadmap.md#expanded-device-control-delivery) for the next milestones.
