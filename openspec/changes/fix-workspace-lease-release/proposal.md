# Proposal

## Why

Normal parallel notes tests repeatedly fail to reopen a workspace after its prior
owner has been dropped, reporting `workspace_already_owned`. This blocks the
existing CLI-help change's workspace verification and undermines dependable
adapter restart; passing the tests serially does not repair the lifecycle.

## What Changes

- Make the Linux notes adapter's acquired lease release explicit and scoped to
  its actual owner, including cleanup after initialization fails.
- Keep the lease held until the workspace's database resources have closed;
  continue rejecting genuinely competing owners without waiting or retrying.
- Add a deterministic lock-lifetime regression using real OS file descriptors,
  alongside live-owner, failed-initialization, restart, and process-death checks.
- Verify the unchanged normal parallel suites and the real v2 service/worker
  diagnostics. Do not hide the failure with serial-only tests or retry loops.
- Record evidence and the remaining limits in the existing qualification/service
  documentation. Recheck the existing CLI-help change only after the blocker is
  actually resolved.

Acceptance: successful teardown and failed initialization no longer leave a
spurious lock held by an incidental alias of the acquired handle; a live owner
still excludes another owner; reopening retains original notes and receipts and
never repeats a write. The existing failing tests and new deterministic
regressions must pass under the normal parallel test configuration.

Scope is the workspace notes lease and its tests/documentation. Excluded: event
capacity reservations, onboarding and CLI convenience changes, Windows transport,
Python client work, shared-journal refactors, schema migrations, public lifecycle
APIs, automatic retries, deployment, commits, pushes, and releases. The other
recommended improvements remain separate work, not completion claims here.

## Capabilities

### New Capabilities

- `workspace-ownership`: Exclusive ownership and deterministic release of the
  Linux notes store through successful use, initialization failure, and recovery.

### Modified Capabilities

None. No maintained OpenSpec capability currently covers this behavior. This
change does not amend the separate `cli-command-help` capability or its scope.

## Impact

- `adapters/workspace/src/store.rs`: private lease lifetime/cleanup, with no
  changes to public `Workspace` operations or note/receipt semantics.
- `adapters/workspace/tests/notes.rs` and private unit tests: deterministic
  regression coverage and preservation of process/ownership checks.
- `docs/reference/execution-service.md` and `docs/qualification-status.md`:
  accurate recovery guidance and measured evidence after implementation.
- Existing `scripts/test-workspace.sh`, `scripts/test-workspace-service.sh`, and
  Rust/Python checks provide integration validation; no CI serialization change.
- No new runtime dependencies, credential changes, protocol changes, storage
  format changes, or native-device qualification.
