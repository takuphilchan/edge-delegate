# External Handoff v0

Status: contract implemented; connector wiring deferred

## Purpose

Define the minimal, policy-filtered request that can be sent to an optional external language model when local processing is insufficient.

## Wire contents

- Reason for escalation
- Redacted task context
- Explicit questions for the external model
- Data classifications included and removed
- Expiry

The `handoff.v0` contract and privacy-class checks exist, but `0.1.0` intentionally does not transmit data or call an external model. External and hybrid routes return an explicit `external_required` coordinator status. Response constraints and local verification will be added before connector wiring.
