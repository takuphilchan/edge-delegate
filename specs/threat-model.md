# Threat Model

Status: scaffold

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

