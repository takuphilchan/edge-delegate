# Evaluation Protocol

Status: deterministic software baseline implemented; model benchmark pending

## Evaluation layers

1. Contract validity: outputs parse and satisfy versioned schemas.
2. Static correctness: all referenced capabilities, types, permissions, and preconditions are valid.
3. Simulated execution: the plan succeeds in a deterministic world model.
4. Routing quality: local, hybrid, external, clarify, defer, and deny choices match labeled expectations.
5. Safety: adversarial requests do not cross policy or actuator boundaries.
6. Calibration: confidence predicts actual plan success and triggers abstention appropriately.
7. Hardware: latency, peak memory, package size, energy proxy, and cold-start cost meet a declared device profile.

## Benchmark discipline

Templates, device families, and paraphrase clusters must be split before generation so held-out results do not measure memorization. Every dataset build will carry a source manifest and content fingerprint.

## Current automated baseline

The repository runs contract/schema, malformed-output, property, integration, regression, policy-boundary, idempotency, audit-minimization, and explicit CUDA visibility tests. Model-quality, calibration, multilingual, latency, memory, and energy benchmarks remain pending until the first planner adapter and dataset manifest exist.
