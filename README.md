# Edge Delegate

Edge Delegate is a model-independent planning and safety runtime for constrained and embedded devices. It turns a candidate natural-language plan into a small, typed Plan IR, checks it against declared device capabilities, live state, permissions, approvals, privacy rules, and resource budgets, and only then permits execution.

The small model is not the security boundary and is not intended to be a general chatbot. It may propose a plan; deterministic code decides whether that plan is executable.

## Current status

Version `0.1.0` implements the first deterministic vertical slice:

- Strict versioned Python contracts and matching JSON Schemas
- Bounded Plan-IR JSON parsing with duplicate-key and non-finite-number rejection
- Stable canonical serialization and SHA-256 plan fingerprints
- Capability, argument, prior-step reference, precondition, and route checks
- Permission, exact-plan approval, connectivity, freshness, memory, latency, energy, and timeout checks
- Mandatory idempotency for write and physical capabilities
- Deterministic device simulation with sensors and state-changing capabilities
- Sequential local execution with output-reference resolution and replay protection
- Fail-closed request coordination and privacy-minimal audit events
- CLI demo and contract-only validation command
- Unit, property, integration, regression, safety, hardware, and CI checks

Model inference, fine-tuning, external LLM handoff, dataset generation, and embedded export remain explicit later milestones.

## Environment setup

The existing WSL environment can be used directly:

```bash
cd /mnt/d/project/edge-delegate
source /home/phil/.venvs/edge-model/bin/activate
python -m pip install -e ".[dev]"
```

The runtime itself has no third-party Python dependencies. The `dev` extra installs only testing, schema-validation, property-testing, and lint tooling.

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

The next milestone is a measured planner baseline, not immediate fine-tuning:

1. Build simulator-derived gold and held-out planning cases.
2. Implement capability retrieval and a prompt-only FunctionGemma adapter.
3. Measure valid-plan rate, execution success, route accuracy, safety failures, calibration, latency, and memory.
4. Compare with Qwen3 0.6B as a stronger baseline/teacher.
5. Fine-tune only after the error analysis shows which failures data can actually fix.
