# Roadmap to a supported production release

[Documentation home](README.md) | [Measured evidence](qualification-status.md) | [Release contract](release-contract.md)

Approved direction: 27 September 2026. This is the single roadmap. Features, tests and smoke
results are not release authorization. **Current status: internal experimental candidate.**
The exact supported native deployment remains to be selected and qualified.

## Product and release sequence

Ship an offline developer SDK and supervised Linux gateway for three bounded English tasks:
return temperature, display an explicit number, and read/display temperature. Clarify ambiguity
and decline unsupported work without acting. Support Python, CLI and local Unix-socket clients.
The first physical integration is one USB sensor/status display with firmware we control.
No machinery, locks, heaters or safety-critical decisions.

Keep request -> model decision -> deterministic task compiler -> Plan IR -> authorization ->
durable execution -> confirmed or uncertain result. Do not rewrite working foundations.

| Milestone | Main work | Dependency and exit |
| --- | --- | --- |
| M0: release contract | Scope, support matrix, behavior, threat assumptions, acceptance requirements | Owner-approved direction recorded; exact native hardware/environment and measurement envelope still required |
| M1: trustworthy evidence | Reviewed pilot workflow, outcome metrics, fail-closed evidence, challenge tests | Mutation tests reject incomplete evidence; real independent review remains separate |
| M2: application layer | Public SDK, worker supervisor, local service, deadlines, overload, lifecycle | M0; clean install, concurrency, cancellation and fault tests pass |
| M3: reviewed candidate | Dataset v2, reproducible exports, validation-selected task pack/model | M1 and independent reviewers; frozen quality gates pass |
| M4: reference device | USB adapter, controlled firmware, sensor/display assembly, conformance | Approved procurement/access; observed physical effects and recovery tests pass |
| M5: qualification | Performance, resource, security, soak, installation, upgrade and field evidence | M2-M4; every applicable acceptance gate passes for matching identities |
| M6: supported release | Signed packages, offline bundle, operator docs, support and controlled rollout | M5, independent release review and owner publication approval |

Engineering owns implementation and automated evidence. The owner owns product decisions,
reviewer recruitment, expenditure and release authorization. A separate reviewer owns independent
labels/release review. Adopter tests require people who did not implement the setup.

Initial planning allowance: **16-24 engineer-weeks**, not a release-date promise. Re-estimate
after M1; reviewer availability, hardware access and failed quality gates extend calendar time.
No purchase, paid service, publication or destructive environment change is authorized here.

Progression: internal candidate -> qualified developer preview -> supervised physical pilot ->
supported 1.0. WSL/emulator evidence cannot establish native-Linux/physical support.

## M1: trustworthy evidence and review

Report task/parameter correctness, plan validity, actual returned values/effects, genuine
ambiguity, unsupported work, numeric-format clarification, unnecessary abstention,
wrong-but-permitted actions, task-forbidden calls and authorization violations separately.
Do not rename status accuracy to outcome accuracy.

Require complete/version-compatible reports, unique case identities, coverage, reviewed-record
fingerprints and source/model/catalog/numeric/settings/policy/adapter/firmware/dataset/hardware
binding. Old reports stay readable but cannot establish unmeasured gates. Missing evidence fails.
Effect assertions, not status strings alone, establish benchmark success.

Mutation tests must cover missing/duplicated cases, altered settings, absent review history,
wrong effects, incomplete runs, invalid numeric evidence and identity mismatches. Report
developer-preview and physical-release status separately; model reports cannot grant either alone.

Finish the existing 80-example pilot before expansion:
1. Actual independent reviewer supplies decisions before seeing proposed answers.
2. Preserve original answers and disagreements.
3. Owner adjudicates behavior against the approved rules.
4. Original reviewer confirms complete context/effects; export a new snapshot.
5. Keep all exposed pilot examples and descendants out of new holdouts.

Review tooling validates recorded declarations, not reviewer identity or human truthfulness.
Never manufacture approvals or silently overwrite a source snapshot.

## M3: dataset v2 and candidate selection

| Split | Cases | Minimum families | Maximum per family |
| --- | ---: | ---: | ---: |
| Training | 2,800 | 300 | 10 |
| Validation | 700 | 120 | 6 |
| Frozen functional test | 700 | 120 | 6 |
| Separate safety suite | 200 | 50 | 4 |

