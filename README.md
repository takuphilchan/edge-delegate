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

Want to control more than the temperature example? The new
[two-light control SDK and demo](docs/device-control.md) supports explicit device targeting,
power, and brightness through structured requests or exact commands. It is a software-only,
non-ML implementation of the first expanded-control milestone; it does not retrain the model.

Want to exercise the three bounded commands without model misinterpretation? The optional
[`bounded-commands` path](docs/gateway-preview.md#bounded-commands-without-learned-model-execution)
uses a closed grammar and declines unrecognized wording. It is not a trained model or a
production qualification. Keep model-only accuracy tests separate.

The new [local gateway preview](docs/gateway-preview.md) adds bounded-task plugins, task-effect
evaluation, and a durable Unix-socket emulator integration. It is experimental: no artifact
or physical-device adapter is release-qualified yet. Project code is MIT licensed; model
licenses remain separate.

For a working, step-by-step path, start with [Try Edge Delegate](docs/try-it.md). It separates
fixed-plan runtime checks, model previews, and model-driven simulator execution, and explains
what a successful result does and does not prove.

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
- a targeted control SDK and durable two-light emulator, with ambiguous-name clarification,
  per-device authorization, and shared request identity tracking;
- a model-neutral planner interface and versioned model-plugin interface;
- a built-in FunctionGemma plugin with strict `submit_plan` parsing;
- one-shot and interactive non-executing clients for testing arbitrary queries against a typed
  device profile;
- model-free profile inspection and model-backed simulator execution with before/after state;
- model-neutral scenario generation, isolated splits, supervised export, Low-Rank Adaptation
  (LoRA) training,
  portable artifact manifests, and evaluation;
- separate software, safety, integration, property, architecture, and hardware tests.

Important limits are equally concrete:

- the edge CLI demo uses a static plan; a production request service is not wired yet;
- local execution targets the simulator, not physical hardware;
- `external` and `hybrid` routes return `external_required`; connector files are placeholders and
  send no data;
- the legacy 36-record pilot remains a pipeline fixture; the new 4,000-case functional corpus
  and 200 adversarial cases still need independent review and broader language coverage;
- embedded model export and representative target-device benchmarks are not implemented.

## Quick start

Use Linux or Ubuntu under Windows Subsystem for Linux (WSL), with Python 3.12 or newer.
From your checkout (no GPU, Hugging Face account, or model weights needed):

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
edge-delegate demo
edge-delegate-lab init-example --output /tmp/my-edge-profile
edge-delegate-lab profile-check --profile /tmp/my-edge-profile
```

Choose a new profile directory; `init-example` never overwrites one. Existing users can keep
their working virtual environment. The demo executes a fixed plan in a software simulator.
It is not a model-accuracy test.

Continue with [Try Edge Delegate](docs/try-it.md), the single first-use walkthrough. It includes
an exact-command emulator smoke test before the optional trained-model path. No trained model
is currently qualified or bundled. Do not assume machine-local `artifacts/` exist in a clone.

For a one-terminal execution session, `edge-delegate-lab run --emulator-dir DIRECTORY` starts
and owns the software emulator, displays readiness/progress, and retains its state and journal.
Select your model plugin/artifact explicitly; see [gateway usage](docs/gateway-preview.md).
This does not change the project's experimental qualification status.

Already have the trained adapter and want to stop entering test queries manually? Run
`bash scripts/test-latency.sh` from this checkout in your WSL model environment. It starts a fresh
emulator, checks six known outcomes repeatedly, and saves burst/idle timing reports. See the
[automatic test instructions](docs/try-it.md#5-test-automatically-instead-of-typing-every-query)
for prerequisites and limits; this is not a model qualification test.

An opt-in CUDA compiled-decoding path reduces resident inference overhead while preserving the
same validation and execution checks. See [inference acceleration](docs/model-plugins-and-compute.md#faster-resident-inference-experimental)
for settings, startup costs, and the reproducible comparison. It is not a qualified default or
a claim of state-of-the-art model quality.

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
ADAPTER_DIR=artifacts/training/functiongemma-tasks-v1-r2-b16/selected-adapter
edge-delegate-lab plan \
  --plugin functiongemma-tasks \
  --adapter "$ADAPTER_DIR" \
  --profile examples/local-display \
  --text "Show the current temperature."
```

Use `edge-delegate-lab interactive` with the same plugin, adapter, and profile arguments to keep
the model loaded while entering several independent queries. Interactive output is readable text
by default; use `/format json` for structured details and `/raw on` for raw generation.

To inspect saved context without a model:

```bash
edge-delegate-lab profile-check --profile examples/local-display
```

To test an actual model proposal through the runtime and observe simulated state changes:

```bash
edge-delegate-lab simulate --plugin functiongemma-tasks --adapter "$ADAPTER_DIR" \
  --text "Show the current temperature on the local display."
```

This uses a fresh, explicit local-display simulator, not the saved profile or physical hardware.
Invalid proposals are rejected. Successful execution does not by itself prove intent correctness.

See the [runbook](docs/development-runbook.md) before generating data, training, or evaluating a
real model. FunctionGemma is gated on Hugging Face and requires accepted terms and WSL-side
authentication.

For installed task/device extensions, see [Extension contract](docs/extensions.md). The
separately installable counter example demonstrates a second task catalog and device adapter;
it is deterministic software, not another trained model or physical-device qualification.

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

The next model milestone is qualifying dataset v1: multiple independent groups per route, more executable
plan shapes, policy and state counterfactuals, safe deny demonstrations, multilingual examples,
and frozen held-out evaluations. A larger or different model should be compared only after that
shared data and evaluation contract is stable.

See the [milestone roadmap](docs/roadmap.md) for acceptance criteria covering data, additional
models, physical devices, and external assistance.
