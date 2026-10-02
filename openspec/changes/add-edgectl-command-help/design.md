# Design

## Context

See proposal.md for motivation. `crates/edge-cli/src/main.rs` uses a small handwritten parser. Root help precedes dispatch, but service commands currently dispatch before they could recognize help. Non-Linux handlers return platform errors. The existing CLI integration tests cover one preview fixture, two invalid forms and root help.

A short design is useful to settle help recognition and platform placement before implementation; this is not a new runtime architecture. Service semantics remain those documented in `docs/reference/execution-service.md`.

## Goals / Non-Goals

**Goals:** keep help a pure presentation path, make it portable, and preserve strict parsing for every non-help invocation.

**Non-Goals:** no generalized option parser, new library, automatic approval, credential inspection, service startup, transport support or changes to recovery.

## Decisions

1. Recognize only the exact two-argument forms before existing dispatch. Keep root/no-argument behavior intact. Do not scan for `--help` anywhere in an invocation: that could hide malformed commands or mistakes. Do not add `-h` or `help COMMAND` in this change.
2. Keep help text and dispatch inside the existing CLI module, with a small pure helper or constants if useful. Introducing a parser framework would change more behavior and dependencies than this task warrants.
3. Match tests against usage fragments and semantic boundaries rather than one full-output snapshot. This catches missing warnings while allowing harmless wrapping changes. Also assert exit status and stdout/stderr separation.
4. Run help tests in a uniquely named empty temporary directory using standard-library test helpers and clean up only that directory. These tests need no service credentials or worker. Check it remains empty. Review the early-return control flow as well: an empty-directory test alone cannot prove absence of every possible external access.
5. Update only the command discovery guidance in the existing service reference. Do not duplicate the API tables or rewrite the broader architecture in this patch.

## Risks / Trade-offs

- Help could accidentally imply native support or merge v1/v2 permissions -> assert distinct simulated-volume/real-note descriptions and explicit owner approval boundaries.
- A generic `--help` scan could accept invalid trailing arguments -> exact matching plus negative tests for every command.
- Non-Linux stubs could intercept help -> place help outside platform-gated code and retain portable integration tests in the existing three-OS Rust CI matrix.
- Help text could drift from syntax -> assert required flags and both preview forms, and review examples against the unchanged parser.

## Migration Plan

No schema, state, dependency or credential migration. Deliver as an additive CLI update. Reverting this change removes subcommand help without touching existing service state. Actual Rust and documentation checks are required before completion; OpenSpec validation alone is not verification of executable behavior.
