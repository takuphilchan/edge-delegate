# Capability Card v0

Status: implemented (`capability-card.v0`)

## Purpose

Describe what a device or host can actually do without teaching the model undocumented functions.

## Wire contents

- Stable capability identifier and version
- Human and machine-readable description
- Typed inputs and outputs
- Preconditions and side effects
- Permission and approval requirements
- Latency, energy, memory, and connectivity estimates
- Privacy classification

Value specifications support `any`, `null`, `boolean`, `integer`, `number`, `string`, `array`, and `object`, plus optional enum and numeric bounds. The static checker verifies literal values and referenced output types before execution. Runtime adapters validate inputs and outputs again as defense in depth. Idempotency belongs to individual Plan-IR steps because it identifies a particular invocation, not a capability definition.
