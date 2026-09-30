# Edge Delegate

**Give your application a controlled way to act on devices.**

Edge Delegate is a local SDK and service for applications that need to request device actions,
get approval, and find out what actually happened. Your application asks for an operation;
Edge Delegate checks it, calls the installed device adapter, and records the result.

For example, an application requests **“set this output to 40%.”** The user can inspect the
target and value before approving. If the connection drops after execution, the application
can look up that same operation instead of sending a new request and risking a duplicate.

**Developer preview:** today the Rust services run on Linux/WSL. The original service controls
a simulated volume device; the new [v2 service](docs/reference/execution-service.md#v2-notes-service)
creates and retrieves real app-owned notes with approval and durable results. Neither changes
native audio or controls your phone. Real-device adapters and a
companion app are part of the [roadmap](docs/roadmap.md).

[Get started](docs/getting-started.md) · [How it works](docs/architecture.md) ·
[API reference](docs/reference/execution-service.md) · [Project status](docs/qualification-status.md)

## What you get

- **Preview before execution.** See the exact target, action and parameters.
- **Separate client access and approval.** An enrolled client cannot approve its own write.
- **Persistent results.** Inspect an operation after a disconnect or host restart.
- **Recovery without blind replay.** An uncertain result stays visible until there is evidence
  of what happened.

The host, not a model or UI, enforces these checks. Installed adapters define the available
actions; arbitrary shell commands and screen automation are not part of this interface.

## Try it

You need Linux or Ubuntu under Windows Subsystem for Linux (WSL), Rust/Cargo, and a C compiler.
From the repository root, build and start the software-device service:

```bash
cargo build --locked -p edge-host -p edge-cli -p edge-simulator --bins
cargo build --locked -p edge-client --example approved_request
mkdir -p "$HOME/.local/state"
cargo run --locked -p edge-host -- serve-software \
  --directory "$HOME/.local/state/edge-delegate-quickstart"
```

Leave that terminal running. In a second terminal at the same repository root:

```bash
cargo run --locked -p edge-client --example approved_request -- \
  "$HOME/.local/state/edge-delegate-quickstart"
```

The example shows a plan and waits. Type `approve` to change the **simulated** output to 40%,
or press Enter to leave it unchanged. It uses the public Rust client, not host internals.

This is an owner-run learning example: it holds separate owner and client credentials in
one process. Ordinary applications should receive only their client credential. Each run
creates a new request; after an error, inspect the printed request ID before running it again.

[Full walkthrough and expected output →](docs/getting-started.md)

## Where models fit

Edge Delegate is not itself a language model. An interpreter can translate language into a
proposed action; execution still requires the same checks. The Rust service currently accepts
structured requests. Its quickstart does not load or train a model.

The repository also contains an existing Python device runtime and a separate Python model
lab. The lab trains and evaluates planners for temperature/display tasks. Those models have
not learned the newer light, computer or phone controls.

| You want to… | Start with |
| --- | --- |
| Connect an application to the Rust service | [Quickstart](docs/getting-started.md), then [Rust client reference](docs/reference/execution-service.md) |
| Use existing Python controls or extend a Python device adapter | [Software-light tutorial](docs/try-it.md), then [Python SDK](docs/reference/control-sdk.md) |
| Experiment with local-model interpretation | [Model tutorial](docs/model-tutorial.md) |
| Contribute to the runtime | [Architecture](docs/architecture.md) and [development runbook](docs/development-runbook.md) |

## Scope

This is developer software, not a production controller for arbitrary devices. Native
Windows/macOS/mobile controls, remote pairing, the companion UI, voice and cloud-model
fallback are not implemented. Passing builds on an OS does not mean its devices are supported.

The SDK is useful when several callers need consistent permissions, approval and recovery.
For a few fixed buttons calling one driver, direct application code may be simpler.

See [current capabilities and evidence](docs/qualification-status.md) for the exact boundary.
Project-owned code is [MIT licensed](LICENSE); models and dependencies retain their licenses.
