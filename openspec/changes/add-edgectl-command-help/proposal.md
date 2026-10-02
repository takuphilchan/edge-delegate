# Proposal

## Why

The CLI already exposes preview, simulated-volume execution and real-note execution, but only root `--help` succeeds. Developers asking a subcommand for help receive argument or platform errors, obscuring the difference between inspecting a plan and submitting an approved action.

## What Changes

- Add successful, non-executing `--help` for `preview`, `capabilities`, `service` and `workspace-service` on every platform where the CLI builds.
- Show exact argument order, a concrete usage example, platform requirements and the command's execution boundary.
- Explain that `capabilities` addresses the saved-context preview service, `service` addresses v1 simulated volume, and `workspace-service` addresses v2 real notes with separate credentials.
- Test help output, exit status, unavailable-service independence and preservation of invalid-argument behavior.
- Add a short command-help discovery section to the execution-service reference.

Acceptance: each exact `<command> --help` invocation exits 0 with useful stdout and no stderr, requires no host or credential files, and does not dispatch actions. Existing valid commands, JSON results and approval requirements remain unchanged.

Excluded: parser replacement, short aliases, reordered flags, new service commands, authentication or storage changes, input-size test expansion, architecture-document rewrite, native controls, model work, commits and publication.

## Capabilities

### New Capabilities

- `cli-command-help`: Discoverable, platform-independent help for the existing edgectl commands, including truthful preview/execution boundaries and compatibility rules.

### Modified Capabilities

None. No maintained OpenSpec capabilities exist yet; this change does not retrospectively specify or qualify the runtime.

## Impact

- `crates/edge-cli/src/main.rs`: handle exact help forms before platform dispatch and argument/file processing.
- `crates/edge-cli/tests/cli.rs`: portable CLI regression tests alongside the existing preview fixture.
- `docs/reference/execution-service.md`: document how to discover command usage without starting a service.
- No new dependencies, wire contracts, credentials or journal migrations. Existing Rust CI already runs CLI tests on Linux, Windows and macOS; no workflow modification is planned.
