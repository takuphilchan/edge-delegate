# Try the Rust foundation without controlling a device

[Repository layout](../repository-layout.md) | [Roadmap](../roadmap.md)

This tutorial exercises strict contracts and a deterministic preview compiler. It does not
change volume, load a model, issue an approval, start a service or contact another device.
The context is an editable saved fixture, not live device state or trusted authorization.

## Prerequisites

Install Rust through the [official Rust installation guide](https://rust-lang.org/tools/install/)
if cargo is missing. The repository selects Rust 1.90.0 and its formatting/lint components.
On Windows, the native toolchain also needs the documented C++ build tools. WSL is sufficient
to try this foundation, but does not qualify the Windows/macOS/mobile application.

## Run the checks

From the repository root:

```bash
cargo test --workspace --locked
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo fmt --all -- --check
```

## Preview one structured request

```bash
cargo run --locked -p edge-cli -- preview --request conformance/contracts/preview-v2/request.json --context conformance/contracts/preview-v2/context.json
```

The fixture requests 40 percent volume on a registered example endpoint. Expect:

- execution_attempted: false
- decision.status: proposed
- decision.requires_approval: true
- One step, bound to the example target and catalog, with a 1000 ms limit.
- A deterministic request, policy and plan fingerprint.

A proposed plan is not executed or approved. No authenticated execution host exists yet.
The future host must authenticate the principal, refresh state, persist intent and enforce
deadlines independently. Even a read preview does not grant authority to inspect a live device.

The separate [software recovery tutorial](rust-recovery.md) exercises a trusted program's
approval, durable execution and reconciliation. edgectl preview never calls that path.

Changing the percent outside 0..100 yields invalid_parameters. Changing the target generation
yields repreview_required. Changing catalog definitions without their fingerprint fails
context validation. These cases are already covered by the automated tests.

## Contract and framing boundaries

The request schema is [control request v2](../../schemas/v2/control-request.v2.schema.json).
Runtime additionally rejects duplicate keys at any depth, invalid UTF-8, text exceeding
4096 UTF-8 bytes, frames over 65536 bytes and mismatched authorities. Unknown fields fail;
unsupported versions never fall back to v1. Immediate budgets are explicitly 1..5000 ms.

Parameters are tagged booleans, JS-safe integers, bounded strings, enums, resources or exact
decimal strings. Decimal wire values are canonical (for example -3.5, not -3.50). This is
not a change to the legacy decimal.v1 user-language policy. The initial generic compiler
supports boolean/integer/string/enum/resource rules; decimal capability rules are not yet
implemented and therefore cannot be accidentally executed.

edge-canonical-json.v1 sorts ASCII keys recursively, emits compact UTF-8 JSON and prohibits
floating-point values/unsafe integers in hashed data. It is not a general RFC 8785
implementation. Rust golden tests and Python independently verify the shared hashes.

The protocol crate encodes a four-byte big-endian length followed by one strict JSON frame.
It bounds allocations and rejects truncated/duplicate-key payloads. The codec alone does not
authenticate callers. The separate [Linux preview service](rust-local-service.md) now adds
owner authentication, version negotiation and connection deadlines; it still cannot execute.

## Existing Python functionality

Keep using the [software-light tutorial](../try-it.md) and [model tutorial](../model-tutorial.md)
for the existing execution paths. Their commands and artifact meanings are unchanged.
Do not point a future Rust executor at a Python journal without the migration described in
the roadmap.
