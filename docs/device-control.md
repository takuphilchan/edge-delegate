# Control two software lights

This is the first device-control implementation batch, not the completed production
roadmap. It adds a public structured SDK and exact English commands for two independent
software lights. No model weights, GPU, network, or physical board are used.

The trained temperature plugins are unchanged. Their quality scores do not improve
because this deterministic control path passes tests.

## Try it

Use your activated Python environment, then install from the repository root:

```bash
python -m pip install -e ".[dev]"
bash scripts/test-control.sh
```

That script automatically tests controls, wrong-target prevention, permissions, duplicate
requests, restart, and lost-acknowledgement recovery. It uses temporary software state.

For persistent demo state, choose a private directory on disk. Preview is the default:

```bash
edge-delegate control-demo \
  --directory "$HOME/.local/state/edge-delegate-lights" \
  --text "Set the inspection light to 40 percent."
```

The output shows a proposed plan, validation issues (empty if valid), and unchanged light
state. Initialization creates local databases, but preview never creates an operation
receipt or changes an existing light's state.

Explicitly execute the same command:

```bash
edge-delegate control-demo \
  --directory "$HOME/.local/state/edge-delegate-lights" \
  --text "Set the inspection light to 40 percent." \
  --request-id inspection-brightness-1 --execute
```

The inspection brightness becomes 40; workbench brightness is unchanged. Brightness and
power are independent: changing brightness does **not** turn the light on.

Repeat that exact request ID to retrieve its recorded result, not issue another action.
Use a new ID for new work. Reusing an ID with changed parameters or another device is a
conflict. A replayed receipt describes the original operation, not necessarily current state.

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

Installed applications can import these public APIs without importing the lab:

```python
from edge_delegate.application import ControlSession, DeviceRegistration, DeviceRegistry
from edge_delegate.simulator.lights import LightEmulator, light_policy
from edge_delegate.planner.control import light_catalog

# Parent directory must already exist and be private.
device = LightEmulator("/private/path/inspection.sqlite")
registry = DeviceRegistry([
    DeviceRegistration("inspection light", device, light_policy(), aliases=("inspection",)),
])

with ControlSession(
    registry, catalog=light_catalog(), journal_path="/private/path/gateway.sqlite"
) as control:
    request = control.request(
        request_id="brightness-1",
        target="inspection light",
        action="light.brightness.set",
        parameters={"percent": 40},
    )
    print(control.preview(request))
    print(control.execute(request))
```

`light.power.set` takes `{"on": true}`; `light.brightness.set` takes `{"percent": 40}`.
Both `.read` actions take no parameters. Booleans are not accepted as brightness numbers;
brightness must be an integer from 0 to 100. Unknown arguments are rejected.

Persist `request.to_dict()` if an application needs to retry or reconcile later. Parse it
using `ControlRequest.from_dict` from `edge_delegate.contracts.control`. Never resolve a new
name and assume it still denotes the original operation's device.

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
