# Dataset review workspace: implemented tooling

[Dataset-v2 proposal](dataset-v2.md) | [Runbook](../docs/development-runbook.md)

This contract describes the implemented review tools, not an approved dataset or release.
The task/numeric policy in the v2 proposal still needs owner and independent reviewer decisions.
Passing these checks does not make records eligible for training. Existing v0/v1 loaders reject
the draft record version deliberately.

## What the tools do

`edge-delegate-lab review-data` reads a workspace without loading a model, executing plans,
editing records, training, or freezing a test set. It checks:

- Existing request/context/plan contracts and static consistency.
- Independently specified local-display effects and expected-plan meaning.
- Record fingerprints, source provenance, review bindings, and split hashes.
- Declared ancestry and exact normalized request-text leakage between splits.
- Accepted review and minimum pilot coverage, unless explicitly inspecting a pending draft.

The effect oracle is a small hand-authored specification, not an execution of the compiler or
coordinator. Its inputs are the labeled task, initial state, expected status, and capability IDs.
It checks exact final state, final value, ordered capability calls, and forbidden calls. The
expected-plan checker separately checks arguments and read-result dependencies. This is not
a new transport-level argument audit or physical-device qualification.

## Files and identities

The directory contains `manifest.json`, `train.jsonl`, `validation.jsonl`, `test.jsonl`, and
`safety.jsonl`. All four split files must exist; they may be empty only in pending-draft mode.
No filenames or executable assertions are supplied by the manifest.

Manifest fields:

| Field | Required value/meaning |
| --- | --- |
| schema_version | edge-dataset-review.v1 |
| catalog | local-display.v1 |
| oracle | local-display-effects.v1 |
| label_policy | Nonempty version of the labeling policy being reviewed; must match each record |
| sources | Object mapping source IDs to entries described below |
| split_counts | Counts for train, validation, test, safety |
| split_sha256 | `dataset_fingerprint` of each complete split |

Pilot writers also include `policy_document_sha256`. The `review-data` file-level command checks
that hash against the UTF-8 text in POLICY.md, normalizing CRLF/CR to LF as the writer does.
A claimed hash must be valid and have a matching document, including with `--allow-pending`.
A policy file without its manifest binding is rejected. Older workspaces with neither retain
compatibility, but the report explicitly says `policy_document.status: not_provided`; they do
not acquire policy-integrity evidence. This check does not authenticate owner approval.
In-memory `validate_review_dataset` checks records/manifest only, not filesystem contents.

Each source entry records `family`, `contributor` alias, `rights` statement, and `exposure`:
fresh or development. Each source belongs to one derivation family. Related templates,
paraphrases, and counterfactuals must share that family; renaming them is not independence.
Test/safety records cannot use development-exposed sources. Source labels are recorded evidence,
not something the software can independently authenticate.

## Record fields

Keep the existing canonical fields: record/request IDs, request, capabilities, state, policy,
evaluation time, expected task, expected plan, expected outcome, expected effects, and metadata.
Use `schema_version: edge-delegate-dataset.v2-draft`.

Required metadata retains `scenario_group`, `template_id`, `paraphrase_cluster`, `scenario_family`,
and `device_family`. Add:

| Field | Meaning |
| --- | --- |
| category | supported, clarify, deny, restricted, adversarial, or challenge |
| catalog_version, label_policy, oracle_version | Match the manifest |
| provenance | Structured entry below, not the legacy free-text provenance |
| sources_sha256 | Fingerprint of the object containing this record's referenced source entries |
| review | Review ledger entry below |
| restriction_reason | Required explanation when an intended action has an expected denied plan |

Provenance has `source_ids` (nonempty list), `parent_ids` (list), and `method` (human or generated).
Generated entries also require a nonempty `generator` version and integer `seed`. Parents must
resolve to records in the workspace, share the family and split, and retain all source ancestry.
Cycles fail. External roots belong in the source registry, not unresolved parent IDs.

Review fields:

- `status`: pending, accepted, quarantined, or rejected.
- `author`: contributor alias, plus `author_decision` equal to the expected task.
- `rationale`: nonempty labeling explanation.
- Accepted entries additionally require a different `reviewer` alias, a `reviewer_decision`
  equal to the expected task, and `reviewed_payload_sha256`.

Accepted entries represent resolved agreement. Keep disagreements and their adjudication history
in the review process; do not overwrite an earlier reviewer decision to manufacture agreement.
Pending mode still verifies accepted entries fully; it does not bypass invalid claimed approvals.

## Fingerprints and review order

Use the installed Python helpers in `edge_delegate.data.fingerprint` and
`edge_delegate.data.review`; no repository-internal path imports are needed.

1. Collect the request, context, intended task, independent expected effects, and source entries.
2. Set `sources_sha256 = content_fingerprint({source_id: source_entry, ...})` for referenced sources.
3. Obtain independent review of the complete payload, including context and effects. Only then
   record `reviewed_payload_sha256 = review_payload_fingerprint(record)` and accepted status.
4. Calculate `content_sha256 = content_fingerprint(record_without_content_sha256)`.
5. Calculate each split's `dataset_fingerprint(records)` and count for the manifest.

Changing request text, context, effects, provenance, policy versions, or source entries invalidates
the relevant fingerprints. Review hashes are integrity checks, not identity signatures or proof
that a person actually reviewed anything. Do not auto-approve drafts by computing a hash.

## Pilot checks versus release gates

By default, every row must have accepted review; all splits must be nonempty. Each functional
split must cover all five task decisions and the supported, clarify, deny, and restricted
categories. Safety must include adversarial cases. The report gives counts, family counts,
largest-family size, and missing coverage.

These are minimum structural pilot checks, not the proposed 4,000+200 collection floors.
`--allow-pending` permits incomplete coverage/review so authors can inspect a draft; malformed
records, inconsistent expectations, stale claimed approvals, or lineage leaks still fail.
The report always states `qualified: false` and `training_eligible: false`.

Use `--format text` for readable counts and missing coverage; JSON remains the default. A
structurally valid pending draft is not a completed independent review.

Remaining gates include owner-approved task/numeric rules, independent semantic label review,
near-duplicate and source-family adjudication, full category/mechanism coverage, append-only
correction history, export round trips, and an approved freeze manifest. No training or export
command consumes this draft schema yet.

## Optional task-decision diagnostics

`BoundedPlanner` now exposes per-call `plan_with_diagnostics` and
`plan_many_with_diagnostics` alongside unchanged `plan`/`plan_many` return contracts. An observation
contains a checked task decision plus a plan or error. It cannot authorize execution.

Diagnostic evaluation records a decision fingerprint and equality with `expected_task` separately
from plan validity and simulated effects. It does not persist raw parameters by default. These
are plugin-checked decisions before compilation: a plugin may already have applied numeric
extraction or clarification rules, so this is not raw model-output scoring.

Parser failures and planners without this optional interface are explicitly unassessed for
decision equality; they do not become correct refusals. Always read assessed/unassessed counts
alongside accuracy. Existing effect/status metrics retain their compatibility meaning.
The audit flags `wrong_intent_masked_by_runtime` when effects/status pass but a captured task
decision is wrong. Both built-in bounded plugins use this shared instrumentation.
