# Pilot audit: findings before expansion

27 September 2026. **Author-side AI-assisted audit, not independent review or label acceptance.**

Read the blank REVIEW.md worksheet first if you intend to contribute an independent first pass.
This document discusses the proposed labels and can bias that pass.

## Result

I inspected all 80 source requests and their grouped rationales against the fixture policy.
No definite task-label correction was identified under the recommended rules. This is an
author-side judgment, not evidence that an independent reviewer agrees. In particular, approval
of a convention such as "show" versus "tell" is not proof of general language understanding.

Structural checks pass for all 80 draft records. The existing all-case gold-plan simulator test
also passes: specified effects agree with execution of the expected plans. Neither test loads
the trained model or scores its language understanding. Accepted independent reviews remain
**0/80**; validation, test, and safety splits remain empty by design.

The owner has now selected the [recommended simulator behavior](OWNER-DECISION.md). Existing
fingerprinted snapshots are preserved; revised policy/labels will need a new version.

## Concrete findings and disposition

| Finding | Evidence | Disposition |
| --- | --- | --- |
| Policy text could change without the review command noticing | Manifest recorded a document fingerprint, but the command checked only record/split identities | Fixed: verify the bound POLICY.md, including pending-draft checks; missing/mismatched documents fail |
| Numeric range and precision are not enforced by the current extractor | pilot-054 (`Display 1001.`) extracts 1001; pilot-055 (`Display 1.234.`) extracts 1.234 | Do not train these as though parser support exists. Implement/version the numeric contract and test both plugins first |
| Format clarification is not yet a distinct machine-readable subtype | pilot-051 through pilot-055 use challenge category and rationale text; generated clarification reason remains ambiguous_request | Add a format_clarification subtype in the revised record/diagnostic contract; keep it separate from genuine semantic ambiguity |
| Family names do not establish independent sources | All 16 groups were authored in one AI-assisted batch; related numeric and negation groups overlap semantically | Keep all current cases development-exposed. Review/merge ancestry before expansion; never divide these groups into an allegedly fresh test set |
| Independent label review has not happened | Every review ledger entry is pending, no reviewer identified | Leave approvals untouched. Obtain an actual separate first pass and preserve disagreements |
| Rights statements remain provisional | Source registry says distribution terms require owner review | Resolve rights/provenance for collected material before a dataset release; MIT code licensing alone is not that decision |
| No independent evaluation sources exist here | 80 train-container rows; zero validation/test/safety rows | Commission separately authored held-out sources before candidate selection; do not repurpose this exposed pilot |

The parser probe is not a model prediction: it establishes numeric extraction behavior only.
The first three format cases (number words, scientific notation, comma separator) return no value
from the current extractor. That does not prove the complete planner will choose clarify.

## Coverage inspected

Each row below covers five records. "Consistent" means the proposed task fits the stated fixture
rules on this author-side pass; all five records still need independent review.

| Records | Family | Author-side disposition |
| --- | --- | --- |
| 001-005 | Current reading | Consistent: return sensor reading, no display update |
| 006-010 | Measured display | Consistent: read then display; 010 still requires calls when the screen is already correct |
| 011-015 | Explicit positive number | Consistent: literal display, no sensor read; 014 still requires its requested write |
| 016-020 | Signed/boundary literals | Consistent with chosen decimal grammar; exercise negative zero and inclusive boundaries in implementation tests |
| 021-025 | Unbound references | Consistent only with the explicit no-memory/conservative-reference policy |
| 026-030 | Missing parameter | Consistent: no supplied number means clarify, not infer from state |
| 031-035 | Unresolved choice/contradiction | Consistent: clarify without invoking anything |
| 036-040 | Outside catalog | Consistent: unsupported communication, explanation, fan control, conversion, arithmetic |
| 041-045 | Unsupported compound | Consistent: refuse the entire unsupported compound/repeated action |
| 046-050 | No action requested | Consistent with provisional deny-as-non-action encoding; review user-facing wording separately |
| 051-055 | Numeric format | Policy expectations are clear, but range/precision implementation and subtype reporting are incomplete |
| 056-060 | Authority/hidden actions | Consistent: unsupported or bypass actions must not be executed |
| 061-065 | Permission counterfactual | Consistent: preserve intent; block display effects when permission is absent |
| 066-070 | Availability counterfactual | Consistent: missing capabilities block execution; 070 must remain unsupported intent rather than a blocked read |
| 071-075 | Freshness counterfactual | Consistent: stale snapshot blocks execution without changing intent |
| 076-080 | Positive/negative contrast | Consistent: positive reads with display prohibition remain reads; purely negative/quoted actions do nothing |

Counts: 28 supported, 15 semantic clarification, 18 deny, 9 restricted-context, 5 adversarial,
and 5 numeric-challenge cases. Five adversarial examples are development material, not a safety
qualification suite. There are no independent contributors demonstrated by this pilot.

## Next revision: acceptance checklist

1. Preserve this source and the owner's decision. Assign a new policy/version for corrected
   metadata and numeric behavior rather than editing existing fingerprints in place.
2. Specify and test the shared numeric grammar before training: boundaries, precision, trailing
   punctuation, signs, negative zero, number roles, scientific notation, separators, and multiple
   literals. Do not implement arbitrary arithmetic or change old artifact semantics silently.
3. Have an actual independent reviewer complete REVIEW.md. Compare only afterwards with the
   proposed answers; keep original decisions, disagreements, and adjudication history.
4. Record real reviewer evidence bound to context and effects in a new reviewed workspace.
   Never mark rows accepted merely because the simulator or author-side audit agrees.
5. Collect broader independent source families, rights records, and held-out examples. Freeze
   those labels and family assignments before tuning a new model.

No training, dataset promotion, runtime permission changes, or physical-device actions were
performed by this audit.
