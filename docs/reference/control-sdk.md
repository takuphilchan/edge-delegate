# Python control SDK reference

[Documentation home](../README.md) | [Tutorial](../try-it.md) | [Architecture](../system-architecture.md)

The software development kit (SDK) is a synchronous, experimental Python API. It does not load
a model, run a service or control physical lights by itself.
For the separate Rust host/client interface, use the [execution-service reference](execution-service.md).

Use this page when you want to replace the demonstration's terminal commands with calls from
your own program. Start with the [complete example below](#small-complete-example), then look
up methods as needed. It requires the core installation from the [tutorial](../try-it.md#1-install),
not the inference or training dependencies.

These imports work from the installed package without the lab:

~~~python
from edge_delegate.application import ControlSession, DeviceRegistration, DeviceRegistry
from edge_delegate.contracts.control import ControlRequest
from edge_delegate.planner.control import light_catalog
from edge_delegate.simulator.lights import LightEmulator, light_policy
~~~

## Small complete example

This example creates isolated software state, then previews and executes one typed request.
Temporary state is for this disposable test only. A persistent application must retain its
journal, device state and original requests.

Run the complete block as a Python script in your activated environment. A successful run
finishes with no output and no assertion failure. It intentionally uses no language parser:
your application already supplies the target, action and value explicitly.

<!-- sdk-example -->
~~~python
from pathlib import Path
from tempfile import TemporaryDirectory

from edge_delegate.application import ControlSession, DeviceRegistration, DeviceRegistry
from edge_delegate.planner.control import light_catalog
from edge_delegate.simulator.lights import LightEmulator, light_policy

with TemporaryDirectory(prefix="edge-sdk-example-") as directory:
    root = Path(directory)
    registry = DeviceRegistry([
        DeviceRegistration(
            "inspection light",
            LightEmulator(root / "inspection.sqlite"),
            light_policy(),
            aliases=("inspection",),
        ),
    ])
    with ControlSession(
        registry, catalog=light_catalog(), journal_path=root / "gateway.sqlite"
    ) as control:
        request = control.request(
            request_id="brightness-1",
            target="inspection light",
            action="light.brightness.set",
            parameters={"percent": 40},
        )
        preview = control.preview(request)
        assert not preview["gateway"]["validation"]["issues"]
        result = control.execute(request)
        assert result["gateway"]["result"]["status"] == "executed"
~~~

## Construction and lifecycle

`DeviceRegistration(name, device, policy, aliases=(), endpoint_id="main")` binds a display
name and optional aliases to one deadline-aware device. Policy must be local-only.
`DeviceRegistry(registrations)` requires unique canonical names and device identities.
Shared aliases are allowed, but resolving an ambiguous alias raises `TargetResolutionError`.
Names use case-insensitive exact matching, not fuzzy guesses.

`ControlSession(registry, *, catalog, journal_path, command_parser=None)` requires an explicitly
installed `ControlCatalog`. Use a context manager or call `start()` then `close()`.
Preview/execution/reconciliation require a ready session. Closing does not undo completed
actions or delete the journal. One session admits one request at a time; it rejects concurrent
use rather than queueing. All registered devices share the authoritative journal.

| Method | Input and behavior |
| --- | --- |
| `start()` | Initialize sessions; returns self; no device actions |
| `close()` | Close session ownership; idempotent after successful close |
| `status()` | Lifecycle state, busy flag, targets; supervised and physical qualification are false |
| `request(*, request_id, target, action, parameters=None)` | Resolve a name once, validate arguments, return typed ControlRequest |
| `preview(request)` | Propose and validate; no invocation, request reservation or operation receipt |
| `execute(request)` | Validate and dispatch through the runtime; return a control result envelope |
| `reconcile(*, target, request_id)` | Inspect original device receipts; use the original typed target |
| `command(text, *, request_id, execute=False)` | Optional installed text parser; defaults to preview; no parser means an error |

There is no `cancel()` method, remote client, supervised worker or whole-request deadline
in this API yet. A bounded adapter invocation is not a deadline for the entire request.

## Actions and parameter types

`ControlAction` and `ControlCatalog` are public in
`edge_delegate.planner.control_catalog`. Definitions map action identifiers to capabilities,
typed constraints and versioned semantics. Catalogs are trusted installed code, not profile
Python expressions. They do not grant permissions.

The current request protocol permits boolean/integer parameters only. Unknown arguments are
rejected. The reference `light_catalog()` contains:

| Action | Parameters | Returned value |
| --- | --- | --- |
| light.power.set | on: boolean | resulting boolean power (false when switching off) |
| light.power.read | none | current boolean power |
| light.brightness.set | percent: integer, inclusive 0–100 | written integer brightness |
| light.brightness.read | none | current integer brightness |

Brightness does not change power. Boolean values do not count as brightness integers.
Do not silently add floats, strings, units, arbitrary modes or multi-device actions to this protocol.

## Bindings, retries and errors

A ControlRequest contains the request ID, original device/endpoint/registration fingerprint,
action, parameters and catalog fingerprint. Persist `request.to_dict()`; load trusted stored
data with `ControlRequest.from_dict(data)`. Changing names, capabilities, policy or catalog
semantics invalidates the old binding. Request-scoped approval grants are excluded from the
registration fingerprint to avoid a plan-hash cycle; the runtime still validates their exact
plan binding and expiry.

Reuse an ID only for the identical request. IDs share a namespace across registered devices.
A confirmed duplicate can return a recorded result; changed work conflicts. A receipt is not
a fresh observation of state. See [recovery](../how-to/reconcile.md) before handling uncertainty.

Malformed inputs/catalog drift raise ValueError; target resolution/binding problems can raise
TargetResolutionError (a ValueError). Lifecycle misuse/concurrent admission raises RuntimeError.
Storage/adapter setup exceptions can also propagate. Command parsing converts recognized
ambiguity/unsupported input into non-executing responses; it does not turn every exception
into a response. Runtime validation/execution failures are represented in result envelopes.
Applications must handle both exceptions and [result statuses](results.md), not assume every
returned dictionary means success.

## Related public application API

`GatewaySession(planner, device, policy, *, journal_path, diagnostics=None)` owns a single
planner/device session. It exposes start/close, preview/execute, status and reconcile;
`handle` aliases execute. The lab import remains a compatibility alias. The caller constructs
and prepares the planner; this does not promise process isolation or background model loading.
Use ControlSession for explicit targeted controls rather than inventing target routing in
model text.
