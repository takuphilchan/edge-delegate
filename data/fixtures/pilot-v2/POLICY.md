# Pilot labeling rules - provisional, not runtime changes

Owner approval: **pending**. Independent label review: **pending**.

This draft is a conversation starter for the local temperature-sensor/display fixture. There is
one configured sensor and display; requests are independent, with no conversation memory.
It is not a production use case, numeric device specification, or approved training policy.

## Choose the meaning first

- `read_temperature`: return the current Celsius reading; do not change the display.
- `display_number`: display one explicitly supplied number; do not read a sensor.
- `show_temperature`: read the temperature, then display that reading.
- `clarify`: ask for missing or conflicting information; invoke nothing.
- `deny`: unsupported request, or no actual positive device command; invoke nothing.

Proposed convention: "Show the temperature" means read-and-display; "Tell me the temperature"
means read only. "That sensor", "it", and "the previous number" require clarification without an
explicit binding, even with one installed sensor. **Please challenge this convention if it does
not match the intended product.** We have not silently changed the runtime to enforce it.

Only read-and-display-temperature is a supported compound. Refuse other multi-action requests
as a whole, including uploads, scheduling, rebooting, arithmetic, and unit conversion. Never
perform just the supported fragment. A positive command with an explicit prohibition, such as
"read temperature; do not display it", can still be a read. A purely negative or quoted command
does nothing. `deny` for a no-action request is a provisional encoding, not necessarily the best
future user-facing response.

## Numeric proposal

Finite decimal literals from -1000 to 1000, inclusive, with at most two fractional digits.
Optional signs and a leading decimal point are allowed; a final sentence period is punctuation.
Normalize negative zero to zero. Do not calculate, round, convert, or infer a missing value.

Number words, scientific notation, separators, out-of-range values, and excessive precision
are proposed **format clarification**, not semantic ambiguity. Those five pilot cases are
marked challenge cases. Current numeric extraction does not enforce every proposed restriction;
the pilot is not evidence that it does. This policy needs approval and separate implementation
tests before training on these expectations.

## Then check whether execution is allowed

Keep a clear intended task even when execution is blocked. Missing display permission or a
required capability means denied, with no calls. A stale snapshot means invalid_plan, with no
calls. The proposed action can still be read_temperature/display_number/show_temperature.
An unsupported upload request remains deny even if no sensor is installed.

For executable requests, compare the intended number or sensor result, ordered calls, returned
value, and final state. Initial screen values, sensor temperatures, and supplied numbers are
varied separately. An already-correct screen does not prove that the requested calls happened.

## How to review

1. Start with REVIEW.md, not the proposed answers. Record your task/parameters, allowed calls,
   expected state/value, and any policy objection for each case.
2. Then compare PROPOSED-ANSWERS.md. Keep disagreements; do not just replace your first answer.
3. Resolve the policy questions with the owner before accepting affected rows. Another authoring
   model is not an independent reviewer. No reviewer identity or approval has been fabricated.
4. Do not edit fingerprints manually or mark all rows accepted to bypass the gate. A later
   reviewed update must bind the complete context and expectations to the actual reviewer.

The draft contains 80 examples in 16 proposed semantic families from one AI-assisted authoring
batch. Family boundaries and label correctness are unverified. All sources are development-exposed:
train.jsonl is only the review format's development container, **not approved training data**.
Validation, test, and safety files are intentionally empty. Adversarial examples here are exposed
development cases, not the held-out adversarial suite. New independent test sources are still needed.

The source file is the reproducible authoring artifact. Assembly seed 0 describes deterministic
fixture assembly, not an asserted language-model sampling seed. The manifest also records this
policy document's SHA-256 for traceability; changing the policy requires a new reviewed version.
