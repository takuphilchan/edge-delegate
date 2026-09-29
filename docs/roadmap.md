# Roadmap to a supported release

[Current evidence](qualification-status.md) | [Release contract](release-contract.md) | [Documentation home](README.md)

This is the **single active delivery plan**. Implemented code, qualification evidence and
planned features are different things. The [historical roadmap](history/roadmap-through-2026-09-28.md)
preserves the earlier three-task milestones; those are not a second parallel backlog.

## Expanded device-control delivery

The intended product is an offline developer software development kit (SDK) and supervised
Linux gateway for bounded, low-impact device operations. Preserve the existing boundary:

Request → decision → deterministic compiler → Plan IR → authorization → durable execution → outcome.

Today there is a synchronous public SDK, targeted two-light software controls, and a separate
temperature/display model lab. This is an experimental vertical slice, **not production support**.
Use [current status](qualification-status.md) for evidence rather than treating this plan as a feature list.

| Milestone | Deliverable | Exit requirement |
| --- | --- | --- |
| C0: behavior contract | Targets, units, bounds, effects, ambiguity, approvals and trust assumptions | Contract recorded before adding an action; physical assemblies separately approved |
| C1: targeted contracts | Stable registry/endpoint binding, typed requests, versioned catalog and generalized task packs | Reject drift and incompatible components; legacy compatibility tests |
| C2: immediate controls | Independent targeted actions and observable effects | Permissions, wrong-target prevention, concurrent duplicate, replacement and lost-acknowledgement tests |
| C3: supervised application | Isolated model worker, local service/client, bounded queue and whole-request deadlines | Explicit overload/expiry, no dispatch after pre-dispatch cancellation, worker/storage fault tests |
| C4: jobs | Configure/start/status/stop with persistent job identity and resource limits | Admission distinguished from completion; no silent restart or duplicate start |
| C5: learned control planner | Reviewed target/action/parameter data and compatible candidate models | Per-action frozen outcome gates; independent review and reproducible export |
| C6: routines, then rules | Installed named sequences, then bounded declarative automation | Partial completion, conflicts, cooldown, expiry, event storm and restart tests |
| C7: physical and deployment release | Named hardware/firmware, observed effects, install/recovery/soak/pilot evidence | All applicable gates below, independent review and owner sign-off |

Dependencies: C0 → C1 → C2 → C3 → C4. Data design can start alongside C1; C5 training waits
for stable contracts and reviewed exports. C6 needs C3/C4. C7 needs hardware access and matched
evidence. The first control slice implements parts of C0–C2 only: one endpoint per device,
one target per request, power/brightness reads and writes. Display/logger controls, generalized
packs, supervised service, jobs, learned controls and rules remain pending.

## Next engineering batches

1. Finish C1 catalog/pack binding and compatibility evidence. The current pack inspector is
   for local-display.v1, not a general control deployment bundle.
2. Finish evidence producers: independently checked effects, authorization and numeric
   dispatch evidence, complete deployment identities and preregistered workloads.
3. Build C3 supervision before adding long-running operations.
4. Complete independent review/export/freeze with actual contributors; then train and compare
   C5 candidates. Never manufacture approvals or retrain merely to bypass a failed review gate.
5. Add C4/C6 only with explicit lifecycle and partial-completion semantics. Implement physical
   adapters/firmware after access is approved; qualify the exact deployment in C7.

Engineering owns code and automated evidence. The owner owns scope, expenditure, recruitment
and publication approval. Independent reviewers own independent labels/release review.
Hardware procurement, paid services, publication and destructive changes require separate
authorization. Re-estimate effort after C1; the historical 16–24 engineer-week allowance
covered the narrower sensor/display scope, not this expanded plan.

## Evidence and reviewed data

Report intended action/target/parameters, plan validity, actual effects and returned values,
unnecessary abstention, wrong-but-permitted actions, forbidden calls and authorization violations
separately. Missing evidence fails qualification. Status agreement alone is not task success.

Bind reports to source build, artifact/protocol, catalog, numeric policy, inference/runtime
settings, adapter, firmware, dataset and hardware. Require compatible versions, unique cases,
coverage and validated review records. Mutate inputs in tests: missing/duplicated cases,
altered settings, missing review history, wrong effects and incomplete runs must fail.
Old reports remain readable, but cannot establish gates they did not measure.

Finish the 80-example pilot with blind independent labels, preserved disagreements, explicit
adjudication and original-reviewer confirmation. Export a new version; preserve originals.
Keep exposed pilot examples and descendants out of fresh holdouts. Tooling checks declarations
and integrity; it does not prove reviewer identity or truthfulness.

Before expanded collection, preregister at least 100 frozen functional cases per action family
plus separate ambiguity, parameter, restricted-context and safety suites. Report correlations
and confidence intervals. Include similar names, negation, read/write distinctions, units/bounds,
unavailable devices, unsupported compounds and unseen target names. Use at least three human
contributors and a reviewer distinct from each author.

The three-task dataset-v2 baseline retains these collection constraints:

| Split | Cases | Minimum families | Maximum cases per family |
| --- | ---: | ---: | ---: |
| Training | 2,800 | 300 | 10 |
| Validation | 700 | 120 | 6 |
| Frozen functional test | 700 | 120 | 6 |
| Safety | 200 | 50 | 4 |

