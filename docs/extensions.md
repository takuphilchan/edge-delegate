# Add tasks and devices without changing the runtime

Use this after you have run the [tutorial](try-it.md) and understand the
[public Python interface](reference/control-sdk.md). This is a developer integration guide,
not a hardware auto-discovery wizard.

There are two separate questions: can the system perform an operation, and can a model
understand requests for it? A device adapter answers the first. A compatible planner and
its task vocabulary answer the second. Adding a driver alone does not train a model.
Start with explicit structured requests or a deterministic test planner to verify your
integration before introducing language-model errors.

This is an experimental extension contract. An installed plugin is trusted Python code,
not a sandbox. Install only packages you trust. JSON device profiles contain data, never
module paths, import statements, or executable builders.

## Who owns what

| Extension | Owns | Must not claim |
| --- | --- | --- |
| Model plugin | Task vocabulary, training/export recipe, artifact compatibility, planner | That unrelated weights understand its catalog |
| Task catalog | Versioned IDs, descriptions, parameter checks, deterministic plan builders | Permission to execute |
| Device adapter | Stable identity, capabilities, fresh state, bounded dispatch, receipts | Exactly-once physical execution or rollback |
| Runtime | Validation, request-plan binding, journal, execution | That a permitted action matches user intent |

A model plugin constructs `BoundedPlanner(decide, catalog=my_catalog())` using `TaskCatalog`
and `TaskDefinition` from `edge_delegate.planner.tasks`. Builders are installed code returning
typed `PlanStep` objects. Each builder must reject missing/unknown/invalid parameters; compiled
plans still require runtime validation. The trained reference plugins remain tied to
`local-display.v1`. There is deliberately no CLI switch pretending their existing weights
understand arbitrary tasks. New catalogs need compatible artifacts and their own quality tests.

## Register an adapter

In an independent package's `pyproject.toml`:

```toml
[project.entry-points."edge_delegate.device_adapters.v1"]
my-device = "my_package:create_device"
```

`create_device(*, settings: dict)` returns an object implementing **both** `DeviceGateway`
and `DeadlineGateway` from `edge_delegate.runtime.ports`. It reports
`api_version = "edge-delegate-gateway.v2"` and a stable, nonempty device identity. An identifier
must not silently move to a replacement device with different receipts. The factory validates
its settings; the registry rejects duplicate names and incompatible objects. Only the explicitly
selected installed entry point is loaded. Profiles cannot select Python import paths.

```bash
edge-delegate-lab run --plugin YOUR_MODEL --adapter YOUR_ARTIFACT \
  --device-adapter my-device --device-settings device.json \
  --policy policy.json --journal /private/path/gateway.sqlite --text "Your request"
```

`run` and `reconcile` select installed adapters. `--socket` is shorthand for the reference Unix
adapter's socket setting. The performance benchmark remains the local-display Unix workload;
it does not qualify a custom adapter.

The optional `CancellationGateway.cancel_operation(operation_id, deadline=...)` must serialize
with dispatch and durably prevent future execution of an unexecuted operation. Returning `failed`
because no receipt was found is **not** sufficient. Completed actions keep their existing receipt.
See [gateway recovery](gateway-preview.md#when-the-device-has-no-receipt).

## Try the independent counter package

`examples/plugins/counter` installs separately, with no core edits. It contains a second catalog
(`counter-demo.v1`) and SQLite software counter adapter. Its planner recognizes exact commands;
it is not a trained model and does not understand unrestricted language.

```bash
python -m pip install --no-deps ./examples/plugins/counter
```

Create a private working directory. In `device.json`, set an absolute path to a new counter
database inside it:

```json
{"database": "/home/your-user/private-counter/device.sqlite"}
```

From the repository root:

```bash
edge-delegate-lab run --plugin counter-demo --device-adapter counter-demo \
  --device-settings device.json --policy examples/plugins/counter/policy.json \
  --journal /home/your-user/private-counter/gateway.sqlite \
  --text "increment counter" --request-id counter-1
```

The returned value is `1`. Repeating it returns the recorded `1` without incrementing.
Use `--text "read counter" --request-id counter-read-1` for a new observation. Other phrases
are denied. State, operation receipts, and cancellation fences persist across restart.
The same package includes `display-demo`, an exact-phrase fixture for Unix-emulator smoke tests.
Neither fixture is a substitute for qualifying the trained candidates.

## Acceptance before claiming support

Test normal execution, expired deadlines, concurrent duplicates, restart, stale state, unknown
outcomes, malformed results, and permission rejection. For cancellation, test late dispatch
after fencing and restart after cancellation. Use one authoritative host journal and one device
receipt store. Protect both; missing databases are not successful recovery.

`tests/unit/test_device_extensions.py` exercises the counter; `tests/integration/test_durable_gateway.py`
exercises the separate-process Unix transport. `scripts/check_wheel.py` installs both wheels into
a fresh environment outside the checkout and tests public commands without PyTorch. CI runs it
alongside source tests. These are software integration checks, not physical-device certification.
