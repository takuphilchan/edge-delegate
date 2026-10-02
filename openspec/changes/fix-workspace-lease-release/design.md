# Design

## Context

See [proposal.md](proposal.md) for motivation and scope. The existing ownership
boundary is described in [the service reference](../../../docs/reference/execution-service.md#worker-and-recovery-boundary)
and [repository layout](../../../docs/repository-layout.md).

`adapters/workspace/src/store.rs` acquires an `fs2` exclusive lock on a validated
private `workspace.lock` file. `Workspace` stores a bare `File` after its SQLite
connection and has no explicit lease-release guard. Initialization after lock
acquisition can also exit early on storage or deployment validation errors.

The normal parallel `cargo test --locked -p edge-workspace --test notes` failed
again during this proposal pass: eight passed and two failed at `notes.rs:137`
and `notes.rs:333`. The preceding verification also reproduced those failures
and saw all ten tests pass serially. The test executable concurrently launches
crash-helper children. These results establish a concurrency-sensitive release
problem, not the exact timing of a particular child process.

Linux `flock` ownership attaches to the open file description: a duplicated or
inherited descriptor can retain the lock after one handle closes, whereas an
explicit unlock releases that lock. This makes close-only cleanup unsuitable for
the desired deterministic teardown contract. See the Linux man-pages project's
[`flock(2)` documentation](https://man7.org/linux/man-pages/man2/flock.2.html).
The deterministic regression must establish this failure mechanism in the actual
adapter; do not report a traced fork interleaving or a completed fix without it.

## Goals / Non-Goals

**Goals:** a private owner-scoped lock guard that covers successful and failed
construction, preserves exclusivity until database cleanup, and permits immediate
reopening after normal cleanup. Use actual kernel locks in regression tests.

**Non-Goals:** no process-global locking framework, asynchronous shutdown API,
schema change, alternate transport, journal cleanup command, or test scheduling
workaround. Do not change the separate `Arc<File>` lifetime used by admission
journals. Arbitrarily forking and continuing to use inherited Rust/SQLite objects
is not a supported workspace API.

## Decisions

### 1. Use a private, non-cloneable acquired-lease guard

Keep the implementation local to the workspace store. Construct the guard only
after the existing private-file validation and successful exclusive acquisition.
It owns the acquired `File` and explicitly calls `FileExt::unlock` during cleanup
before closing that handle. Preserve the original error if later initialization
fails. A failed acquisition must never construct a guard that would release
another owner's lease.

Record the acquiring process identity and do not explicitly unlock from an
inherited guard in a different process. This does not make SQLite objects
fork-safe; it prevents accidental cleanup in a child from releasing the live
parent's lock. Do not add public handle duplication or lease-transfer APIs.

Alternative rejected: relying solely on `File` close leaves aliases sharing the
open file description able to extend the lock lifetime. Sleeping, retrying, or
serializing the test suite would conceal the lifecycle defect.

### 2. Release after database teardown on every path

Retain declaration order with the database connection before the lease guard,
and document why it is significant. On failed construction, acquire the guard
before creating the database connection so reverse local destruction closes
database resources before dropping the guard. Review early returns after
acquisition explicitly, including missing storage, invalid sidecars, schema
rejection, initialization failure, and wrong deployment identity.

Do not unlock at the start of `Workspace::drop`: that would release ownership
while its database field is still live. A field-level guard gives the intended
cleanup order without making the database optional or adding a fallible public
close method. Keep destructors non-panicking; if an OS unlock fails, close the
handle and retain fail-closed acquisition behavior, not a false recovery result.

### 3. Add deterministic and process-level regressions

Use private unit tests in the store module to duplicate the actual lease file
handle with safe `File::try_clone`. Hold that incidental alias across owner
teardown. The test must fail before the fix because reopening cannot acquire the
lease, then pass after explicit release while the alias remains alive. The alias
does not operate on the database and is not itself another authorized owner.

Also test scope exit after successful lease acquisition followed by a controlled
initialization error. Any fault seam belongs to tests only, not an environment
switch or public API. Preserve the original error and verify reacquisition.

At the public `Workspace` boundary, keep and strengthen tests for a live competing
owner, rejected contender cleanup, wrong authority/endpoint, incompatible storage,
normal reopen, original receipt reconciliation, and abrupt process exit. Add a
child helper following the existing `--exact` subprocess test pattern to check
cross-process ownership; only pass that fixture's temporary directory. Bound
helper readiness/exit waits and reap owned children on failure. Never terminate
unrelated processes.

Do not introduce unsafe code, new runtime dependencies, artificial success mocks,
blind sleeps, or retry-until-green assertions. Run the ordinary parallel notes
suite repeatedly as additional stress evidence, not as the deterministic oracle.

### 4. Keep evidence and dependent completion separate

The fix requires the full default-parallel Rust workspace suite plus the real
notes worker/service scripts, not only the unit regression. Record exact command
results in this change and update measured status only after checks finish.
Preserve the earlier failure record in the CLI-help change; add a dated resolution
and check its final integration task only when its original checks pass normally.

No automatic commit, push, archive, deployment, or CI submission follows from
passing local checks. Windows/macOS build evidence and native qualification must
be reported as unrun where unavailable.

## Risks / Trade-offs

- **Unlocking too soon** -> keep the lease field after the database field and
  cover initialization failures as well as normal teardown.
- **A failed contender releases a live owner's lock** -> guard creation follows
  successful acquisition only; exercise a third contender after rejection.
- **Inherited child cleanup releases parent authority** -> bind explicit unlock
  to the acquiring process; do not claim general post-fork object safety.
- **The alias regression does not explain every observed failure** -> require
  both its red/green result and normal parallel integration success. If the same
  failure remains, keep the change incomplete and investigate the specific
  surviving lock owner; do not paper over it with retries.
- **Other journals use close-only leases too** -> do not silently refactor their
  distinct ownership lifetimes here. Record any independently observed defect
  for a separate change.
- **Destructor errors cannot become a new public result** -> do not panic or
  fabricate success; close the owned handle and keep competing acquisition
  checks intact. No guarantee is made for broken filesystems or kernel failures.

## Migration Plan

No data migration is required. A stopped worker can use the fixed binary with the
existing schema, deployment identity, notes, and receipts. Rollback changes only
the executable and would reintroduce the release defect; it must not restore an
older database, clear an uncertain outcome, or replace a live owner. Actual
deployment remains separately authorized.
