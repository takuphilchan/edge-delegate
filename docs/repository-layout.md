# Repository layout and migration rules

[Documentation home](README.md) | [Roadmap](roadmap.md) | [Rust foundation tutorial](tutorials/rust-foundation.md)

## Where to work today

```text
src/edge_delegate/          Existing Python contracts, runtime, adapters and plugins
src/edge_delegate_lab/      Existing Python training/evaluation and lab commands
crates/edge-contracts/      Rust strict data-only v2 request types and canonical hashes
crates/edge-core/           Compiler and experimental single-operation coordinator/ports
crates/edge-storage/        SQLite journal, bound approvals and restart transitions
adapters/simulator/        Persistent software device, injected faults and recovery example
crates/edge-protocol/       Strict frames, separate preview/execution envelopes, Linux checks
crates/edge-host/           Linux preview and authenticated software execution services
crates/edge-client/         Public Rust preview and software execution clients
crates/edge-cli/            edgectl preview commands plus explicit authenticated service calls
conformance/contracts/     Shared request/context/hash fixtures
schemas/v2/                Experimental new schema; existing schemas stay in place
tests/architecture/        Dependency, compatibility and documentation guards
docs/decisions/            Target design, not implementation evidence
docs/tutorials/            Tested paths through implemented functionality
```

Cargo.toml declares the Rust workspace; Cargo.lock and rust-toolchain.toml pin the build.
The root pyproject.toml continues to install the existing Python package. No Python files
have been relocated and no old console commands have been replaced.

## Add these only with tested implementation

```text
crates/edge-planner/        CPU parser/classifier inference
crates/edge-worker/         Desktop planner worker executable
crates/edge-relay/          Opaque self-hosted internet relay
adapters/                  Simulator, workspace, Windows, Linux, macOS, mobile bridges
apps/assistant/            Shared React UI and restricted Tauri shell
sdks/python/               edge_delegate_client, independent of the training lab
sdks/typescript/           Typed public client and application binding
lab/                       Independently packaged lab after compatibility migration
packs/                     Workspace, companion and device-reference metadata
deployment/                Desktop, mobile and relay packaging/configuration
conformance/               Adapter, recovery and security fixtures as they are implemented
examples/                  Public SDK, adapter and workflow examples
```

Do not add placeholder packages that merely return success. Do not claim an API exists
because its future directory appears here. Frontend scaffolding requires a startup test;
native permissions and pairing are not mocked away in release evidence.

The storage package backs up/upgrades Rust schema 1 to 2; it still needs legacy import, stale-restore
fencing, quotas and cross-journal device ownership. Its lock owns one directory, not every
possible journal on a machine. See the [recovery boundary](tutorials/rust-recovery.md).

## Dependency rules

Contracts are data-only. Core depends on contracts and ports, never adapters. Storage and
adapters implement ports. Host assembles the components. SDKs depend on contracts/protocol,
not private core execution. UI calls public clients. Lab is not a runtime dependency.
No model-family branches in core or shared commands. No generic utilities package to bypass
these boundaries. Current Cargo edges are checked by the Python architecture suite.

Shared catalog/plan/preview wire types now live in edge-contracts; edge-core re-exports the
previous names for Rust source compatibility. The client does not import the executor.
The host assembles compiler/storage and communicates with an installed adapter child through
edge-protocol. It does not depend on the concrete simulator crate. The simulator's test-only
host dependency exercises that integration. The preview socket constructs no execution session
and still cannot dispatch. See [preview](tutorials/rust-local-service.md) and
[supervision](tutorials/rust-supervision.md). The in-process
[scoped authority](tutorials/rust-authority.md) owns admission, grants and cancellation.
Its scoped handles are host embedding types. The separate execution-service client talks
through edge-protocol and has no runtime/storage dependency. Accepted requests, operation
records and service enrollment persist; previews, approvals and live scheduling do not
resume. See [execution IPC](tutorials/rust-execution-service.md).

The initial packages deliberately use the standard library plus serialization/hashing.
Future host networking is added to host/protocol rather than pulled into the pure compiler.

## Migration discipline

1. Add parallel versioned behavior with shared fixtures.
2. Compare legacy/new results without double-dispatching effects.
3. Move ownership only after durable migration, backup and recovery tests.
4. Split the lab with an independently installable package and compatibility imports.
5. Relocate files separately from behavior changes.

Never share live journal ownership between runtimes, reinterpret an old artifact as v2,
discard review histories, or change existing example paths merely for cosmetic consistency.
