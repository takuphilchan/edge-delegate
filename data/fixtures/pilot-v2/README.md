# Local-display pilot: start here

This versioned source contains **80 AI-assisted examples, all pending independent review**.
It adds no model weights and changes no runtime permissions or numeric parsing.

Update, 27 September: the owner selected the recommended simulator rules. See
[the decision record](OWNER-DECISION.md). Existing pending snapshots are preserved rather than
retroactively approved. [The author-side audit](AUTHOR-AUDIT.md) lists implementation gaps and
coverage findings; read it only after a first independent worksheet pass.

Numeric implementation update: both bounded plugins now offer the opt-in `decimal.v1` policy,
including range/precision checks and boundary tests. Existing artifacts/settings remain legacy
by default. See [the numeric-policy guide](../../../docs/model-plugins-and-compute.md#versioned-numeric-policy-for-bounded-tasks).
The historical POLICY.md, author audit, source labels, and pending review ledger remain unchanged;
this implementation does not approve them or add a new training export.

Read [the provisional policy](POLICY.md). The compact [source](source.json) owns the draft requests,
grouping, and proposed labels. Do not use the source or answer key for your first independent label pass.

From the repository root in the activated WSL environment:

```bash
python -m edge_delegate_lab.pilot \
  --source data/fixtures/pilot-v2/source.json \
  --output data/review/pilot-v2

edge-delegate-lab review-data --directory data/review/pilot-v2 --allow-pending
```

Add `--format text` for a readable progress summary. The check now verifies the POLICY.md
fingerprint as well as records and splits. A changed policy needs a new reviewed version;
do not alter its hash just to silence a failed check.

The assembly command refuses an existing output directory to preserve reviewer edits. If this
workspace already exists, open its REVIEW.md instead of rebuilding it. Use a new versioned path
for a deliberate revised draft; do not delete an existing review to make the command pass.

Outputs:

- `REVIEW.md`: requests, context, initial state, and blank answers; read this first.
- `PROPOSED-ANSWERS.md`: proposed labels, plan arguments, effects, and rationale; compare afterwards.
- `POLICY.md`: snapshot of the provisional rules.
- `train.jsonl` and `manifest.json`: canonical exposed draft records and provenance.
- Empty `validation.jsonl`, `test.jsonl`, and `safety.jsonl`: no invented held-out evidence.
- `draft-check.json`: structural check report, not semantic approval.

The default command, without `--allow-pending`, **must fail** until accepted independent review
and coverage requirements are met. The training loader also rejects this draft schema.
Keep annotations private as appropriate; generated review workspaces are ignored by Git. The
source recipe and instructions remain versioned.

Next: an independent reviewer fills the worksheet, the owner settles disputed task/numeric
rules, and a revised version records adjudication. Only then expand collection. This pilot
does not replace the planned independent test and safety sets or authorize retraining.
