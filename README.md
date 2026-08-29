# Edge Delegate

Edge Delegate is a model-independent planning and safety runtime for constrained and embedded devices. It turns a candidate natural-language plan into a small, typed Plan IR, checks it against declared device capabilities, live state, permissions, approvals, privacy rules, and resource budgets, and only then permits execution.

The small model is not the security boundary and is not intended to be a general chatbot. It may propose a plan; deterministic code decides whether that plan is executable.

## Current status

Version `0.3.0` implements the deterministic vertical slice, measured real-model baseline, and guarded LoRA training loop:

- Strict versioned Python contracts and matching JSON Schemas
- Bounded Plan-IR JSON parsing with duplicate-key and non-finite-number rejection
- Stable canonical serialization and SHA-256 plan fingerprints
- Capability, argument, prior-step reference, precondition, and route checks
- Permission, exact-plan approval, connectivity, freshness, memory, latency, energy, and timeout checks
- Mandatory idempotency for write and physical capabilities
- Deterministic device simulation with sensors and state-changing capabilities
- Sequential local execution with output-reference resolution and replay protection
- Fail-closed request coordination and privacy-minimal audit events
- Dependency-free BM25 capability retrieval with stable, explainable ranking
- A strict FunctionGemma adapter behind a replaceable backend for offline tests
- One `submit_plan` function-call boundary for complete multi-step Plan IR
- Simulator-authored scenarios spanning local, hybrid, external, clarify, defer, and deny routes
- Leakage-resistant group splits, isolated safety cases, fingerprints, and manifests
- FunctionGemma-compatible SFT JSONL export without model-generated gold labels
- Strict training preflight for Plan-IR labels, scenario leakage, and token truncation
- BF16 all-linear LoRA training with assistant tool-call-only loss and best-checkpoint selection
- Reproducible training metadata with package, model, dataset, hardware, memory, and timing details
- Adapter-aware inference and a non-executing six-route model doctor
- Parsing, static validity, execution, routing, exact-plan, calibration, and abstention metrics
- CLI demo, validation, dataset generation, and gold/model evaluation commands
- Unit, property, integration, regression, safety, hardware, and CI checks

External LLM handoff, embedded export, and representative hardware model benchmarks remain later milestones. The current fine-tune proves the training contract, but the 36-record pilot corpus is intentionally too small and imbalanced for deployment.

## Environment setup

The existing WSL environment can be used directly:

```bash
cd /mnt/d/project/edge-delegate
source /home/phil/.venvs/edge-model/bin/activate
python -m pip install -e ".[dev]"
```

The runtime itself has no third-party Python dependencies. The `dev` extra installs testing and lint tooling. Real FunctionGemma inference is isolated in an optional extra:

```bash
python -m pip install -e ".[planner]"
```

`google/functiongemma-270m-it` is gated on Hugging Face. Accept its license and authenticate before a real-model run; ordinary tests use a scripted backend and do not download model weights.

Install the separate training stack only on a development machine:

```bash
python -m pip install -e ".[training]"
```

## Run the vertical slice

```bash
edge-delegate demo
```

The demo reads a simulated temperature, passes the typed result to a simulated display capability, validates the plan, executes it, and prints a structured outcome.

Validate external contract files without executing anything:

```bash
edge-delegate validate \
  --capabilities examples/local-display/capabilities.json \
  --state examples/local-display/state.json \
  --policy examples/local-display/policy.json \
  --plan examples/local-display/plan.json \
  --now 2026-01-01T12:00:00Z
```

An invalid plan exits with code `2`; malformed input or operational failure exits with code `1`.

## Build and evaluate the pilot data

Generate reviewed scenarios, grouped splits, a manifest, and the initial FunctionGemma SFT export:

```bash
edge-delegate generate-data --output data/processed/pilot --seed 17
```

First verify the evaluator against its gold plans:

```bash
edge-delegate evaluate \
  --dataset data/processed/pilot/all.jsonl \
  --planner gold \
  --output artifacts/evaluation/gold-self-check.json
```

Then diagnose the unmodified FunctionGemma baseline after installing the planner extra and authenticating with Hugging Face:

```bash
edge-delegate model-doctor \
  --model-id google/functiongemma-270m-it \
  --output artifacts/model-doctor/functiongemma-prompt-baseline.json
```

Preflight the exact tokenizer rendering and split isolation before training:

```bash
edge-delegate train --config configs/training/pilot.yaml --preflight-only
```

The two-step smoke configuration checks the complete training and adapter-loading path. The pilot configuration runs the first small experiment:

```bash
edge-delegate train --config configs/training/smoke.yaml
edge-delegate train --config configs/training/pilot.yaml
edge-delegate model-doctor \
  --model-id google/functiongemma-270m-it \
  --adapter artifacts/training/functiongemma-pilot-v0/final-adapter \
  --output artifacts/model-doctor/functiongemma-pilot-v0.json
```

On the RTX 5060 Laptop GPU, the measured prompt-only model and first pilot adapter produced:

| Six-route integration smoke | Prompt-only | Pilot LoRA |
| --- | ---: | ---: |
| Parse-valid plans | 0/6 | 6/6 |
| Correct request ID | 0/6 | 6/6 |
| Statically valid plans | 0/6 | 3/6 |
| Correct route | 0/6 | 3/6 |
| Exact plan | 0/6 | 1/6 |

The pilot used 3,796,992 trainable adapter parameters, peaked near 4.03 GB allocated GPU memory during training, and selected its best checkpoint at epoch 5. These are engineering measurements from a tiny integration fixture, not general model-quality claims. The gold run likewise remains only a harness self-check.

## Verify changes

```bash
make verify
make test-hardware
```

Ordinary tests exclude hardware checks so the deterministic core runs on CI and non-GPU edge hosts. The hardware target is tested explicitly.

## Repository boundaries

- `specs/` defines architecture, contracts, threats, and evaluation rules.
- `schemas/` contains the versioned public wire contracts.
- `src/edge_delegate/contracts/` contains dependency-free Python contract types.
- `src/edge_delegate/ir/` owns parsing, canonicalization, and static validation.
- `src/edge_delegate/policy/` owns deterministic permission, privacy, approval, and risk logic.
- `src/edge_delegate/planner/` defines the interchangeable planner protocol.
- `src/edge_delegate/runtime/` coordinates validated execution, replay protection, and audit.
- `src/edge_delegate/simulator/` provides deterministic capabilities without physical hardware.
- `examples/` contains executable wire-format examples.
- `benchmarks/` and `tests/` keep model quality separate from software correctness.

## Next milestone

The next milestone is dataset v1, driven by the measured pilot failures:

1. Add multiple independent scenario groups per route across train, validation, and test.
2. Balance empty-step abstention routes against direct-action, multi-step, reference, and hybrid plans.
3. Add safe deny demonstrations while keeping prompt-injection and actuator attacks isolated.
4. Add policy/state counterfactuals, capability-set variation, multilingual utterances, and device-family holdouts.
5. Freeze the expanded evaluation sets, retrain, and require gains in static validity, routing, exact plans, and safety—not merely token loss.
6. Compare a stronger small checkpoint only after the same data and evaluation contract is stable, then export and benchmark the winner on declared edge targets.
