# Edge Delegate documentation

Build applications that submit supported requests through a local permission and execution
boundary. Start with one integration below; you do not need to read the entire documentation set.
For the product's purpose and limits, see the [project overview](../README.md).

## Get started

| Your goal | Follow this tutorial | What you will finish with |
| --- | --- | --- |
| Use the new authenticated Rust service | [Execute an approved request](tutorials/rust-execution-service.md) | A scoped client, a separately approved software write, and a durable result |
| Try the existing Python device controls | [Control two software lights](try-it.md) | A preview, a targeted change, ambiguity handling and receipt replay |
| Test a trained planner | [Run a local model](model-tutorial.md) | Model-generated plans for temperature/display tasks |

The first two paths need no model or physical hardware. The model path has separate artifact
and compute requirements. The Rust service changes software volume state only; Python light
controls do not use the trained temperature model.

## Build an application

- **Rust:** [Execution-service reference](reference/execution-service.md) for authentication,
  methods, scopes, results and limits. Start with structured requests; no interpretation worker
  is attached to this service.
- **Python:** [Control SDK reference](reference/control-sdk.md) for the existing in-process
  device runtime. This is not a Python client for the Rust socket service.
- **Device integration:** [Adapter and task guide](extensions.md) for the existing Python
  extension interfaces and conformance expectations.

Python/TypeScript clients for the Rust service, native platform adapters and the companion
application are planned. Do not import private host internals as substitutes for public clients.

## Understand execution

- [Execution concepts](concepts/execution.md): permission, approval, dispatch and uncertainty.
- [Python architecture](system-architecture.md): the current Python request path.
- [Repository layout](repository-layout.md): component ownership and migration rules.
- [Glossary](glossary.md): terms used in code, reports and training.

## Operate and troubleshoot

- [Rust service troubleshooting](tutorials/rust-execution-service.md#troubleshooting): startup,
  credential, approval and submission failures.
- [Rust results and recovery](reference/execution-service.md#results-and-recovery):
  interpret durable records without replaying uncertain writes.
- [Rust security and storage](reference/execution-service.md#security-and-storage):
  credentials, revocation, retained evidence and unfinished operational features.
- [Python reconciliation](how-to/reconcile.md): inspect receipts for existing Python sessions.
- [Python command inventory](reference/cli.md) and [result reference](reference/results.md):
  look up implemented Python commands and statuses.

## Develop and evaluate models

The lab is separate from the execution service. Model quality and runtime authorization are
different requirements: passing permission checks does not establish that a model understood a request.

1. [Model lifecycle](model-lifecycle.md): data, training, candidate selection and evaluation.
2. [Review and candidate tooling](implementation-batch-1.md): independent labels and export gates.
3. [Model plugins and compute](model-plugins-and-compute.md): compatibility and inference settings.
4. [Gateway preview](gateway-preview.md): Python temperature/display sessions and emulator operation.

## Contribute and inspect evidence

- [Development runbook](development-runbook.md): task-specific setup and checks.
- [Documentation standard](contributing-docs.md): writing, examples and drift checks.
- [Qualification status](qualification-status.md): dated measurements and known gaps.
- [Roadmap](roadmap.md): the single active implementation sequence.
- [Release contract](release-contract.md): target scope and acceptance gates.
- [Architecture decision](decisions/cross-platform-redesign.md): the planned cross-platform product.

**Implemented** means code exists. **Experimental** means its interface or deployment is not
supported as a production release. **Qualified** requires matching evidence for a named
configuration. **Planned** means unavailable. These labels are not interchangeable.

## Advanced implementation examples

These explain individual Rust layers; they are not prerequisites for the service tutorial:

| Example | Boundary it exercises |
| --- | --- |
| [Foundation](tutorials/rust-foundation.md) | Strict contracts and offline preview |
| [Preview host](tutorials/rust-local-service.md) | Authenticated saved-context inspection; no execution |
| [Recovery](tutorials/rust-recovery.md) | Durable operation records and receipt reconciliation |
| [Supervision](tutorials/rust-supervision.md) | Child-process faults and owner-console confirmation |
| [Authority](tutorials/rust-authority.md) | Scoped in-process handles, admission and cancellation |

Historical measurements and superseded plans remain in [history](history/). They explain prior
decisions; they are not current installation instructions or evidence of supported deployment.
