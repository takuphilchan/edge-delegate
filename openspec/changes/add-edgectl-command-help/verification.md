# Verification — 2026-10-02

Status: **integration verification blocked**. The command-help implementation was
already present at the start of this pass. No application code was changed during
this verification. Do not treat the checked planning artifacts or passing help
tests as evidence that the full workspace is ready to merge.

## Environment and commands

Ubuntu under WSL, repository `/mnt/d/project/edge-delegate`, Cargo 1.90.0.
Python 3.14.4 and Ruff used the existing
`/home/phil/.venvs/edge-model` environment. Tests used their own temporary state;
no installed-user workspace, native device, or model was exercised.

| Command | Observed result |
| --- | --- |
| `cargo fmt --all -- --check` | Passed |
| `cargo clippy --workspace --all-targets --locked -- -D warnings` | Passed |
| `cargo test --workspace --locked` | Failed in `edge-workspace` notes tests; the preceding CLI suite passed all seven tests |
| `cargo test --locked -p edge-workspace --test notes` | Reproduced the same two failures: eight passed, two failed |
| `cargo test --locked -p edge-workspace --test notes -- --test-threads=1` | Ten passed; diagnostic only, not a substitute for the normal parallel suite |
| `ruff check .` | Passed |
| `python -m pytest -q` | 604 passed, one deselected in 167.37 seconds, including documentation checks |
| `openspec validate add-edgectl-command-help --strict --no-interactive` | Passed structural validation with OpenSpec 1.14.0 |
| `git diff --check` | Passed |

All four documented `cargo run --locked -p edge-cli -- <command> --help`
invocations (`preview`, `capabilities`, `service`, `workspace-service`) were also
run successfully. Cargo's build messages are separate from the tested binary's
stdout/stderr contract.

## Blocking finding

Normal parallel testing failed twice in:

- `compile_create_restart_reconcile_read_and_list`,
  `adapters/workspace/tests/notes.rs:137`: reopening after dropping the prior
  owner returned `workspace_already_owned`.
- `competing_owner_and_replacement_deployment_are_rejected`,
  `adapters/workspace/tests/notes.rs:333`: reopening the original identity after
  the competing/wrong-identity checks unexpectedly failed.

Both passed when the same test executable ran with one test thread. This is
evidence of concurrency-sensitive behavior, not proof of its root cause. The
notes tests also launch crash-helper child processes; lock lifetime and child
process interactions need investigation. Do not disable parallel tests, add
blind retries, remove ownership checks, or call the issue fixed on this evidence.

The notes implementation is outside this change's explicitly agreed help-only
scope. Task 2.1 remains unchecked pending resolution and a clean normal suite.
The apply workflow is paused rather than silently expanding this change into a
storage change. No new recovery, onboarding, CLI convenience, Windows transport,
or Python-client implementation is claimed by this verification.

## Requirement review

- **Command-specific help:** seven CLI tests passed, including positive checks
  for all four exact forms, their required flags, examples, and argument order.
- **No execution:** positive help cases run in empty temporary directories and
  leave them empty. Source review confirms the exact-help early return precedes
  platform dispatch, file reads, credential loading, and service connection.
- **Unavailable transport:** help matching is outside Linux-only handlers and
  states the Linux/WSL limitation. Windows/macOS execution was not run locally;
  the existing Rust CI matrix covers these tests when separately submitted.
- **Truthful boundaries:** tests assert saved-context inspection versus v1
  simulated volume versus v2 real notes, separate credentials, and owner approval.
- **Compatibility:** root help/no-argument equality, non-executing preview, and
  all seven invalid help-like forms passed. Invalid forms keep exit code 2,
  empty stdout, and a stderr diagnostic.
- **Scope:** the reviewed application diff changes help text, exact-help
  dispatch, CLI tests, and the service-reference help section only. No runtime,
  protocol, dependency, journal, permission, or existing non-help parsing changes.
  Pre-existing README/OpenSpec/bootstrap work was preserved.

## Evidence limits

The earlier red-test run referenced by task 1.1 was not repeated and its raw log
was not available in this pass. Existing checked tasks were not rewritten as new
evidence. Windows/macOS CI, mobile cross-compilation, release builds, packaging,
installed-client tests, and the service smoke scripts were not run in this pass.
No native-device qualification, independent review, merge readiness, archive,
commit, push, or publication is implied.

## Subsequent checkpoint - 2026-10-02

The separately scoped notes lease repair passed its focused regressions, but the
full suite then exposed `service_already_owned` in the v2 service restart test.
See the [lease repair verification](../fix-workspace-lease-release/verification.md)
for the new evidence, including the successful release build and the unresolved
service failure. Task 2.1 remains incomplete. The user subsequently requested a
commit and push of the current work; this is a checkpoint, not a clean-suite or
release-readiness claim. The earlier failure evidence above remains historical.