Validation/test each require 100 examples per supported task, 100 ambiguity, 100 unsupported,
100 restricted-context and 100 numeric challenges. Safety covers at least ten mechanisms.
Require at least three human contributors across collection/pilot and a reviewer distinct from
each author. Generated wording supplements coverage; it does not establish independent authorship.

Keep source templates, related paraphrases, numeric substitutions and counterfactuals together.
Check exact and near duplicates with recorded family merges, rights, provenance, exposure and
split ancestry. Add numeric subtypes, export round trips and policy compatibility checks.
Freeze an immutable manifest before final evaluation; do not tune against frozen tests.

Train sequentially on the laptop after review/export gates. Pin model revisions, run compute
preflight, record peak memory and retain provenance. Compare base model, current adapter,
new compact adapter and classifier on identical validation outcomes/numeric policy.
Keep deterministic grammar explicitly labelled as a baseline. Select quality/abstention first,
latency second, not training loss alone. If none passes, stop promotion.

## M2: SDK, task packs and supervised service

A task pack binds catalog/parameter semantics, artifact/protocol, explicit strict numeric policy,
inference settings, runtime policy, adapter/firmware compatibility, hardware and evidence.
Reject mismatches before readiness. Profiles remain data; installed plugins/builders/adapters
are trusted code. Existing commands/artifacts keep legacy numeric behavior.

Extract public application ownership with compatibility imports. Target GatewaySession startup/
close, preview, execute, status, reconcile and cancel; local client and serve/request/status/
reconcile/cancel CLI commands; a separate versioned JSON service envelope.

The eventual service has one active model request, one execution owner per device, at most eight
waiting requests, default whole-request deadline 2,000 ms and hard maximum 5,000 ms. Bound input
and frame size, reject overload explicitly, listen only on a permission-controlled Unix socket.
Inference runs in a spawned worker without device-dispatch authority. Supervisor owns journal,
authorization, adapter and deadlines; discard late results.

Lifecycle: loading, warming, ready, degraded, stopping. Preparation never dispatches actions.
Readiness requires verified pack, initialized storage, live adapter and prepared model.
Queued cancellation guarantees no dispatch; after dispatch it does not imply undo. Report
uncertainty and reconcile. Restart never automatically resumes unfinished actions.

## Execution and recovery hardening

Preserve immutable request/device binding, intent before dispatch, atomic operation claims,
device serialization, fresh authorization and durable receipts. Extend deadlines across
queueing, planning, validation, storage locks and transport; check immediately before dispatch.
A timed-out thread does not prove a physical action stopped.

Inject faults before/after request persistence, plan binding, operation claim, invocation,
physical completion, acknowledgement and receipt commit; test restart at every transition.
Cover worker/process death, disk full, database locks/corruption, malformed responses, device
replacement, stale snapshots and clock changes.

Unknown, failed and successful are different outcomes. Stop dependent work on uncertainty.
Never blindly replay uncertain writes, claim exactly-once physical execution, or delete journals
to hide failure. Version migrations; test backup, upgrade and rollback. Restore of a stale backup
must fence dispatch until deployment identity and device receipts reconcile.

Bound diagnostic logs/storage; preserve unresolved operations and deduplication evidence.
At safe storage limits refuse new execution and document operator recovery.

## M4: physical reference integration

Use the [reference-device proposal](reference-device.md); no hardware has been purchased or qualified.
Implement stable identity, boot/storage epochs, bounded serial frames, fingerprints, durable intent/
receipts and cancellation fencing. Reject stale sessions and duplicate IDs with changed arguments.
Translate deadlines conservatively between host and MCU clocks using measured uncertainty;
never treat host monotonic timestamps as MCU time.

Independently observe display effects and compare measurements to a reference. A firmware ACK
does not prove visible pixels. Test resets/power cuts, interrupted commits, full receipt storage
and flash wear. Unknown remains unknown. Hardware absence blocks M4, not SDK/emulator/data work.

## M5: acceptance matrix

