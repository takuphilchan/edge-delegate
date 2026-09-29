# Edge Delegate

**Local execution infrastructure for applications that control devices.**

Edge Delegate sits between a request and the code that changes a device. It turns supported
requests into explicit plans, checks permissions, requires approval where configured, and
keeps a durable record of execution. If a connection breaks after an action may have happened,
it preserves that uncertainty so an application can investigate instead of blindly repeating it.

Use it to build a control interface with a shared permission and recovery boundary. A model
can propose an action, but it cannot grant itself permission to execute. **No model is required.**

**Status: experimental developer software.** The Rust service currently controls one software
volume endpoint on Linux/WSL. It does not change your computer's audio. Native computer/phone
controls, a companion application and remote pairing are planned, not available products.
No physical integration or production deployment is qualified.

[Get started](docs/tutorials/rust-execution-service.md) ·
[Documentation](docs/README.md) ·
[Current status](docs/qualification-status.md) ·
[Roadmap](docs/roadmap.md)

## What it does

For a request to set an output to 40 percent, the Rust service provides this sequence:

```text
Client previews a request
  → owner approves the exact target and value
  → client submits the approved request
  → host records and executes the operation
  → client inspects the result or reconciles uncertainty
```

Preview does not execute. Enrollment gives a client a scope, not permission to approve itself.
The execution host checks the approval and current state before dispatch. Recorded results
survive a restart; unfinished work does not automatically resume.

This is execution infrastructure, not a general-purpose computer-use agent. It does not generate
shell commands, click arbitrary screens, or discover unrestricted actions. Installed code
defines what the system can do.

## Try the execution service

You need Linux or Ubuntu under Windows Subsystem for Linux (WSL), Rust with Cargo, a C compiler
and Python 3 for the test driver. Run from a checkout of this repository. The repository pins
Rust 1.90.0; a first build needs access to download the toolchain and dependencies.

```bash
bash scripts/test-rust-execution.sh
```

This starts a real host and CLI client against the software adapter. It checks separate
client/owner credentials, rejected self-approval, one approved write, retry, restart and
revocation. It stops the host it started and prints the path to a retained report.

Success ends with `PASS: exactly one recorded software write.` No model, GPU, physical device
or external service is used at runtime. The evidence directory contains private credentials;
do not upload it wholesale. The test program supplies approval for its own fixture, not
independent human consent.

For prerequisites, manual operation and troubleshooting, follow the
[execution-service tutorial](docs/tutorials/rust-execution-service.md).

## Choose an integration

The repository has three distinct paths. They are not interchangeable implementations of
every capability.

| Path | Use it for | Start here |
| --- | --- | --- |
| Rust execution service | Authenticated local clients, separate owner approval, durable software execution and recovery | [Service tutorial](docs/tutorials/rust-execution-service.md) and [API reference](docs/reference/execution-service.md) |
| Python device runtime | Structured controls and exact commands for the existing software lights and device examples | [Software-light tutorial](docs/try-it.md) and [Python SDK](docs/reference/control-sdk.md) |
| Python model lab | Training and evaluating optional planners for the temperature/display catalog | [Model tutorial](docs/model-tutorial.md) |

SDK means software development kit: the interfaces an application calls. A device adapter is
installed code that implements operations. A model adapter is learned weights; training one
does not create device drivers or expand permissions.

The existing temperature model has not learned light, phone or application controls. Its known
quality failures are recorded in [qualification status](docs/qualification-status.md).
External-model delegation, voice processing and microcontroller inference are not implemented.

## Understand the design

- [Execution concepts](docs/concepts/execution.md): requests, permissions, approval and recovery.
- [Repository layout](docs/repository-layout.md): Rust runtime boundaries and the separate Python lab.
- [Python architecture](docs/system-architecture.md): the existing device-runtime request path.
- [Release contract](docs/release-contract.md): intended support boundaries and qualification gates.

If a few fixed buttons calling a known driver solve your problem, direct application code may
be simpler. Edge Delegate is useful when multiple callers need consistent checks, execution
records and recovery behavior.

## Contribute

From the repository root:

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked
```

For Python work, activate your development environment, then run:

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
python -m ruff check .
```

The normal Python suite excludes hardware-marked tests. Passing software tests is not evidence
of model accuracy or physical reliability. See the [development runbook](docs/development-runbook.md)
and [documentation standard](docs/contributing-docs.md).

Project-owned code is [MIT licensed](LICENSE). Models and dependencies retain their own licenses.
