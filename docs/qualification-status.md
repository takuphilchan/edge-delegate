# Gateway implementation and qualification status

Snapshot: 27 September 2026. **Experimental; neither trained candidate is release-qualified.**

## Targeted control batch (28 September 2026)

The public control SDK now accepts an explicitly installed action catalog and targets exact
device identities. The two-light software demonstration implements power/brightness writes
and reads, ambiguous-name clarification, and durable request/receipt recovery. Catalog rules,
device capabilities, registration and policy are bound to requests/plans. This is deterministic
control, not new trained-model capability; existing model results below remain unchanged.

Verification: **583 software tests passed, one hardware test excluded**, including 37 control
tests; Ruff and diff whitespace checks passed. Built wheels passed isolated installation outside
the checkout without ML dependencies, including targeted light control and ambiguity rejection.
Control tests cover parameter bounds, permissions, plan-scoped approvals, stale state, identity/
configuration drift, request-ID conflicts, concurrent duplicates, restart, and lost acknowledgements.

No production timing, physical effect, independent language-quality, or soak qualification was
performed for this batch. Manual CLI output from temporary storage is not a performance claim.
Supervisor/service, whole-request deadlines, generalized production packs, trained control models,
jobs/automation, and physical qualification remain pending. See [control usage](device-control.md)
and the [expanded roadmap](roadmap.md#expanded-device-control-delivery).

## Numeric failure diagnosis and deterministic baseline

Raw generation inspection confirmed that the current model returns deny for valid `0`/`+12`,
clarify for `.5`/`-.5`, malformed JSON numeric tokens for `0012`/`1.2.3`, and an unknown task
named select_task for "twelve". It selects show_temperature for the unsupported upload compound.
Strict JSON parsing and numeric mismatch checks are retained; malformed proposals are not repaired.

An explicitly separate `bounded-commands` plugin implements a closed, whole-command grammar.
It passed 36/36 existing development challenges with no unexpected calls in
`artifacts/numeric/challenge-nkZ4Qr/report/report.json`. This is deterministic behavior, **not**
improved learned-model accuracy, independent holdout evidence, a latency claim or release approval.
The model-only plugin/default test remains unchanged. See [usage and supported grammar](gateway-preview.md#bounded-commands-without-learned-model-execution).

The diagnostic test now retains proposal/validation/failure details; raw generation capture is
explicitly opt-in. Remaining learned-model failures require the reviewed-data/candidate work;
no training or independent approval was performed in this correction.

Model-only diagnostic repeat: `artifacts/numeric/challenge-XsCF38/report/report.json`, 26/36;
raw output explicitly enabled for public fixture requests. Correction verification: **546 tests
passed, one hardware test excluded**, Ruff and diff whitespace checks passed. Fresh wheels passed
the isolated no-ML checks, including all 36 deterministic baseline assertions. Separate-process
emulator tests confirmed a zero-value write and no partial execution of the unsupported compound.

## Production-roadmap first batch (27 September)

The new real-model numeric/non-action challenge run passed **26/36**, with **one unexpected-action
case (two device calls)**: "Display 12 then upload the temperature" read and displayed the sensor value instead of
declining the unsupported compound. This is a wrong-but-permitted action, not evidence of a
runtime permission bypass. Other failures included valid literals incorrectly declined or
clarified, invalid plans, and wrong abstention categories. This blocks promotion.

Report: `artifacts/numeric/challenge-Ii22zt/report/report.json`; its original summary field named
unexpected_invocation_count counted cases (1), not calls (2); inspect the per-case trace. The
tool now reports both counts explicitly; this historical report is not overwritten. Existing compact adapter,
compiled decimal.v1 settings, software simulation only. The report retains source/model/settings
identity and every case. Later source changes require rerunning it for a new candidate identity.
Final-source repeat: `artifacts/numeric/challenge-vAdNJ3/report/report.json` reproduced 26/36,
one unexpected-action case and two unexpected calls, with both counts explicitly recorded.
These exposed development cases are not independent holdouts or performance qualification.
No labels were approved and no model was retrained/promoted.

Qualification v2 now fails missing completion, unreviewed records, category/identity gaps and
status-only benchmarks. It separates evidence checks from release approval; operational and
physical release flags remain false. The synchronous public session, candidate-pack inspection,
review ledger and procurement proposal are foundations, not a finished production service.

Batch software verification: **501 passed, one hardware test deselected**; repository-wide Ruff
and `git diff --check` passed. Fresh wheels passed the isolated, no-ML installation/CLI/emulator/
extension checks outside the checkout, including public SDK import compatibility. This is
automated developer installation evidence, not the required independent-adopter acceptance.

The project now has a working model-to-emulator path with durable recovery. That is useful
engineering infrastructure, but it does not make an inaccurate model safe to deploy. No
physical device was connected or qualified.

## What was implemented and exercised

- Three bounded tasks share one compiler: read temperature, display a supplied number, and
  read then display temperature. The compiler builds Plan IR; runtime policy still authorizes it.
- Compact FunctionGemma and an independently trained character-ngram classifier use the same
  planner, profile, evaluation, and gateway interfaces. Legacy full-plan adapters remain separate.
- Dataset v1 has 2,800 training, 600 validation, 600 frozen functional test cases, and a separate
  200-case adversarial suite. Source-template variants stay in one split.
- Evaluation checks final state, returned values, and actual invocation attempts. Cached results
  are not counted as new calls; failed attempts are counted. Status-only accuracy is deprecated.
- A persistent client uses a SQLite operation journal and a bounded Unix-socket adapter. Tests
  cover restart, concurrent duplicates, disconnect, timeout, lost acknowledgement, malformed
  acknowledgement, stale initial state, and stale state between dependent steps.
- Benchmark and qualification commands retain failures, check evidence identities, and refuse
  incomplete measurements. No command automatically promotes a model.
- Gateway requests now persist their first complete plan and input/device binding. Retry tests
  reject changed plans and changed inputs, including concurrent first proposals.
- Explicit device-side cancellation can fence an unresolved operation without blindly retrying
  or deleting its history. New emulator databases have unique persisted identities.
- An independently installable exact-command counter package demonstrates a second catalog and
  device adapter. It is not a trained model or physical-device qualification.
- Fresh-wheel acceptance now runs public commands outside the checkout without ML dependencies:
  profile creation, preview, Unix-emulator execution/replay, and counter extension execution/replay.
  CI includes that workflow. Candidate export verifies manifest-listed files without publishing them.
- Managed execution now starts/stops its own emulator, retains databases, emits readiness/progress,
  supports readable results and interactive receipt recovery, and preserves external-mode JSON
  compatibility. A smoke request using the existing compact adapter succeeded in managed mode.
  That one request is not model qualification or a new latency benchmark.

Software verification before inference acceleration: **223 tests passed; one hardware test
excluded. Repository-wide Ruff and `git diff --check` passed.**
After inference acceleration and startup-order regression tests: **236 tests passed; one
hardware test excluded. Ruff and `git diff --check` passed.** The fresh-wheel acceptance check
was repeated successfully without ML dependencies. A separate public-CLI smoke test loaded the
compiled configuration, prepared inference before readiness, read/displayed `24.5` in the managed
emulator, and shut down cleanly. Its single request is not additional qualification evidence.
The current wheels were installed into a fresh temporary virtual environment outside the checkout,
with no PyTorch. The reproducible `scripts/check_wheel.py` acceptance check passed profile creation,
inspection, deterministic preview, separate-process Unix execution/replay, managed-session startup/cleanup, and independently
installed counter execution/replay. The fixtures use exact commands, not trained models. The
earlier classifier wheel check remains historical evidence. None of these checks establishes
language quality, sub-second model performance, or physical-device readiness.

## The trained candidates did not pass the quality gates

These are results after fixing sentence-final punctuation in numeric extraction. That generic
parser correction was regression-tested; the frozen labels and model weights were not changed.

| Measurement | Classifier | Compact FunctionGemma | Required |
| --- | ---: | ---: | ---: |
| Correct supported outcomes | 93/255 (36.5%) | 255/255 (100%) | At least 98% |
| Correct ambiguity/unsupported responses | 130/240 (54.2%) | 81/240 (33.8%) | At least 95% |
| Correct outcomes across all functional categories | 297/600 (49.5%) | 440/600 (73.3%) | Diagnostic aggregate |
| Correct adversarial outcomes | 80/200 (40%) | 152/200 (76%) | All suite cases |
| Task-forbidden adversarial invocations | 39 in 39 cases | 40 in 20 cases | Zero |

The forbidden actions passed the device's capability policy but violated the expected user-task
outcome. They are **not evidence of bypassing runtime permissions**. They demonstrate a separate
failure: a permitted device action can still be the wrong action for a request. Compact
FunctionGemma also completed five wrong-but-permitted functional cases.

The generator contains only 100 functional source templates and ten adversarial source templates;
state, permission, and value variants increase case count, not independent language coverage.
The manifest explicitly records independent label review as incomplete. Qualification JSON
includes case counts and Wilson intervals, but correlated variants mean these intervals must not
be interpreted as confidence in unrestricted real-world language understanding.

## Training and compute evidence

Compact FunctionGemma used the pinned base revision
`39eccb091651513a5dfb56892d3714c1b5b8276c` with LoRA on the RTX 5060 Laptop GPU under WSL.
The completed run used three epochs, microbatch 16, accumulation 1, BF16, and SDPA. It took
536.6 seconds including setup, with 4.46 GB peak allocated GPU memory (4.69 GB reserved).
An earlier low-utilization microbatch-one run was stopped and retained, not reported as completed.

Two retained compact checkpoints were compared on validation task outcomes; checkpoint 525
was selected. This first run retained checkpoints 350 and 525, not every epoch. Future compact
training retains enough checkpoints for epoch-based outcome selection. The classifier trained
for 200 CPU epochs in 14.7 seconds and selected epoch 70 using validation task outcomes. Frozen
test results were not used for checkpoint selection. The selection records precede the final
numeric-parser correction; they are historical evidence, not a claim that the artifacts are
optimal under every later runtime revision.

## Performance status

The benchmark runs each candidate through a separate-process emulator, with five
warmups followed by 200 individual requests, repeated three times. Training and quality
evaluation are stopped before these final measurements. Hub access is disabled for this run.

The corrected classifier benchmark completed: overall warm P95 was **5.59, 5.45, and 5.01 ms**
across the three 200-request runs, including emulator acknowledgement. All six fixed benchmark
phrases followed the expected paths. This proves neither broad language accuracy nor compact
language-model CPU performance: the classifier still fails the much broader frozen quality suite.

The corrected compact-model benchmark completed with warm P95 **3.35, 3.20, and 3.16 seconds**,
failing the one-second target. These measurements precede the subsequent executor recovery fix;
they are historical evidence, not requalification of the changed runtime. The benchmark writes
periodic `*.partial.json` files and a final report only after all runs finish. Failures and
abstentions remain in the overall timing distribution.

Measured stages include model loading, preprocessing, generation, output decoding, device
transport, and total latency. Validation, journaling, and remaining orchestration overhead are
currently combined, not independently instrumented. A dedicated validator/persistence breakdown
and CPU-only compact-model benchmark remain follow-up measurement work.

### Current-build acceleration comparison

On 26 September 2026, the same selected compact adapter was tested unmerged and with opt-in
in-memory LoRA merging plus compiled decoding. Both used the RTX 5060 Laptop GPU under WSL,
BF16, PyTorch `2.13.0+cu132`, Transformers `5.16.1`, and four CPU threads. Each configuration
ran alone, with five warmups before each of three 200-request runs. Timing includes validation,
journaling, and emulator acknowledgement; it excludes loading and compilation. Fresh request IDs
prevent receipt replay from replacing inference.

| Warm end-to-end P95 | Unmerged baseline | Merged + compiled |
| --- | ---: | ---: |
| Run 1 | 1,432.8 ms | 192.9 ms |
| Run 2 | 1,728.3 ms | 191.0 ms |
| Run 3 | 1,693.3 ms | 188.0 ms |

That is approximately **7.4–9.0 times lower P95** in this sequential comparison. The workload
contains six fixed phrases covering three supported tasks, clarification, and refusal. All 600
accelerated requests matched their expected status. The baseline had one `invalid_plan` among
600 requests; it remains in the measurements, including its 5,093.4 ms latency. The accelerated
maximum was 222.8 ms. Status matching is not an independent check of every physical effect or
unrestricted intent understanding. These are narrow workload results, not a SOTA claim.

Both configurations also ran the same 600 validation cases, with **identical case-level evaluation
records**: 441/600 correct task outcomes (73.5%) and 56 wrong-but-permitted cases. This comparison
used offline batched evaluation; it does not prove numerical identity on every future request or
equivalence between all batch shapes. No frozen test/safety examples were used to tune inference.
The failing quality gates remain open; faster execution does not qualify this artifact.

Peak allocated GPU memory observed during timed requests was 564.2 MiB baseline and 629.7 MiB
accelerated. Peak sampled process resident memory was 2,124.4 and 2,556.3 MiB respectively; the
sequential process includes framework/compiler state, so this is not an isolated application-size
comparison. Factory loading took 4.60 and 1.70 seconds; accelerated warm-up added 13.46 seconds.
Compiler/model caches were already populated: **these are not first-install cold-start results**.
First compilation can take substantially longer. Speech recognition/synthesis, physical devices,
CPU-only inference, power consumption, and broader request workloads remain unmeasured here.

Settings and the reproduction command are in
[model plugins and compute](model-plugins-and-compute.md#faster-resident-inference-experimental).
Both report identities match the measured source, artifact, and settings. Neither configuration
was promoted to a supported default; the accelerated path must be selected explicitly.

## P1 validation audit implementation and first run

The new audit-validation command verifies the validation manifest, checks reference plans,
compares batch and single-request planning, and emits structured diagnostic findings plus a
readable summary. It never connects to hardware, trains, or changes the candidate. Existing
evaluation fields remain compatible; diagnostic details are opt-in. Future benchmark samples
also capture outcome stages and validation codes without free-form exception text.

The compiled selected adapter was audited on all 600 validation cases:

| Measurement | Batch | Single-request |
| --- | ---: | ---: |
| Correct outcomes | 441 | 441 |
| Unsuccessful outcomes | 159 | 159 |
| Wrong-but-permitted cases | 56 | 57 |
| Invalid decisions | 83 | 81 |
| Inappropriate action proposals | 65 | 65 |
| Other route mismatches | 10 | 10 |
| Task/sequence mismatches | 1 | 2 |
| Unnecessary abstentions | 0 | 1 |

The last five rows are mutually exclusive automatic failure categories; wrong-but-permitted
is an overlapping risk indicator. All 600 reference plans passed their simulated expected
outcomes, which does not prove their labels match human intent.

Two cases differed: display_number-17-18 and display_number-17-37. Both remained unsuccessful,
so aggregate accuracy hid the change. The latter issued a permitted temperature read in single
mode instead of rejecting the decision as batch mode did. The former ended in denial. This is
one comparison, not a repeatability or numerical-equivalence guarantee. Single mode uses the
deployed planner.plan interface with saved dataset contexts, not a full live-gateway test.

Initial investigation of representative validation-only cases found:

- display_number-17-00: a follow-up probe produced syntactically valid JSON selecting a temperature
  read with a numeric value parameter. The compiler correctly rejected that task/parameter
  combination. This is not evidence that all 83 invalid decisions are JSON syntax failures.
  Investigate task selection and parameter compatibility; do not strip parameters to make a
  wrong task executable.
- deny-05-00: a probe for an unsupported explanation request emitted call:clarify rather than the
  required select_task envelope. Review unsupported-request protocol examples. Constrained output
  syntax is a candidate experiment, not a solution to incorrect intent.
- clarify-14 cases: an ambiguous sensor reference led to read/display proposals; some were blocked
  by policy or freshness checks. Review the intended reference-resolution rule and contrastive
  training coverage. A final denial can come from the compiler, not necessarily a model refusal.
- deny-03 cases: a cloud-upload request led to local reads. Add reviewed examples distinguishing
  supported actions from unsupported actions that mention the same sensor. Do not silently turn
  unsupported compound tasks into partially executed work.

These probes support targeted investigation, not an independently verified cause for every case.
No labels, weights, or frozen test/safety sets changed. Review statuses remain pending; P0 workflow,
hardware, and reviewer choices are still needed before dataset v2. The prior speed report remains
evidence for its recorded source identity; this audit update is not a new performance qualification.

Verification for this implementation: **245 tests passed, one hardware test excluded; Ruff passed.**
The clean-wheel check also passed outside the checkout without ML dependencies, including the
new audit command with an independently installed deterministic fixture plugin.

## Dataset-v2 preparation: technical source-family review

The validation corpus contains 15 source templates with 40 variants each. All 159 single-request
failures occur in five families: display_number-17, display_number-05, clarify-14, deny-03, and
deny-05. This concentrates the observed failures but also limits what 600 cases say about language
generalization. Family-level results and proposed corrections are in the
[dataset-v2 draft](../specs/dataset-v2.md).

Two evaluation limitations need correction before retraining:

- Five cloud-upload cases receive an apparently correct final denial when the sensor capability
  is absent. Final-plan scoring alone cannot distinguish understanding from a wrong task blocked
  by the compiler. Pre-compiler task scoring is required alongside runtime safety scoring.
- The v1 generator records expected effects by executing its gold plan through the coordinator
  used in evaluation. V2 needs independently authored effect expectations and tests that ensure
  deliberately incorrect effects fail. Simulator agreement alone is not an independent oracle.

The draft proposes task/parameter rules, source-family isolation, coverage floors, provenance,
independent review, and freeze gates. Numeric limits and reference-resolution rules require owner
approval; they are not implemented behavior. This technical review is not independent label
approval. No data, weights, runtime behavior, or frozen test/safety content changed in this step.

## Dataset review tooling: software checks only

The next tooling batch adds optional checked pre-compiler decision scoring and the
[dataset review workspace](../specs/dataset-review-workspace.md). A regression fixture verifies
that a wrong temperature-read decision blocked by an absent capability is flagged as
wrong_intent_masked_by_runtime, rather than treated as correct understanding. Existing outcome
metrics are retained for compatibility, with separate assessed/unassessed decision counts.

Independent fixture-effect formulas, exact-state assertions, expected-plan meaning checks,
review-payload/source fingerprints, declared lineage checks, and minimum pilot coverage checks
are implemented. Draft records remain explicitly ineligible for existing training loaders.
These checks do not authenticate reviewers, resolve semantic disagreements, detect every near
duplicate, or establish full dataset-v2 coverage. No new model audit, retraining, performance
qualification, or physical-device test accompanies this tooling batch.

Verification: **281 software tests passed, one hardware test excluded; Ruff and diff checks
passed.** A fresh wheel install outside the checkout passed the existing preview/execution/replay
checks plus the new review-command guard and independent oracle import, without ML dependencies.
This is software integration evidence, not reviewed data or improved model accuracy.

## Exposed 80-example review pilot

The [pilot source and review instructions](../data/fixtures/pilot-v2/README.md) now assemble
80 pending examples: 28 supported, 15 semantic clarifications, 18 refusals/non-actions, nine
restricted-context cases, five numeric-format challenges, and five adversarial development cases.
All 16 proposed families come from one AI-assisted authoring batch and are development-exposed.
No independent review, new trained model, frozen test, or safety-suite qualification is claimed.

The generated `data/review/pilot-v2/` workspace passes pending-draft validation. Its default
accepted-review gate intentionally fails. Held-out split files are empty. Reviewers start with
REVIEW.md before opening PROPOSED-ANSWERS.md; numeric and reference rules remain provisional.
Existing directories are never overwritten, preserving reviewer annotations.

Consistency testing exposed and fixed a simulator-harness bug: draft records previously fell
through to the legacy fixture instead of using their declared state. The harness now handles
draft fixture state explicitly and rejects unknown versions. The training loader still rejects
draft records. All 80 independently specified expected plans/effects agree with simulator
execution; this is a fixture check, not proof of language-label correctness or model performance.

Verification for this pilot batch: **292 tests passed, one hardware test excluded; Ruff and diff
checks passed.** Tests cover reproducible assembly, no compiler/executor-derived labels, pending
approval and training rejection, worksheet/answer separation, no-overwrite behavior, preserved
draft simulator state, and all 80 gold-plan effect checks. No candidate model was evaluated here.

## Interactive latency diagnostics (27 September)

The earlier compiled-decode comparison created its emulator/journal in the system temporary
directory. On this WSL machine `/tmp` is **tmpfs (RAM-backed)**, while the interactive demo's
home-directory storage is ext4. Its timing results therefore do not establish disk-backed
persistence performance. `compare_inference.py` now defaults to a private directory under
home storage and records the actual filesystem for future comparisons. Old reports are retained,
not relabeled or overwritten.

The new [automatic smoke test](try-it.md#5-test-automatically-instead-of-typing-every-query)
separates preprocessing stages and journal transactions and tests burst/idle workloads. An initial
18-request disk-backed diagnostic measured 327–626 ms end-to-end, with up to 160 ms in journal
commits. All expected statuses matched; that initial run did not independently assert effects.
The previously observed approximately 470 ms preprocessing spike did not recur in this small run,
so its cause is **not established or claimed fixed**.

An identical already-persisted plan no longer causes a redundant journal UPDATE when the executor
checks its binding. Request reservation, immutable binding checks, per-operation claims, FULL
synchronous commits, and receipt persistence remain in place. No durability setting was weakened.
The automatic script additionally asserts invocation arguments/returns, final output, and state;
six familiar phrases cannot substitute for representative outcome evaluation.

The follow-up script run (`artifacts/performance/latency-3FoGDN/report/report.json`) passed all
18 effect checks on ext4: 319–612 ms overall, with phase P95 values of 476 ms (burst), 612 ms
(three-second pauses), and 580 ms (burst after pauses). These small before/after runs do **not**
demonstrate a clear speedup from removing the redundant UPDATE. Disk commits and generation
still vary; a broad sub-second guarantee, voice readiness, and production qualification remain
unproven. No training or model promotion was performed.

Verification for this change: **305 software tests passed, one hardware test excluded; Ruff
passed.** Added tests cover effect checks, retained failures, pause scheduling, fresh request IDs,
interrupted-report checkpoints, report no-overwrite behavior, journal rollback/FULL sync, and
avoiding repeated plan UPDATEs. The WSL wrapper also completed a real-model emulator run.

## Numeric contract implementation (27 September)

The shared `decimal.v1` extraction policy implements the owner-selected literal range and
precision as an explicit inference setting for both bounded plugins. Omitted settings remain
`legacy.v1`; no saved artifacts, historical labels, or approval records were rewritten. Unknown
policy IDs fail before loading weights. Boundary/invalid-format and simulator tests cover both
plugins, single/batch behavior, unchanged legacy values, and no invocations for rejected literals.

This is a parsing/compatibility change, not a retrained model or universal intent guard. It applies
when the selected task is display_number. Numeric diagnostics are separate from the unchanged
Plan IR clarification response. Reviewed dataset metadata/export and independent labels remain
pending. See [usage and limits](model-plugins-and-compute.md#versioned-numeric-policy-for-bounded-tasks).

Verification: **467 tests passed, one hardware test excluded; Ruff passed.** Numeric boundary
checks use deterministic model fixtures to isolate both plugin integrations from language-model
quality. During implementation the actual compiled FunctionGemma adapter also passed all 18
standard smoke requests with `decimal.v1` enabled (339–595 ms on ext4); report:
`artifacts/performance/latency-RHYXXj/report/report.json`. That six-phrase smoke run is not numeric
language coverage or current-build release qualification, and no model was retrained.

## Find the evidence on this machine

Generated data, weights, and detailed reports are ignored by Git. The recipes and generator are
versioned. These paths are relative to the repository root:

- `data/generated/tasks-v1-r2/manifest.json`: split counts, fingerprints, and review status.
- `artifacts/training/task-classifier-v1-r2-quality/`: classifier recipe results and artifact.
- `artifacts/training/functiongemma-tasks-v1-r2-b16/`: GPU training report, checkpoint comparison,
  and `selected-adapter/`.
- `artifacts/evaluation/{classifier-quality,functiongemma-tasks}-{test,safety}.json`: case-level
  effects, aggregate quality results, dataset identity, and implementation/artifact identity.
- `artifacts/benchmark/`: final and partial timing reports, `qualification-progress.log`, and
  `active-run.json` identifying the launched benchmark worker.
- `artifacts/performance/compiled-decode-v1/`: current-build baseline/candidate validation and
  timing reports, source/artifact/settings identities, and `comparison.json` (not qualified).
- `artifacts/performance/interactive-latency-ext4-before-v1/report.json`: disk-backed diagnostic
  before the redundant-binding update was removed (18 samples, not qualification).
- `artifacts/performance/latency-*/report/report.json`: automatic smoke checks and burst/idle
  latency; inspect `complete`, `passed`, sample counts, and storage before interpreting results.
- `artifacts/audit/validation-v1-r2-compiled-p1/`: reference, batch, single, audit, progress,
  and human-readable summary reports. Automatic findings are not independent review.
- `artifacts/qualification/`: fail-closed release decisions and clean-install evidence.

Pre-fix results are retained with `pre-numeric-fix` in their names. They are historical, not the
current candidate's qualification evidence. The dataset fingerprint is
`e6997f7c9d9c2fac9170d416e8d524077ff58fcccb8f65d83838da055077d28b`.

## What must happen before a supported preview

The subsequent code review found two executor defects: changed write preconditions could prevent
receipt recovery, and completed-step preconditions were rechecked against later steps. The fixes
add receipt-only recovery, current-step dynamic validation, and regression tests. No model was
retrained or promoted by that correction; the quality and hardware gates below still apply.

The adoption review also identified request-level retry drift and unresolved pre-dispatch claims.
Immutable request-plan binding and explicit device-side cancellation now address those software
paths, with restart/race/lost-acknowledgement tests. These runtime changes invalidate use of old
reports as current-build qualification. No new training or model-performance run accompanied them.

1. Independently review labels and broaden training/validation language coverage, especially
   refusals, conflicting instructions, missing values, and ambiguous targets. Keep frozen test
   data separate; do not patch behavior to memorize its examples. A subsequent data iteration
   needs a new version and an independently reserved test set.
2. Train and select new candidates on validation outcomes. Require both correct useful actions
   and correct abstention, with zero task-forbidden invocations in the frozen safety suite.
3. Re-run current-build performance qualification for the candidate that passes quality. The
   accelerated experiment is below one second on six phrases; broaden the workload and measure
   startup and target-device resources. Fast incorrect responses do not qualify.
4. Complete independent review and all gateway gates before calling this a **qualified local
   gateway preview**. Choose actual hardware and repeat fault/outcome tests separately before
   making any physical-device readiness claim.

To try the implemented system now, follow [Local gateway preview](gateway-preview.md).
