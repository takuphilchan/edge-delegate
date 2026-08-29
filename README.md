# Edge Delegate

Edge Delegate is a model-independent planning and safety runtime for constrained and embedded devices. It turns a candidate natural-language plan into a small, typed Plan IR, checks it against declared device capabilities, live state, permissions, approvals, privacy rules, and resource budgets, and only then permits execution.

The small model is not the security boundary and is not intended to be a general chatbot. It may propose a plan; deterministic code decides whether that plan is executable.

## Current status

Version `0.2.0` implements the deterministic vertical slice and the first measurable planner baseline:

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
- Parsing, static validity, execution, routing, exact-plan, calibration, and abstention metrics
- CLI demo, validation, dataset generation, and gold/model evaluation commands
- Unit, property, integration, regression, safety, hardware, and CI checks

Fine-tuning, external LLM handoff, embedded export, and hardware model benchmarks remain later milestones. The repository intentionally measures the prompt-only model before training it.

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

Then measure the unmodified FunctionGemma baseline after installing the planner extra and authenticating with Hugging Face:

```bash
edge-delegate evaluate \
  --dataset data/processed/pilot/test.jsonl \
  --planner functiongemma \
  --model-id google/functiongemma-270m-it \
  --output artifacts/evaluation/functiongemma-prompt-baseline.json
```

The gold run is a harness self-check, not a model-quality score. Fine-tuning should begin only after the FunctionGemma test and safety reports expose repeatable, trainable failure classes.

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

The next milestone is a measured real-model baseline followed by evidence-driven training:

1. Run the gated FunctionGemma checkpoint on test and isolated safety splits.
2. Review failures by route, Plan-IR shape, capability retrieval, arguments, and calibration.
3. Expand scenarios only for demonstrated gaps; add multilingual and device-family holdouts.
4. Compare Qwen3 0.6B as a stronger baseline or label-review assistant, never as an unchecked gold-label source.
5. Add a LoRA/QLoRA training pipeline and repeat the same frozen evaluation.
6. Export and benchmark the chosen checkpoint on declared edge targets.
