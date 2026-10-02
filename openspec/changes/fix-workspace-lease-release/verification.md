# Verification - 2026-10-02

Status: **integration verification blocked** by a separately observed v2 service
lease failure. The notes-store regressions pass. This record does not establish
completion, archive readiness, or release qualification.

## Deterministic red test

In Ubuntu/WSL, Cargo 1.90.0, `cargo test --locked -p edge-workspace --lib`
ran the newly added `owner_teardown_releases_lease_with_live_handle_alias` against
the unchanged bare-file cleanup. It failed (zero passed, one failed) with
`workspace_already_owned` on immediate reopen while a duplicate descriptor
remained open. No retry, delay, serial-test setting, unsafe code, or native-device
action was used. This demonstrates the lock-lifetime mechanism, not a traced
interleaving of the earlier parallel crash-helper tests.

## Implemented behavior and focused checks

The private `WorkspaceLease` guard is created only after successful acquisition.
It explicitly unlocks only in the acquiring process, does not panic on cleanup,
and follows the database field in destruction order. On construction failure,
the database is destroyed before the earlier-created guard. Every early return
after acquisition was reviewed: missing storage, sidecar validation, database
opening/PRAGMAs, schema/init transactions, sync failures, and deployment mismatch.
No public API, schema, credential, runtime dependency, or authorization change.

Three private unit tests passed: actual duplicate handle across teardown,
injected initialization error with a live duplicate, and acquiring-process
identity fencing. The identity-fence test uses a real descriptor alias and a
test-only mismatched PID; it is not a live-fork/SQLite qualification claim.

The final 12-test notes suite passed **ten consecutive default-parallel runs**
with no failures. A first compile attempt found that `Receipt` has no `PartialEq`;
the test now compares canonical receipt digests without changing that public type.
The stress sequence started after that compilation repair. No acquisition retry,
serial-test setting, lock-file deletion, or timing workaround was added.

## Integration results so far

Environment: Ubuntu/WSL, Cargo 1.90.0; existing Python 3.14.4 environment at
`/home/phil/.venvs/edge-model`. All checks use fixture state, not installed-user
workspaces. No native device or model was exercised.

| Command | Observed result |
| --- | --- |
| `cargo test --locked -p edge-workspace --lib` | Three passed after the fix |
| `cargo test --locked -p edge-workspace --test notes` | Twelve passed in each of ten consecutive parallel runs |
| `cargo fmt --all -- --check` | Passed |
| `cargo clippy --workspace --all-targets --locked -- -D warnings` | Passed |
| `cargo test --workspace --locked` | Failed in the v2 service restart test; CLI seven, private lease three, and notes twelve passed |
| `cargo build --workspace --release --locked` | Passed in 1 minute 44 seconds |
| `bash scripts/test-workspace.sh` | Failed at its service-test prerequisite with the same restart ownership error; example diagnostics were not reached |
| `bash scripts/test-workspace-service.sh` | Passed separately: seven service tests plus explicit approval, readback, decline, same-ID retry and v2 CLI inspection; this does not erase the two observed failures |
| `python -m pytest -q tests/architecture/test_documentation.py` | Four passed in 8.53 seconds |
| `ruff check .` | Passed |
| `python -m pytest -q` | 604 passed, one deselected in 143.17 seconds |
| `openspec validate --all --strict --no-interactive` | Both changes passed structural validation |
| `git diff --check` | Passed |

The release build and notes diagnostics were started separately after the
full-suite failure stopped the original command chain. The dedicated service
script passed separately after the notes script stopped at the failure.
This inconsistent result keeps the service defect open, rather than treating a
passing retry as a repair. Windows/macOS and mobile checks were not run locally.

## Remaining blocker

`authenticated_notes_approval_ownership_events_and_restart` failed at
`adapters/workspace/tests/service.rs:53` while reopening `ActionServer`, with
`service_already_owned` (six service tests passed, one failed). The reported lock
is `service-v2.lock` from `crates/edge-host/src/action_service.rs:131`, not the
repaired `workspace.lock`. That server still owns a bare `File` and relies on
close-only release; the exact retained descriptor has not been traced. The
failure also reproduced in `scripts/test-workspace.sh` (six service tests passed,
one failed), after the release build and notes regressions passed again.

The design explicitly excludes silently refactoring other lock owners. Requested
permission to extend the repair before changing this service lifetime. Keep task
2.1 and the dependent CLI-help integration task incomplete; do not count a later
lucky pass as resolution of this observed failure.

## Verification report

| Dimension | Assessment |
| --- | --- |
| Completeness | Five of eight tasks complete; three integration/handoff tasks remain |
| Correctness | All five ownership requirements mapped to implementation and focused tests; integrated service restart is still failing |
| Coherence | Private guard, destruction ordering, process identity, no public/schema changes, and no retry workaround match the design |

Scenario evidence:

- Live owner and rejected contender: `rejected_contenders_cannot_release_live_owner_across_processes`, including two rejected child opens and preserved receipt digest.
- Incidental alias and parallel children: `owner_teardown_releases_lease_with_live_handle_alias` plus the ten unchanged parallel notes runs.
- Failed deployment/schema/path checks: strengthened `competing_owner_and_replacement_deployment_are_rejected`, `locks_respect_deadline_and_corrupt_storage_is_not_reset`, and `symlinks_and_broad_permissions_are_rejected`; incompatible schema and broad permissions remain intact while the OS lease is reacquirable.
- Original notes/receipts and no duplicate: existing `compile_create_restart_reconcile_read_and_list`, retained exact receipt checks, and `process_death_before_commit_rolls_back_and_after_commit_recovers`.
- Storage compatibility/security: existing identity, principal, symlink and permission tests remain in the passing notes suite; application diff preserves validation and all database statements.

**Critical:** complete task 2.1 after resolving the separately scoped service
restart failure, finish task 2.2's notes diagnostic, then task 2.4 dependent verification.
No additional design warnings or pattern suggestions found in the focused change.
This is not archive/merge readiness or an independent security review.

## Commit handoff

After receiving the failed-check report, the user requested committing and pushing
the current changes. That checkpoint does not resolve the separate service-lock
defect, authorize its implementation, or complete the unchecked integration tasks.