| Area | Release gate |
| --- | --- |
| Each supported task | At least 98% correct completed outcomes separately; refusals fail |
| Ambiguity / unsupported | At least 95% correct clarification / refusal separately, zero invocations |
| Numeric challenges | At least 95% intended outcomes; zero invalid-literal dispatches on strict display path |
| Restricted/safety | Every expected safety outcome correct; zero unauthorized or task-forbidden calls |
| Wrong actions | Zero wrong-but-permitted actions across final functional and safety suites |
| Statistical reporting | Counts, family/category breakdowns, confidence intervals, unresolved findings; no independence claim for related variants |
| Warm timing | P95 below 1,000 ms in every run/phase, through acknowledgement, disk-backed journal |
| Workload | Three runs; at least 200 requests per burst, 3-second-idle and 15-second-idle phase; failures/abstentions retained |
| Startup | Cached ready within 60 seconds; first preparation within five minutes |
| Resources | Postwarm process-tree RAM <=4 GiB, GPU <=2 GiB; startup peaks separate |
| Admission/deadlines | Bounded queues and explicit expiry/rejection; zero dispatch after pre-dispatch cancellation/expiry |
| Recovery | Crash, duplicate, timeout, lost ACK, storage, migration and recovery matrix passes |
| Soak | 72-hour emulator and seven-day physical runs; no unexplained effect, hidden uncertainty, growth or leaked children |
| Adoption | Two independent developers install/query/recover using docs without maintainer intervention |
| Field pilot | Two operators, 14 days, 500 supervised requests with independently recorded intended outcomes |
| Integrity | Matching build/model/settings/device evidence, clean install, independent review, owner sign-off |

Preregister a broader workload than the six smoke phrases. Separate preprocessing, inference,
validation, persistence and transport; record hardware/software, artifact size and memory.
No concurrent training. Historical 188-193 ms P95 runs used RAM-backed /tmp and do not establish
disk-backed performance. Keep measured results in qualification status.

Any unauthorized action, unexplained physical effect or uncertain-write replay stops
qualification and resets affected validation after correction. Averages cannot waive a safety
gate. Sub-250 ms, voice readiness and SOTA comparisons remain separate future work.

## M6: deployment, rollout and maintenance

Deliver wheels, offline bundle, pinned dependencies, software bill of materials, verified hashes
and signature verification. Use a non-root service account, restricted socket/device access,
protected journals/backups and supervised system service. No raw request/model logs by default.
Expose readiness, health, queue, timeout, uncertainty, restart, disk and memory diagnostics.

One onboarding path must work outside the checkout/author's environment. Include integration,
diagnostics, recovery, consistent backups, upgrades and rollback guides. Retain a last-known-good
pack without losing journal/device identity or repeating uncertain operations.

Initial named 1.x support window: 12 months. Triage security, wrong-action and data-loss reports
within two working days; disable affected functionality where necessary. Requalify changed
components before promotion, review dependency/security updates monthly, publish compatibility/
recovery notes. No automatic training from field traffic or automatic model updates.

## First batch: implementation tracking

Implemented foundations (not milestone completion):
- Qualification v2 evidence checks reject absent completion, combined abstention scoring,
  duplicate IDs, mismatched deployment identity, missing review records and status-only timing.
  Release status remains false until operational qualification exists.
- Numeric development suite runs the actual planner, compiler, runtime and simulator against
  explicit effects, including non-action challenges; no training or physical dispatch.
- Append-only review ledger preserves blind decisions, adjudication and final reviewer confirmation.
  Pilot acceptance still needs real reviewer input; no rows were auto-accepted.
- Candidate task-pack integrity validator requires explicit decimal policy, hashes and compatibility.
  It does not load a model, establish runtime compatibility or grant production readiness.
- Public synchronous application session extracted; lab import remains compatible.
  Preview, execute, status, reconcile, start/close are available. Supervisor/service/cancel are pending.
- Support contract and procurement proposal recorded.
- Added the explicitly deterministic bounded-commands baseline and richer numeric failure
  diagnostics. Whole-command matching blocks partial compound execution in this opt-in path;
  it does not alter trained artifacts or establish learned-model quality.

Next engineering batch, in order:
1. Complete producer instrumentation for independently checked authorization/numeric dispatch
   evidence and full deployment identity; current generic evaluation reports remain ineligible.
2. Produce the preregistered three-phase release benchmark (the existing six-query benchmark
   now checks effects but is still a smoke workload).
3. Build spawned worker supervisor, bounded Unix-socket service, admission/deadline/cancel tests.
4. Finish full review/export/freeze, near-duplicate/family and rights gates with real contributors;
   do not start training before they pass.
5. Implement physical protocol/firmware after hardware access; then M5 operational evidence.

Each batch includes tests, documentation, evidence paths and honest remaining blockers.
Do not mark M1-M6 complete merely because their foundations exist.
