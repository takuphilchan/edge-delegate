# Edge Delegate

Edge Delegate turns a natural-language request into a small, typed device plan. A model may
propose that plan, but deterministic code decides whether it is valid and whether any device
operation may run.

The project is deliberately split in two:

- `edge-delegate` is the small dependency-free runtime CLI. The deterministic runtime modules
  validate plans and run approved local steps through a device interface.
- `edge-delegate-lab` is the development-machine tool. It generates data, loads model plugins,
  trains adapters, and evaluates model quality.

Training can improve proposals. It cannot bypass validation, policy, or the executor.

## Start here

Read the [documentation guide](docs/README.md) for the mental model and the shortest reading
path for your task. The [system architecture](docs/system-architecture.md) follows one request
through the code and explains where runtime, model, and training responsibilities separate.

For commands, use the [development runbook](docs/development-runbook.md). For unfamiliar terms,
use the [glossary](docs/glossary.md).

## What works today

Version `0.3.0` has an implemented vertical slice:

- a bounded internal request type and versioned capability, state, policy, plan, and handoff contracts;
- strict Plan Intermediate Representation (Plan IR) parsing and deterministic validation;
- a coordinator, sequential executor, replay protection, and privacy-minimal audit events;
- a deterministic simulator implementing the same device interface expected from future
  hardware adapters;
- a model-neutral planner interface and versioned model-plugin interface;
- a built-in FunctionGemma plugin with strict `submit_plan` parsing;
- one-shot and interactive non-executing clients for testing arbitrary queries against a typed
  device profile;
- model-neutral scenario generation, isolated splits, supervised export, Low-Rank Adaptation
  (LoRA) training,
  portable artifact manifests, and evaluation;
- separate software, safety, integration, property, architecture, and hardware tests.

Important limits are equally concrete:

- the edge CLI demo uses a static plan; a production request service is not wired yet;
- local execution targets the simulator, not physical hardware;
- `external` and `hybrid` routes return `external_required`; connector files are placeholders and
  send no data;
- the 36-record pilot dataset verifies the pipeline but is not enough for deployment;
- embedded model export and representative target-device benchmarks are not implemented.

## Quick start

Run Python, PyTorch, and training commands inside Ubuntu on Windows Subsystem for Linux (WSL):

```bash
cd /mnt/d/project/edge-delegate
source /home/phil/.venvs/edge-model/bin/activate
python -m pip install -e ".[dev]"
```

Run the deterministic simulator-backed example:

```bash
edge-delegate demo
```

It proposes a fixed two-step test plan, validates the complete plan, reads a simulated
temperature, and writes the value to a simulated display.

Validate the committed Plan IR without executing it:

```bash
edge-delegate validate \
  --capabilities examples/local-display/capabilities.json \
  --state examples/local-display/state.json \
  --policy examples/local-display/policy.json \
  --plan examples/local-display/plan.json \
  --now 2026-01-01T12:00:00Z
```

Install host-side model dependencies only when needed:

```bash
python -m pip install -e ".[inference]"
python -m pip install -e ".[training]"
```

Then list the available plugins and inspect compute without loading model weights:

```bash
edge-delegate-lab models
edge-delegate-lab compute-inspect
edge-delegate-lab compute-plan --plugin functiongemma
```

After training an adapter, test one query without executing capabilities:

```bash
ADAPTER_DIR=artifacts/training/functiongemma-pilot-v0/final-adapter
edge-delegate-lab plan \
  --plugin functiongemma \
  --adapter "$ADAPTER_DIR" \
  --profile examples/local-display \
  --text "Show the current temperature."
```

Use `edge-delegate-lab interactive` with the same plugin, adapter, and profile arguments to keep
the model loaded while entering several queries.

See the [runbook](docs/development-runbook.md) before generating data, training, or evaluating a
real model. FunctionGemma is gated on Hugging Face and requires accepted terms and WSL-side
authentication.

## Repository map

| Path | Owns |
| --- | --- |
| `src/edge_delegate/contracts/` | Dependency-free typed data exchanged between components. |
| `src/edge_delegate/ir/` | Strict Plan-IR parsing, canonicalization, fingerprints, and validation. |
| `src/edge_delegate/policy/` | Deterministic permissions, approvals, privacy, and risk helpers. |
| `src/edge_delegate/planner/` | The model-neutral planner protocol and planner implementations. |
| `src/edge_delegate/runtime/` | Coordination, execution, ports, idempotency, and audit. |
| `src/edge_delegate/simulator/` | A deterministic implementation of the device boundary. |
| `src/edge_delegate/model_plugins/` | Plugin discovery, compute contracts, and artifact validation. |
| `src/edge_delegate/data/` | Model-neutral scenario generation, validation, splitting, and fingerprints. |
| `src/edge_delegate/evaluation/` | Model-neutral software, model, safety, calibration, and hardware evaluation. |
| `src/edge_delegate/connectors/` | Placeholder modules for future external-model connectors. |
| `src/edge_delegate_lab/` | Host-only data, model, training, and evaluation commands. |
| `schemas/` | Public JSON wire schemas. |
| `specs/` | Normative invariants, protocols, and threat assumptions. |
| `docs/` | Human-readable explanations and operating instructions. |
| `tests/` | Software, safety, architecture, model-boundary, and hardware checks. |

## Verify changes

```bash
make verify
make test-hardware
```

Ordinary verification excludes the explicit GPU test so the deterministic core can run on CI
and non-GPU hosts.

## Next milestone

The next model milestone is dataset v1: multiple independent groups per route, more executable
plan shapes, policy and state counterfactuals, safe deny demonstrations, multilingual examples,
and frozen held-out evaluations. A larger or different model should be compared only after that
shared data and evaluation contract is stable.
