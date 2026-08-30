# Evaluation Protocol

Status: deterministic evaluator, real-model diagnostics, and pilot adapter measurement implemented

## Evaluation layers

1. Contract validity: outputs parse and satisfy versioned schemas.
2. Static correctness: all referenced capabilities, types, permissions, and preconditions are valid.
3. Simulated execution: the plan succeeds in a deterministic world model.
4. Routing quality: local, hybrid, external, clarify, defer, and deny choices match labeled expectations.
5. Safety: adversarial requests do not cross policy or actuator boundaries.
6. Calibration: confidence predicts actual plan success and triggers abstention appropriately.
7. Hardware: latency, peak memory, package size, energy proxy, and cold-start cost meet a declared device profile.

Calibration metrics include only parse-valid typed plans because malformed output has no
trustworthy Plan-IR confidence. Reports record the calibration-eligible case count and use
`null`, not a synthetic perfect score, when that count is zero.

## Benchmark discipline

Templates, device families, and paraphrase clusters are assigned together so held-out results do not measure paraphrase memorization. Safety-tagged groups are isolated. Every dataset build carries record, split, and complete-dataset fingerprints plus a source manifest. Gold labels come from reviewed scenarios and deterministic execution, never from an unchecked model.

## Current automated baseline

The repository runs contract/schema, malformed-output, property, integration, regression, policy-boundary, idempotency, audit-minimization, retrieval, strict adapter, grouped-data, evaluation-harness, and explicit CUDA visibility tests. The gold self-check must score 100% and only proves the harness is internally consistent.

The measured six-route integration smoke on the prompt-only checkpoint produced no parseable plans. The first pilot LoRA produced parseable, request-bound Plan IR for all six cases, but only half were statically valid, half selected the expected route, and one was exact. These six cases validate the model/software boundary; they are not a model-quality benchmark. Multilingual behavior, broader device families, calibrated confidence, energy measurement, and edge deployment benchmarks remain pending.
