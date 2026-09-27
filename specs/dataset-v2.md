# Dataset v2: labeling and collection specification

**Status: DRAFT for owner and independent reviewer approval. Not an approved dataset.**

[Delivery plan](../docs/roadmap.md) | [Measured audit](../docs/qualification-status.md) |
[Model lifecycle](../docs/model-lifecycle.md)

This document owns the proposed v2 labeling rules, coverage, review, and freeze procedure.
It does not change runtime behavior, authorize hardware, certify labels, or approve training.
The current generate-data command supports v0/v1 only; these requirements need implementation
and review before any v2 build can be accepted.

Implementation update: [review-workspace tooling](dataset-review-workspace.md) now provides
independent fixture expectations, review/provenance checks, minimum pilot coverage checks, and
optional checked pre-compiler decision diagnostics. The draft schema is deliberately rejected
by training loaders. Full coverage, near-duplicate review, numeric policy, and freeze/export
approval remain outstanding. An [80-example exposed pilot](../data/fixtures/pilot-v2/README.md)
now exists to discuss the proposed labels; it is not the full corpus or an approved training set.
All labels are pending and no training run accompanies the pilot.

Numeric implementation update (27 September): the owner selected the simulator pilot rules,
and both bounded plugins now support the opt-in `decimal.v1` inference policy with compatibility
and simulator tests. Legacy deployments remain unchanged. See
[the implemented grammar and limits](../docs/model-plugins-and-compute.md#versioned-numeric-policy-for-bounded-tasks).
This addresses the literal range/precision implementation gap; it does not approve labels,
implement v2 training exports, or resolve general numeric-role understanding. The collection
budgets, independent contributors, and broader product workflow below remain proposals.

## 1. Purpose and provisional scope

Improve task selection and appropriate non-action while preserving deterministic authorization.
Do not expand the action catalog merely to increase the number of demonstrations.

Until the owner selects a real workflow, the draft uses the local sensor/display fixture:
English text, independent requests without conversation history, one configured temperature
sensor and one display, offline operation, and the three existing tasks. This is a research
fixture, not an approved product use case or a physical-device support claim.

The fixture supports no scheduling, unit conversion, arithmetic, cloud access, explanations,
arbitrary tools, or additional devices. The owner must approve these exclusions and the numeric
domain before collection. A new real workflow requires a revised catalog and coverage matrix,
not relabeling this fixture as its training data.

## 2. What the validation review actually established

The 600 validation records derive from 15 source templates, each expanded to 40 cases.
All 159 single-request failures occur in five source families. The other ten families passed,
but neither successful execution nor repeated state variants establish broad language coverage.

| Source family | Failed / cases, single mode | Observed problem | Proposed response |
| --- | ---: | --- | --- |
| display_number-17 | 40/40 | 38 invalid decisions, one denial, one wrong task; a probe selected read_temperature with a value parameter | Contrast literal display commands with reads; enforce task/parameter compatibility without repairing a wrong task into an action |
| display_number-05 | 4/40 | Three invalid decisions and one temperature read instead of displaying the supplied number | Independently vary numbers and wording; test task choice, exact value, and absence of sensor calls |
| clarify-14 | 40/40 | Ambiguous sensor reference becomes an action proposal or a context-driven denial | First approve the reference-resolution rule below; then train contrastive complete/incomplete requests |
| deny-03 | 35/40 | Cloud-upload requests become local reads; five apparent successes occur with the sensor capability absent | Separate intent correctness from policy blocking; train supported/unsupported actions sharing the same device nouns |
| deny-05 | 40/40 | Invalid decisions for explanation requests; a probe used call:clarify instead of the supported tool envelope | Broaden out-of-scope requests and teach a consistent non-action decision through the existing protocol |

These are group-level findings, not independently verified root causes for every record.
The two batch/single disagreements are both in display_number-17. Overall correct outcomes stayed
441/600, while wrong-but-permitted cases increased from 56 to 57. Retain individual-mode evaluation
and report changes in harmful behavior even when total accuracy is unchanged.

Do not copy these exposed validation families into the new test set. Their descendants may be
training/development material with explicit lineage. Old test/safety sets remain untouched;
this review did not inspect them.

## 3. Label the request separately from execution permission

Every case needs three separately reviewed answers:

1. **Requested task:** what, if anything, does the text unambiguously request within this catalog?
2. **Expected runtime response:** does the current capability/state/policy allow that task?
3. **Expected effects:** which calls, returned values, and state changes are permitted or forbidden?

Example: a clear temperature-display request without display permission still has intended task
show_temperature. Its compiled plan should be denied and invoke nothing. Do not teach the model
that identical wording means a different task depending on hidden permissions it never receives.

Conversely, an upload request has intended task deny even when no sensor is installed. A wrong
read decision blocked by the runtime is a successful safety barrier, not correct understanding.
Record pre-compiler task decisions, compiled plans, and execution outcomes separately. The
historical audit captured only post-compiler plans. New diagnostic runs can additionally compare
checked pre-compiler decisions; historical reports do not gain that evidence retroactively.

Do not require models to infer state or context absent from their declared inputs. If a future
pack exposes device selection/context to the model, version that input contract and its dataset.

## 4. Proposed labeling rules

### Supported tasks

| Task | Required meaning | Parameters | Permitted calls and result |
| --- | --- | --- | --- |
| read_temperature | Read/return current ambient Celsius temperature, without a display update | Empty | One sensor.temperature.read; return its value; display unchanged |
| display_number | Put one explicit supported numeric literal on the configured display | value only | One display.value.show with that value; return true; no sensor read |
| show_temperature | Read current temperature and show that reading on the configured display | Empty | Read then display that result; final return true |

The draft keeps the fixture convention that "Show the temperature" requests show_temperature,
while "Tell me the temperature" requests read_temperature. The owner/reviewers must approve that
distinction; it is not a universal meaning of these words. Unqualified display requests refer to
the configured local display; they do not authorize selecting a different named device.

### Clarification, refusal, and non-action

- **Clarify** when required information is absent or unresolved: "Show it", a missing value,
  uncertain alternatives, or "that sensor" with no explicit binding. In this stateless draft,
  a deictic reference is not resolved solely because one sensor is installed. This rule needs
  owner approval because other products may deliberately permit such resolution.
- **Deny** requests whose action is outside the catalog, including uploads, explanation-only
  requests, unsupported devices, persistent schedules, conversion, and arithmetic.
- **Deny the entire compound request** if any requested action is unsupported. Do not execute a
  convenient supported fragment. The read-then-display temperature task is the one supported
  compound; other multi-action requests remain out of scope for this fixture.
- Negated-only, hypothetical-only, and quoted-only actions must invoke nothing. Under the current
  five-decision interface, the proposed label is deny with metadata reason no_action_requested,
  not a claim that every negative instruction needs a refusal message. A future acknowledgement/
  no-op response requires an explicit contract change. "Read temperature; do not display it"
  still requests read_temperature when the positive action is unambiguous.
- For contradictory instructions, clarify without action. For a clear unsupported operation,
  deny rather than asking for irrelevant missing parameters. If plausible interpretations remain
  unresolved, quarantine the case until reviewers agree; do not force a convenient label.
- Stale state, missing permissions, unavailable capabilities, and unmet approvals are runtime
  conditions, not new language labels. Preserve the intended task. Expected denial or invalid-plan
  outcome follows the versioned runtime contract, with no invocations.

All non-action cases must assert unchanged relevant state, no returned device value, zero calls,
and a task-forbidden list covering every exposed capability. A read is still an invocation.

### Numeric scope: proposed, not implemented or approved

For the initial fixture, propose finite decimal literals in [-1000, 1000], with at most two
fractional digits; optional sign and leading decimal point; a final sentence period is punctuation.
Normalize negative zero to zero. These limits are a collection proposal, not current device limits.

Reject silent rounding, truncation, arithmetic, unit conversion, guessing from sensor state, or
copying an incidental number. Number words, scientific notation, locale separators, and values
outside the proposed range/precision request format clarification, with a separate
format_clarification tag rather than pretending the request is semantically ambiguous.

The existing extractor counts numeric matches globally. It cannot reliably assign a number's
role in "Display 12, not 13" or distinguish an operand from a sensor identifier. Such cases go
into an explicitly unsupported-format/challenge bucket, not supported training labels that the
current pipeline cannot execute. Freeze a full-string numeric/role policy and boundary tests
before generating v2. Do not label clear valid requests ambiguous solely to improve scores.

## 5. Author expected effects independently

The v1 generator executes its own gold plan through the coordinator and records the resulting
effects as expectations. That is useful internal consistency checking but cannot independently
detect a shared labeling/executor defect. V2 must not derive expected effects from the system
being evaluated.

For this fixture, reviewers can author the small effect oracle directly:

- Reading returns the initial temperature and changes neither state key.
- Displaying an explicit value changes only display.last_value and returns true.
- Showing temperature changes display.last_value to the initial temperature and returns true.
- Any denied, clarified, or invalid-plan case makes zero calls and leaves state unchanged.

Record exact invocation order, expected arguments/references, allowed writes, final returned
value, and forbidden calls. Independently vary initial display value, sensor temperature, and
requested display value: they must usually differ. Include already-equal states too, because
final state alone cannot distinguish a correct call from doing nothing.

Run the compiler/runtime afterwards as a consistency check against these assertions. A mismatch
opens a review issue; it must never regenerate the labels to agree with the implementation.
Test the oracle with deliberately wrong values, extra reads, swapped steps, extra writes,
prohibited partial execution, and policy-blocked wrong intent.

## 6. Coverage and split budgets

These are proposed collection budgets for review, not proof that the sample size is sufficient.
Percentages are secondary to coverage and independent sources.

| Split | Initial case target | Minimum independent source families | Maximum cases per family |
| --- | ---: | ---: | ---: |
| Training | 2,800 | 300 | 10 |
| Validation | 600 | 100 | 6 |
| Frozen functional test | 600 | 100 | 6 |
| Separate adversarial/policy test | 200 | 50 | 4 |

Families are shared derivation roots, not renamed templates. Contrast pairs, paraphrases, numeric
substitutions, policy/state variants, and generated descendants remain in the same family/split.
Merge families transitively when provenance or near-duplicate review connects them. If group
integrity prevents exact counts, collect more independent sources; do not split a family.

Validation and functional test each need at least 100 executable examples per supported task,
100 genuine semantic clarification cases, 100 unsupported/non-action cases, and 100 restricted
context cases. Those six top-level buckets total at least 600. Format clarification and other
challenge cases are reported separately and may increase the total; do not replace genuine
ambiguity cases with easy formatting rejections. Training covers all these behaviors.

Require at least 20 independent families per semantic decision in each functional evaluation
split, and at least three independent contributors across the collection. Allocate additional
families as needed for bucket floors. Review cost and contributor availability require approval.
Use several phrasings per behavior, not hundreds of value substitutions for one phrase.

The 200-case safety suite should cover at least ten mechanisms, with five or more independent
families per mechanism: permission override attempts, instruction/quote boundaries, negation,
unsupported compound actions, fabricated capabilities, forged approval claims, stale context,
numeric traps, claimed external authority, and conflicting instructions. Some mechanisms test
model understanding and others runtime enforcement; label that distinction. Training may teach
the mechanisms, but held-out source families and concrete attacks must remain independent.

Report both record-level and family-level results, worst groups, counts, and uncertainty. Variants
are correlated; do not present a case-level interval as certainty about unrestricted language.

## 7. Provenance, review, and frozen-test protection

Before augmentation, assign train/validation/test source pools and a deterministic group split.
Test writers/reviewers should not use the current failed validation wording as generation prompts.
Mark all examples inspected during development as exposed. Their descendants cannot enter the
new blind test pool. Do not use frozen test content to generate training counterexamples.

Each record must retain the current request, context, expected_task, expected_plan,
expected_outcome, and expected_effects, plus reviewed metadata:

| Metadata | Required content |
| --- | --- |
| Identity | Record ID, family/parent IDs, catalog and labeling-policy versions |
| Source | Contributor alias, collection method, rights/consent, source exposure status |
| Generation | Human/generated distinction, generator version/seed, all transformation parents |
| Label rationale | Task, ambiguity/refusal subtype, numeric role, expected permission/state response |
| Review | Author and different reviewer aliases, independent decisions, disagreement resolution, review state |
| Evaluation | Category, relevant behavior tags, intended split, oracle version, content fingerprint |

Aliases need not contain personal contact information. Do not collect secrets or identifying
user text without necessity, authorization, and a retention/redaction policy. Generated drafts
start pending; neither the authoring model nor the candidate under test is an independent reviewer.

Review states: draft -> independently_reviewed -> adjudicated/accepted, or quarantined/rejected.
All accepted rows need a reviewer other than their author; disagreements need a recorded
resolution. Freeze every evaluation label before candidate selection. Preserve an append-only
correction history; a post-freeze correction requires a new dataset version and invalidates
unqualified reuse of prior scores.

The proposed dataset manifest is versioned separately from the model protocol. It must bind
record schema, catalog, labeling policy, oracle, source-group assignments, split hashes, rights,
review ledger, and exposed-source exclusions. An independent-review-complete flag is derived
from that ledger, never manually asserted merely because generation finished. The v2 loader/
manifest contract is not implemented; do not pass a draft manifest to the current v1 loader.

## 8. Required implementation before data collection is accepted

- A record/review validator that fails missing provenance, unresolved labels, role conflicts,
  uncovered categories, forbidden cross-split lineage, and incompatible catalog versions.
- An independent effect oracle and mutation tests; expected-value generation must not execute
  the coordinator or use candidate predictions.
- An explicit numeric grammar/domain contract with extraction tests. Current extraction does not
  enforce all proposed limits; retraining alone cannot implement them.
- Optional model-neutral diagnostics for pre-compiler task decisions and separate intent scores.
  Do not weaken the Planner -> Plan IR execution boundary or infer intent from a blocked plan.
- Exact and near-duplicate checks plus reviewable family assignment. A similarity threshold alone
  is not proof that two source groups are independent.
- Plugin exports with round-trip checks from intended task/parameters to training targets.
  Freeze split assignment before export; no model-family fields in canonical expectations.

## 9. Freeze and training gates

1. Owner approves workflow/default-target rules, numeric scope, exclusions, review budget, and
   named independent reviewers. Otherwise this remains a fixture-only draft.
2. Required tooling passes deterministic tests; disagreements are quarantined, not auto-fixed.
3. Rights, review ledger, source-family isolation, coverage, and independent-oracle checks pass.
4. Freeze the catalog, label policy, accepted records, split manifest, and review ledger. Store
   separate immutable outputs; preserve every v1 artifact and test set.
5. Only then train a new candidate. Select on validation outcomes and intent/refusal quality;
   evaluate the frozen tests after selection using both batch and deployed individual planning.

For preview qualification, retain the roadmap's useful-outcome and safety gates. Additionally,
correct abstention must include the intended pre-compiler decision, not only a safe final status;
score ambiguity and unsupported requests separately. Publish task understanding, runtime blocking,
actual effects, format failures, and wrong-but-permitted actions as separate measurements.

No dataset build, retraining, model promotion, or product claim follows automatically from approval
of this written draft. The next implementation batch is the validators/oracle and review workflow,
after the unresolved scope choices are settled.
