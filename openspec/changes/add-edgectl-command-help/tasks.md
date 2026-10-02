# Tasks

## 1. Command help and regression coverage

- [x] 1.1 Add portable regression tests in `crates/edge-cli/tests/cli.rs` for all four exact command-help forms, output/exit contracts, examples, argument order, platform statements and approval boundaries. Include an empty temporary working directory with no service/credentials and assert no files are created. Run `cargo test --locked -p edge-cli --test cli` in WSL before implementation and record that the new positive help cases fail for the expected current behavior.
- [x] 1.2 Implement exact command-help recognition before platform dispatch in `crates/edge-cli/src/main.rs`; keep the existing parser and dependencies. Add no-argument/root-help compatibility and invalid help-like argument cases from the spec alongside the existing offline-preview fixture. Verify `cargo test --locked -p edge-cli` passes, and inspect the help early-return path for absence of file, credential and service access.
- [x] 1.3 Add a concise help-discovery section to `docs/reference/execution-service.md`, distinguishing preview, v1 and v2 without duplicating API documentation. Run every documented help invocation, verify the displayed flag order against the parser, and run `python -m pytest -q tests/architecture/test_documentation.py` in the existing WSL development environment.

## 2. Integration verification and review handoff

- [ ] 2.1 Run `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets --locked -- -D warnings`, and `cargo test --workspace --locked` in WSL. Record command results and any failures; use the existing Windows/macOS CI matrix for portable coverage and explicitly identify any platform tests not run. Do not claim native-device qualification.
- [x] 2.2 Run `ruff check .` and `python -m pytest -q` in the existing WSL environment for the repository's compatibility checks. Record actual outcomes and any unavailable prerequisites without modifying unrelated failures or broadening scope.
- [x] 2.3 Run `openspec validate add-edgectl-command-help --strict --no-interactive` and `git diff --check`; review the implementation against every scenario. Record verification evidence in this change, distinguish planning validation from software tests, and confirm no runtime/protocol/dependency/journal changes or unrelated edits were introduced. Leave commits, pushes and archiving for separately requested workflows.

Verification and the task 2.1 blocker are recorded in [verification.md](verification.md).
