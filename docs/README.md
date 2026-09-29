# Documentation

**New here? Start with [Control two software lights](try-it.md).**
It is the single first-use path and requires no model or physical hardware.

Edge Delegate has three proposal paths—structured requests, deterministic command parsing,
and learned model proposals—and a shared validation/execution boundary. The paths do not
have equal language coverage or qualification. See [current status](qualification-status.md).

## Learn by doing

- [First-use tutorial](try-it.md): preview, execute, clarify, and retry on software lights.
- [Optional model tutorial](model-tutorial.md): verify a compatible artifact, preview a query,
  then optionally execute in a temperature simulator.

## Complete a task

- [Device-control guide](device-control.md): supported exact light commands and SDK examples.
- [Reconcile uncertain work](how-to/reconcile.md): inspect receipts without repeating actions.
- [Add a task/device integration](extensions.md): installed plugins, adapters, and conformance.
- [Gateway workflow](gateway-preview.md): persistent temperature sessions and Unix emulator.
- [Development runbook](development-runbook.md): environment, review, training, diagnostics.
- [Review tooling](implementation-batch-1.md): blind labels, adjudication and candidate checks.
  The filename is retained for compatibility; it is not a separate delivery roadmap.

## Look up an interface

- [Control SDK](reference/control-sdk.md): lifecycle, methods, request bindings and errors.
- [Commands](reference/cli.md): current executable command surface.
- [Results](reference/results.md): routes, execution states, envelopes and exit codes.
- [Glossary](glossary.md): acronyms and terms.
- [Schemas](../schemas/) and [specifications](../specs/): field contracts and invariants.
  A specification marked draft is a proposal, not implemented behavior.

## Understand the design

- [Architecture](system-architecture.md): all entry paths and who can dispatch actions.
- [Contracts and safety](contracts-and-safety.md): validation, permissions and recovery limits.
- [Model lifecycle](model-lifecycle.md): datasets, exports, training and outcome evaluation.
- [Model plugins and compute](model-plugins-and-compute.md): optional dependencies and artifacts.

## Follow development and evidence

- [Current status](qualification-status.md) owns implemented/experimental/unqualified claims.
- [Roadmap](roadmap.md) owns the active sequence and acceptance gates.
- [Release contract](release-contract.md) owns scope and trust assumptions.
- [Reference-device proposal](reference-device.md) is a procurement proposal, not support evidence.
- [Historical qualification log](history/qualification-status-through-2026-09-28.md) preserves older runs.
- [Historical roadmap](history/roadmap-through-2026-09-28.md) preserves superseded sequencing.

## Keeping these pages reliable

Each page has one purpose: tutorial, how-to, reference, explanation, status, or plan.
Do not copy the full quickstart or current evidence table into several documents.
The [documentation maintenance guide](contributing-docs.md) defines checks and ownership.

Code is evidence of implemented behavior; specs describe intended invariants. A disagreement
is a defect to resolve, not permission to silently reinterpret either one.
