# Documentation

Start by making one request, then learn how to integrate and recover it. You do not need a
model or physical device for the Rust service.

## Start here

1. **[Run your first approved operation](getting-started.md).** Start a local host, inspect a
   proposed volume change, and approve or decline it.
2. **[Understand the system](architecture.md).** See what belongs in your application, the
   execution host, the device adapter and the optional model lab.
3. **[Integrate the client](reference/execution-service.md).** Look up methods, permissions,
   response fields and errors.

The quickstart changes software state only. For deployment decisions, read
[current support and evidence](qualification-status.md).

## Work with the Rust service

| Task | Guide |
| --- | --- |
| Make calls with the CLI instead of the SDK example | [Manual enrollment, approval and execution](tutorials/rust-execution-service.md) |
| Understand permission versus approval | [Execution concepts](concepts/execution.md) |
| Inspect a timeout, retry or interrupted request | [Results and recovery](reference/execution-service.md#results-and-recovery) |
| Handle credentials, revocation and retained state | [Security and storage](reference/execution-service.md#security-and-storage) |
| Find the implementation | [Repository layout](repository-layout.md) |

The service currently supports one installed software-volume action. General device discovery,
native adapters, a companion UI and Python/TypeScript socket clients are planned, not available
through the interface above.

## Use the existing Python tools

These are separate from the Rust service; they do not connect to its socket or share its journal.

- **Device controls:** [try two software lights](try-it.md), use the [Python SDK](reference/control-sdk.md),
  or [add an adapter](extensions.md).
- **Model work:** [load a model](model-tutorial.md), understand the [training lifecycle](model-lifecycle.md),
  and use [review/export tooling](implementation-batch-1.md).
- **Lookup:** [commands](reference/cli.md), [results](reference/results.md),
  [reconciliation](how-to/reconcile.md), and [Python architecture](system-architecture.md).

The temperature/display model and exact light commands are different examples. A working
driver does not mean a model has learned to use it.

## Contribute

Use the [development runbook](development-runbook.md) for checks and the
[documentation standard](contributing-docs.md) for writing and example verification.
The [glossary](glossary.md) defines project terms.

The [roadmap](roadmap.md) is the active plan. The [release contract](release-contract.md)
defines intended support and acceptance gates. [Historical records](history/) explain earlier
experiments; they are not current onboarding instructions.

Advanced Rust layer examples remain available for contributors:
[contracts](tutorials/rust-foundation.md), [preview-only IPC](tutorials/rust-local-service.md),
[owner console](tutorials/rust-supervision.md), [authority](tutorials/rust-authority.md)
and [receipt recovery](tutorials/rust-recovery.md).