Validation/test floors: 100 per original task, plus 100 each ambiguity, unsupported,
restricted-context and numeric challenges. Safety covers at least ten mechanisms.
These counts are **not sufficient by default for newly added actions**; revise coverage before collection.

Keep templates, paraphrases, numeric substitutions and counterfactuals together. Record rights,
provenance, exposure, family merges and exact/near-duplicate review. Verify export round trips
and policy compatibility; freeze an immutable manifest before final evaluation.
Train sequentially with pinned revisions, compute preflight and resource records. Compare
base/current/new compact models, a classifier and a labelled deterministic baseline on the
same validation outcomes. Select quality first, latency second. Never tune on frozen tests.

## Application and execution requirements

Production task packs bind catalog semantics, explicit numeric policy, artifact, settings,
runtime policy, adapter/firmware and hardware compatibility to qualification evidence.
Profiles stay data; installed builders/plugins/adapters are trusted executable code.

C3 targets one active model request, one execution owner per device, eight waiting requests
maximum, a 2,000 ms default whole-request deadline capped at 5,000 ms, bounded frames and a
permission-controlled Unix socket. No TCP listener or cloud calls. A spawned model worker
has no device-dispatch authority; the supervisor owns authorization, persistence and deadlines.
Discard late results. Loading/warming never executes actions; readiness requires storage,
adapter, model preparation and verified configuration.

Check deadlines across queueing, planning, validation, storage-lock waits and transport,
including immediately before dispatch. Queued cancellation guarantees no dispatch.
Cancellation after dispatch does not mean undo. A timed-out thread is not a transport deadline.

Retain immutable request bindings, durable intent before dispatch, device serialization and
fresh authorization. Test faults around every persistence/claim/dispatch/receipt transition,
including process/GPU death, disk full, locks/corruption, malformed responses, replacement,
stale snapshots and clock changes. Stop dependent work after uncertainty. Never blindly replay
uncertain writes or claim exactly-once physical execution.

Version migrations and consistent backups; fence dispatch after stale restoration until
identity/receipts reconcile. Bound logs/storage without pruning unresolved operations or
deduplication evidence. Refuse new execution safely at storage limits. Do not delete journals
to hide failures. Jobs need explicit stop/restart behavior; multi-device work has no implicit rollback.

## Release gates

| Area | Required evidence for the named configuration |
| --- | --- |
| Each action family | ≥98% correct completed outcomes; refusals count as failures |
| Ambiguity / unsupported | ≥95% correct clarification / refusal separately, with no invocation |
| Numeric challenges | ≥95% intended outcomes; zero invalid-literal strict-display dispatches |
| Restricted / safety | Every expected safety outcome correct; zero unauthorized or task-forbidden calls |
| Wrong actions | Zero wrong-target or wrong-but-permitted actions in final suites |
| Reporting | Counts, family/category breakdowns, intervals and unresolved findings; no false independence assumptions |
| Warm timing | P95 <1,000 ms in every run/phase through acknowledgement, on disk-backed storage |
| Workload | Three runs; ≥200 mixed requests per burst, 3-second-idle and 15-second-idle phase; failures/abstentions retained |
| Startup / resources | Cached readiness ≤60 seconds; initial preparation ≤5 minutes; postwarm process-tree RAM ≤4 GiB, GPU ≤2 GiB; startup peaks separate |
| Deadlines / overload | Bounded admission, explicit expiry/rejection, zero dispatch after pre-dispatch cancellation/expiry |
| Recovery | Crash, duplicate, timeout, lost acknowledgement, storage, migration and recovery matrix passes |
| Soak | 72-hour emulator and seven-day physical runs; no unexplained effect, hidden uncertainty, unbounded growth or leaked workers |
| Adoption | Two independent developers install, query and recover a fault using docs without maintainer intervention |
| Field pilot | Two operators, 14 days, ≥500 supervised requests with independently recorded intended outcomes |
| Integrity | Matching code/model/settings/device evidence, clean installation, independent review and owner sign-off |

Preregister broader workloads than smoke phrases; report preprocessing, inference, validation,
persistence and transport separately. No concurrent training. WSL is development evidence,
not native-Ubuntu support. RAM-backed measurements cannot establish disk-backed performance.
Sub-250 ms, voice readiness and state-of-the-art comparisons require separate qualification.

Physical release requires a named, approved low-impact assembly and observed effects.
The [reference-device proposal](reference-device.md) is not purchase approval. Firmware must
handle identity, boot/storage epochs, bounded frames, durable receipts, stale-session rejection
and conservative host/device clock translation. Test power cuts, interrupted commits, full
receipt storage and flash wear. A display acknowledgement does not prove visible pixels.

Any unauthorized action, unexplained physical effect or uncertain-write replay stops
qualification. Correct the cause and repeat affected evidence; averages never waive safety gates.

## Deployment and maintenance

Progression: internal candidate → qualified developer preview → supervised physical pilot →
supported 1.0. No stage is granted by completing features alone.

Deliver verified wheels, offline bundle, pinned dependencies, software bill of materials and
release-signature verification. Use a non-root supervised service, restricted socket/device
permissions, protected journals/backups and raw-text logging disabled by default.
Document diagnostics, consistent backups, upgrades, rollback and a last-known-good pack without
losing deployment identity or repeating uncertain work.

The intended named 1.x support window is 12 months, with security/wrong-action/data-loss triage
within two working days, monthly dependency review and requalification of changed components.
This is a release commitment to establish, not an existing support service. No automatic model
updates or training from field traffic.
