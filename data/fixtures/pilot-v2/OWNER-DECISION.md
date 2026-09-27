# Owner decision: simulator-pilot behavior

Recorded: 27 September 2026. Scope: the local sensor/display research fixture only.

The project owner asked to proceed with the recommended approach after the assistant presented
the pilot rules for approval. This records that direction; it does **not** invent a reviewer
identity, independent review, individual label acceptance, training approval, or hardware support.

## Agreed direction

- Requests are independent; there is no conversation memory.
- Use the configured local sensor/display. Unbound references require clarification rather
  than guessing from a previous request or a saved screen value.
- "Show the temperature" means read the sensor and display that result; "tell me the
  temperature" means return the reading without changing the display.
- Only read-temperature, display-an-explicit-number, and read-then-display-temperature are
  supported actions. Unsupported compounds execute nothing, including their supported fragment.
- For the next pilot policy implementation, accept finite decimal literals in [-1000, 1000]
  with at most two fractional digits. Optional signs and leading decimal points are allowed;
  sentence-final periods are punctuation. Normalize negative zero. Do not round, calculate,
  convert, or infer missing numbers. Other numeric formats request clarification.
- Preserve task meaning when permissions, available capabilities, or freshness block execution.
  Authorization remains deterministic runtime work, not a model decision to override.
- Non-action/quoted-only/negated-only requests invoke nothing. The existing five-decision
  interface represents them as deny; this does not introduce a new user-facing no-op response.

## What this decision does not change

The existing [POLICY.md](POLICY.md), source JSON, generated worksheet, answers, and manifest
are historical draft snapshots and are intentionally not rewritten. Their pending flags describe
the state when they were assembled. The policy snapshot fingerprint is:

`61d5b6d3b404f9de2c7cc2df9a7d3189a3e6cfbfa9f2020112840c8c89d9d41c`

This decision records intended behavior for the next revision; it is not a signed attestation
and is not consumed by a training loader. The current numeric extractor does not enforce the
approved range/precision. Preserve compatibility with existing artifacts until a versioned
implementation and tests exist. Do not silently change deployed behavior or rehash old labels.

All 80 labels still need actual independent review and disagreement resolution. Contributor
rights, family independence, broader collection, separate test authorship, training, and a
release freeze are not approved merely by approving these behavior rules.

Next: use [the author-side audit](AUTHOR-AUDIT.md) to prepare the revision. A reviewer should
complete the existing REVIEW.md worksheet **before** reading the audit or proposed answers.
