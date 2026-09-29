# Find your way through Edge Delegate

Edge Delegate connects requests to configured device operations. The runtime decides what may
execute and tracks outcomes; an optional model helps interpret language; the lab develops and
tests that model. These are related parts, not three names for the same thing.

If that purpose is still unclear, start with the [project overview](../README.md).
You do not need a model, hardware or a training run to try the system.

## New here? Follow this path

1. **See it work:** [Control two software lights](try-it.md). Install the core, preview a
   request, execute it, and see ambiguity and retries handled. No model or board is needed.
2. **Understand what happened:** [Architecture](system-architecture.md). Follow that same
   request through interpretation, checks, execution and recorded results.
3. **Choose what to build:** use one of the paths below. Stop when you have what you need;
   the reference pages are for lookup, not required reading in order.

## Choose your goal

| I want to… | Start here | What I should have afterwards |
| --- | --- | --- |
| Call controls from my Python application | [Control SDK example](reference/control-sdk.md#small-complete-example) | A typed request that previews and executes against a software device |
| See which light phrases work | [Command guide](device-control.md#supported-exact-commands) | The exact supported vocabulary and parameter limits |
| Try a trained model | [Model tutorial](model-tutorial.md) | A compatible artifact loaded for preview, then optional software execution |
| Add a device or task | [Integration guide](extensions.md) | An understanding of the adapter/catalog work and required conformance tests |
| Improve a model's decisions | [Model lifecycle](model-lifecycle.md) | The relationship between reviewed labels, training, candidate selection and outcome tests |
| Recover after an uncertain result | [Reconciliation guide](how-to/reconcile.md) | A receipt-inspection procedure that does not blindly repeat a write |
| Decide whether I can deploy this | [Current status](qualification-status.md) | Implemented capabilities, known failures and missing qualification evidence |

SDK means software development kit: the Python interfaces you call from your own application.
A device adapter implements operations; a model adapter contains learned changes to model weights.
They solve different problems.

## Do not accidentally switch experiments

The software-light tutorial uses structured requests and exact command parsing.
The learned-model tutorial uses the separate temperature/display task catalog.
The model has not learned lights merely because the light demonstration works.

Preview means no device action is dispatched. Simulation can execute actions, but only against
software state. Confirmed execution means the proposed operation completed; it is not proof
that a model understood the user correctly or that a physical effect was independently observed.

## Reference: use when you need a detail

- [Python control interface](reference/control-sdk.md): construction, lifecycle, methods and exceptions.
- [Command inventory](reference/cli.md): implemented commands, generated from the parsers.
- [Results](reference/results.md): routes, statuses, receipt replay and exit codes.
- [Glossary](glossary.md): unfamiliar terms and acronyms.
- [Contracts and safety](contracts-and-safety.md): arguments, permissions, approvals and recovery limits.
- [Model plugins and compute](model-plugins-and-compute.md): model isolation, artifacts and inference settings.
- [Schemas](../schemas/) and [specifications](../specs/): wire formats and intended invariants.
  A draft specification is not proof of an implemented feature.

## Development and advanced workflows

The [development runbook](development-runbook.md) is a task reference, not a sequence that
every user must run. It includes environment setup, diagnostics, historical pilot recipes and
review commands. The [gateway guide](gateway-preview.md) explains persistent temperature
sessions and the separate-process software device once you have chosen a planner.

For dataset work, use [review and candidate tooling](implementation-batch-1.md).
The old filename is retained for compatibility; it is not a second roadmap. Structural checks
do not approve human labels, and an example training recipe is not approval to promote a model.

## Plans, evidence and history

- [Current status](qualification-status.md): what is implemented and what has actually been measured.
- [Roadmap](roadmap.md): the single active delivery sequence and release gates.
- [Release contract](release-contract.md): intended scope, trust assumptions and support requirements.
- [Reference-device proposal](reference-device.md): proposed hardware, not a purchase or support claim.
- [Historical results](history/qualification-status-through-2026-09-28.md) and
  [historical roadmap](history/roadmap-through-2026-09-28.md): background, not onboarding instructions.

If a page leaves you unsure what to do next, that is a documentation defect.
The [maintenance guide](contributing-docs.md) explains how to improve and verify these pages.
