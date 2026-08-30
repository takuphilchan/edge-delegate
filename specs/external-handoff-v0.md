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

The `handoff.v0` data type and privacy-class checks exist, but version `0.3.0` does not construct
or transmit a handoff and does not call an external model. External and hybrid routes return an
explicit `external_required` coordinator status. Redaction, outbound policy enforcement, response
constraints, response validation, provenance, and timeouts are required before connector wiring.
