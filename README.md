# Edge Delegate

Working title for a model-assisted planning system that compiles natural-language requests into small, typed execution plans for constrained and embedded devices.

> Status: repository scaffold only. Runtime, training, and model logic will be wired in the next phase.

## Intended outcome

The system should decide whether a request can be handled locally, needs a hybrid local/external plan, should be handed to a larger language model, requires clarification or approval, must be deferred, or must be denied by policy.

The small model is not intended to be a general chatbot. Its differentiator is producing a verifiable intermediate representation (IR) against the device's declared capabilities, current state, privacy policy, and resource limits.

## Planned boundaries

- `specs/` defines behavior before implementation.
- `schemas/` contains versioned wire contracts.
- `src/edge_delegate/contracts/` will expose typed Python contracts.
- `src/edge_delegate/ir/` will parse and statically check plans.
- `src/edge_delegate/policy/` will enforce privacy, approval, and risk rules outside the model.
- `src/edge_delegate/planner/` will contain interchangeable small-model adapters.
- `src/edge_delegate/runtime/` will coordinate validation and execution.
- `src/edge_delegate/simulator/` will make plans testable without physical hardware.
- `src/edge_delegate/connectors/` will isolate optional external-LLM access.
- `src/edge_delegate/data/` will own dataset generation and provenance.
- `src/edge_delegate/evaluation/` will measure correctness, safety, calibration, and hardware cost.
- `benchmarks/` and `tests/` keep model quality separate from software correctness.

## Candidate model strategy

The configuration scaffold includes FunctionGemma 270M as the first constrained planner candidate and Qwen3 0.6B as a stronger comparison/teacher candidate. The contracts are intentionally model-independent so either can be replaced after evidence from the benchmark.

## Local environment

The existing WSL environment can be activated with:

```bash
source /home/phil/.venvs/edge-model/bin/activate
```

Dependency installation is intentionally deferred until the contracts and first vertical slice are agreed.

## Next phase

Wire one thin vertical slice: capability card -> request -> plan IR -> static check -> simulated execution. Only after that passes deterministic tests should model prompting, fine-tuning, quantization, or external-LLM handoff be added.

