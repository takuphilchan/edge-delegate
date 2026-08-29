# Threat Model

Status: initial deterministic controls implemented (`0.1.0`)

## Initial threats

- Prompt injection through user text, sensor text, retrieved capability descriptions, or external-model output
- Hallucinated capability identifiers or arguments
- Unauthorized actuator use
- Leakage of secrets, personal data, or unnecessary sensor context
- Replay, duplicate execution, and retry amplification
- Malicious or stale capability cards
- Resource exhaustion on constrained devices
- Unsafe behavior during network loss or partial execution

## Required controls

Typed contracts, allowlists, static validation, explicit approval gates, bounded execution, idempotency keys, provenance, least-data handoff, and fail-closed policy checks.

## Implemented controls

- Strict versioned parsing, unknown-field rejection, size/depth limits, and duplicate-key rejection
- Declared-capability allowlisting and typed argument/output validation
- Request-, capability-, plan-hash-, and expiry-bound approvals
- Resource budgets, state freshness, permissions, network checks, and preconditions
- Mandatory idempotency for write and physical effects
- Privacy-minimal audit events that exclude request text and step arguments
- No external transmission path in the current release

## Outstanding before model or connector release

- Adversarial evaluation of retrieved capability text and model output
- Handoff redaction, response constraints, and response validation
- Persistent idempotency and audit stores with retention policy
- Hardware timeout/cancellation and compensation semantics
- Signed capability-card provenance and update rollback
