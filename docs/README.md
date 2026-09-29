# Edge Delegate Documentation

This guide explains the implemented project in the same boundaries used by the code. Detailed
wire rules live in `specs/` and `schemas/`; these pages explain how to understand and operate
them.

**New here?** Follow [Try Edge Delegate](try-it.md) to run the system and understand exactly what
each test proves. Then use [Delivery plan](roadmap.md) for phased work, dependencies, and release gates.

For the expanded device-control direction, try [two-light controls](device-control.md).
It is a separate deterministic SDK path; the existing trained temperature plugins are unchanged.

The [release contract](release-contract.md) records scope and trust boundaries. Use
[first-batch tooling](implementation-batch-1.md) for numeric challenges, review history, candidate
packs and the public session API. [Reference-device proposal](reference-device.md) is awaiting
procurement approval, not a hardware-support claim.

For the new bounded-task model and durable device-emulator workflow, use the
[local gateway preview](gateway-preview.md). This is explicitly experimental.
The [qualification status](qualification-status.md) records what was tested and why neither
current model candidate is supported yet.

## The mental model

Edge Delegate has one safety rule that everything else follows:

> A model proposes a plan. Deterministic code authorizes and executes it.

A request moves through these stages:

```text
request + device capabilities + live state + policy
                         |
                         v
               Planner proposes Plan IR
                         |
                         v
              deterministic validation
                    /           \
              rejected       validated
                                  |
                                  v
                       route decision or local executor
```

The model never receives direct access to sensor or actuator functions. The legacy FunctionGemma
plugin submits complete plans through `submit_plan`. The compact `functiongemma-tasks` plugin
uses `select_task`; trusted code turns that short decision into a plan. The independently trained
`task-classifier` plugin uses the same task compiler without a generative language model.

## The three parts of the repository

| Part | Code | Responsibility |
| --- | --- | --- |
| Edge runtime | `contracts/`, `ir/`, `policy/`, `planner/base.py`, and `runtime/` under `src/edge_delegate/` | Typed contracts, planning boundary, validation, policy, coordination, and execution. It has no third-party runtime dependencies. |
| Model plugin | `src/edge_delegate/model_plugins/` plus model-specific planner/trainer code | Creates a planner for one model family and translates its native format to typed Plan IR. FunctionGemma is the first plugin. |
| Host lab | `src/edge_delegate_lab/` | Generates datasets, resolves training compute, trains adapters, verifies artifacts, and evaluates models. It is not imported by the edge runtime. |

The plugin is selected when a host application or lab command constructs a planner. It is not a
separate authority inside the coordinator. Once constructed, every planner must satisfy the same
small `Planner.plan(request, context) -> PlanIR` interface.

Some model-neutral host support remains in `src/edge_delegate/data/` and
`src/edge_delegate/evaluation/`. The lab composes those libraries, but the runtime package does
not import them. The simulator is a device adapter used by the demo, data generator, and tests;
the runtime depends only on the `DeviceGateway` interface.

## Read according to your task

| Goal | Read |
| --- | --- |
| Run a working example and distinguish harness tests from model tests | [Try Edge Delegate](try-it.md) |
| Choose the next improvement and its acceptance evidence | [Milestone roadmap](roadmap.md) |
| Understand how a request moves through the code | [System architecture](system-architecture.md) |
| Understand Plan IR and why execution is fail-closed | [Contracts and safety](contracts-and-safety.md) |
| Add another model or understand adapter portability | [Model plugins, artifacts, and compute](model-plugins-and-compute.md) |
| Install a task/device extension and understand its guarantees | [Extension contract](extensions.md) |
| Understand data generation, training, and evaluation | [Model lifecycle](model-lifecycle.md) |
| Review proposed dataset-v2 labels, independent expectations, and collection gates | [Dataset v2 draft](../specs/dataset-v2.md) (collection policy not approved) |
| Check review records before a pilot dataset is accepted | [Review-workspace tooling](../specs/dataset-review-workspace.md) (implemented; not training approval) |
| Review the 80-example exposed pilot draft | [Pilot review instructions](../data/fixtures/pilot-v2/README.md) (all labels pending) |
| Run setup, training, evaluation, or troubleshooting commands | [Development runbook](development-runbook.md) |
| Look up an acronym or project term | [Glossary](glossary.md) |

Recommended first read: this page, then [System architecture](system-architecture.md). After that,
choose only the page that matches your work.

## What each document owns

This division prevents the same explanation from drifting across several files:

- [Try Edge Delegate](try-it.md) owns the first-use walkthrough and what each test proves.
- [Milestone roadmap](roadmap.md) owns planned work and acceptance criteria, not implemented behavior.
- [System architecture](system-architecture.md) owns component boundaries, the actual request
  path, dependency direction, and current-versus-future wiring.
- [Contracts and safety](contracts-and-safety.md) owns data shapes, validation rules, permissions,
  approvals, replay protection, and audit behavior.
- [Model plugins, artifacts, and compute](model-plugins-and-compute.md) owns plugin discovery,
  model isolation, artifact compatibility, and compute-plan selection.
- [Model lifecycle](model-lifecycle.md) owns canonical data, model-specific exports, preflight,
  training, and evaluation meaning.
- [Dataset v2 draft](../specs/dataset-v2.md) owns proposed collection and labeling rules; it does
  not describe an implemented generator or independently reviewed dataset.
- [Development runbook](development-runbook.md) owns commands, expected outputs, and failure
  recovery. It should not be used as the architecture specification.
- [Glossary](glossary.md) owns definitions and acronym expansions.

## Current boundary at a glance

| Area | State now |
| --- | --- |
| Typed contracts, parsing, validation, policy, and simulator execution | Implemented |
| Runtime device/audit/idempotency interfaces | In-memory simulation plus versioned deadline gateway and SQLite journal |
| FunctionGemma inference and Low-Rank Adaptation (LoRA) training | Implemented on the host development machine |
| Portable adapter manifest and strict file verification | Implemented |
| Model evaluation | Implemented; model doctor never executes, dataset evaluation may execute only in the simulator |
| Physical hardware adapters | Not implemented |
| External-model handoff transmission | Not implemented; connector modules are placeholders |
| Embedded model export and target-device benchmarks | Not implemented |
| Deployment-quality model | Not achieved; both bounded-task candidates fail qualification on the new held-out corpus |

## Sources of truth

| Question | Source of truth |
| --- | --- |
| What fields are accepted on public JSON boundaries? | [`schemas/`](../schemas/) and [`src/edge_delegate/contracts/`](../src/edge_delegate/contracts/) |
| What makes a plan executable? | [`src/edge_delegate/ir/static_check.py`](../src/edge_delegate/ir/static_check.py) |
| What happens for each route? | [`src/edge_delegate/runtime/coordinator.py`](../src/edge_delegate/runtime/coordinator.py) |
| What can invoke a device? | [`src/edge_delegate/runtime/executor.py`](../src/edge_delegate/runtime/executor.py) and [`ports.py`](../src/edge_delegate/runtime/ports.py) |
| How is a model selected and loaded? | [`src/edge_delegate/model_plugins/`](../src/edge_delegate/model_plugins/) |
| How is FunctionGemma trained? | [`src/edge_delegate_lab/models/functiongemma/`](../src/edge_delegate_lab/models/functiongemma/) |
| What behavior is normative? | Accepted contracts in [`specs/`](../specs/); explicitly marked drafts are proposals only |
| What commands are supported? | Runtime/lab CLI parsers, the emulator entry point, and the [development runbook](development-runbook.md) |

[Next: System architecture](system-architecture.md)
