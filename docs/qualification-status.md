# Current implementation and qualification status

[Roadmap](roadmap.md) | [Release contract](release-contract.md) | [Historical evidence](history/qualification-status-through-2026-09-28.md)

**Experimental developer software. No supported physical deployment or production release is qualified.**
This page summarizes current capabilities; the dated archive preserves measurements, artifact
paths and failed experiments. Documentation changes do not retrain or qualify models.

## Authenticated software execution service (29 September 2026)

The new Linux/WSL service exposes the existing durable authority through a separate
authenticated Unix socket, public Rust client and `edgectl service`. Enrollment and
revocation persist privately. Clients have inspect/control scopes; owner confirmation is
separate from client submission. Each request uses the authenticated principal, not a
principal supplied in a client action. Restart restores enrollment/results, never previews,
approvals or unfinished execution.

The [automated service diagnostic](tutorials/rust-execution-service.md) drove the actual
host and CLI through enrollment, rejected self-approval, owner confirmation, submission,
same-ID retry, durable status, restart and persistent revocation. It retained one software
write and evidence at `/tmp/edge-execution-cydjPY/evidence/report.json` in WSL. This directory
also contains private credentials; it is not a public release artifact.

The service tests cover wrong credentials, negotiation, identity switching, client separation,
read-only scopes, persistent revocation, post-restart recovery, dropped submission responses,
in-flight cancellation, failed revocation persistence, private-path checks, overload and
partial-frame expiry. These are test-program approvals, not independent human review.

Locally verified for this batch: **119 Rust tests** passed, including 13 execution-service
integration tests using the real adapter worker. Formatting, Clippy with warnings denied and
the release build passed under WSL. The Python regression suite passed **601 tests, with one
hardware test deselected**; Ruff and 23 documentation/architecture checks passed. These
results establish software regression evidence, not native-device or production qualification.

The original preview socket remains non-executing. Native controls, other platform transports,
the companion UI, Python/TypeScript clients, event streaming, key rotation, safe restore and
production qualification remain pending. Tokens plus same-user IPC do not sandbox malicious
software running under the same OS account. No physical test devices were used or required.

The following sections record earlier implementation batches; their initial limitations and
test counts are historical, not claims that later features are absent.

## Cross-platform foundation (29 September 2026)

The new Rust workspace implements strict immediate-request v2 contracts, deterministic
saved-context preview, bounded JSON framing and a non-executing edgectl command. Shared
fixtures independently verify request/catalog hashes in Python. Existing Python execution
and artifacts remain unchanged. See the [foundation tutorial](tutorials/rust-foundation.md).

At that initial batch there was no authenticated Rust execution host, journal migration,
native adapter, companion app, paired remote client or relay. Linux owner-authenticated preview and its
Rust client are described below. CI definitions include three desktop builds and
mobile library compile checks; those definitions are not evidence that native jobs or
physical-device tests have run. Follow the [stage tracker](roadmap.md#delivery-order-and-exit-gates).

Locally verified for this batch: **23 Rust tests**, Clippy with warnings denied, and release
build passed under WSL with Rust 1.90.0. The contracts/core libraries also passed ARM64 iOS
and Android cross-compilation checks. These are library checks, not app builds or phone tests.
The full Python regression suite passed **601 tests, with one hardware test deselected**;
Ruff and documentation link/schema/hash compatibility checks passed. No new model training,
review approval or performance qualification was performed.
Fresh Python wheel and independent counter-extension installation also passed outside the
checkout, including documented effects/non-actions/replay, SDK example, Unix execution and
review guards, without ML dependencies. This checks legacy packaging, not Rust app packaging.

## Rust software recovery batch (29 September 2026)

Added trusted-embedding approval tokens, durable operation claims/dispatch intent, same-journal
exclusive ownership, pre-dispatch cancellation, restart transitions and a persistent software
adapter. An unknown result blocks new work on its endpoint. Expired/revoked approvals and
changed request bindings do not dispatch. Existing terminal records are not executed again.

The automated [recovery example](tutorials/rust-recovery.md) committed one software write,
lost its acknowledgement, reopened both owners, retried with zero further invocations, and
reconciled to success from the stored device receipt. Another tested fault retained unknown
when the effect occurred without a receipt. Desired-state readback was not treated as proof.

The Rust workspace passed **51 tests** under WSL, including actual child-process exit and
cross-process ownership rejection, malformed acknowledgements, approval binding/revocation,
failed claim/receipt persistence and cancellation. Formatting and Clippy with warnings denied
passed. The automated recovery script retained its generated software evidence directory.
The full Python suite was rerun: **601 passed, one hardware test deselected**, with Ruff
passing. Release build and ARM64 Android/iOS contracts/core cross-compilation also passed.
These mobile checks do not include SQLite adapters, native application builds or devices.

This is a direct library integration, not authenticated IPC, a consumer consent interface,
physical control or full deadline supervision. Process-exit and SQL-trigger tests do not
establish power-cut/disk-exhaustion qualification. Migration, stale-backup fencing, quotas,
global device ownership and native Windows permission qualification are still pending.

## Rust Linux preview-service batch (29 September 2026)

Added a separate-process, owner-authenticated Linux preview host and public Rust client.
Discovery and preview use strict versioned envelopes. Shared catalog/plan/preview types live
in contracts; the client has no executor/storage/adapter/model dependency. Core re-exports
the former type names and legacy preview serialization remains unchanged.

The host verifies Linux peer identity and a private, restart-rotated owner credential.
It bounds active connections and read/write time, rejects incompatible versions, and has
no approval or execution endpoint. The saved catalog is not real-device discovery. Same-user
applications remain trusted; this does not qualify per-application grants or remote pairing.

WSL verification: **65 Rust tests passed**, including 13 local-service tests for wrong
credentials, changed credentials, handshake/schema/version mismatches, stale bindings,
malformed/oversized frames, forbidden methods, private paths, stale sockets, overload and
partial-frame expiration. A separate-process CLI smoke test matched service and offline
previews, with execution_attempted false and no execution database. Clippy passed with
warnings denied. Release build and the full Python suite passed: **601 tests, one hardware
test deselected**, with Ruff passing. [Run the service smoke test](tutorials/rust-local-service.md).

The planned supervised execution authority, native transports on other platforms, public
Python/TypeScript clients, consumer approval flow, native effects, security review and soak
qualification are not established by these results.

## Supervised Rust software session (29 September 2026)

Added a trusted-owner console/session with fresh software previews, exact plan-fingerprint
confirmation and a separate installed simulator process. The host owns approvals and its
journal. The adapter receives only typed operation messages through inherited local IPC;
its environment is cleared, but it is not sandboxed against malicious installed code.
The existing authenticated socket service still has no approval or execution endpoint.

The supervisor bounds adapter I/O, rejects malformed/late responses, retires failed channels
and requires explicit restart. Linux parent-death handling terminates an orphaned adapter.
No uncertain operation is automatically replayed. The diagnostic hung the adapter after one
software write, recorded unknown, retried without another invocation, restarted the adapter
and reconciled its receipt. The final software write count was one.

Verification: **78 Rust tests passed**, including 10 supervision/session tests (one subprocess
helper) and three adapter-contract checks. Coverage includes exact approval, superseded and
cancelled previews, stale state, missing approval, duplicate execution, lost/malformed/late
acknowledgement, a hung child, a crashed child and actual parent-process death during dispatch.
The script also exercised the real interactive console without manual query entry. These are
test-program confirmations, not independent human approval or model-quality evidence.
The full Python suite passed **601 tests, one hardware test deselected**; Ruff passed.

See [the supervision tutorial](tutorials/rust-supervision.md) for the runnable commands and
limits. The console remains synchronous. The following batch adds a separate scoped
in-process authority; execution RPC, native adapters, worker sandboxing, full filesystem
deadline enforcement and production qualification remain pending. Python behavior and
journals are preserved.

## Rust scoped software authority batch (29 September 2026)

Added owner-issued client handles restricted by action, endpoint and operation, with no
client self-approval API. The software authority has one execution owner and eight waiting
jobs, explicit overload, queue-time deadlines, concurrent duplicate admission, revocation,
and out-of-band cancellation. Retention is bounded without silently evicting request IDs.
The dispatch gate prevents invocation when cancellation wins, including after intent is
persisted. After dispatch, interrupted I/O preserves uncertainty rather than claiming undo.

The [automated diagnostic](tutorials/rust-authority.md) rejected unapproved submission,
cancelled a waiting request, interrupted an adapter after its software effect, restarted
the authority and reconciled a durable receipt. It confirmed one software write, with no
queue replay. Reports/journals were retained in `/tmp/edge-authority-qY8bVk/evidence` in WSL;
temporary evidence is not a published release artifact.

Verification: **92 Rust tests passed**, including nine authority tests, two dispatch-gate
tests and three new persistence-boundary interruption tests. Formatting, Clippy with warnings
denied and the release build passed. The existing preview-service and supervised-console
diagnostics also passed. The full Python regression suite passed **601 tests, one hardware
test deselected**; Ruff and 23 targeted architecture/documentation checks passed. After
installing the missing Rust target libraries in WSL, contracts/core compile checks also
passed for ARM64 Android and iOS. These are library checks, not native apps or device tests.

At that batch, admission, offers and grants were **volatile**; only claimed operations were durable. An
owner can inspect/reconcile durable records after restart, but neither queue nor approval
is restored. There is no execution RPC, persistent transport enrollment, consumer consent
interface, durable event stream or production retention policy. The socket client is still
preview-only. No physical effects, model quality, latency qualification, independent review
or security sandboxing were established by that batch. The next batch replaces volatile
acceptance with durable admission; grants and previews still remain in memory.

## Durable admission and schema upgrade (29 September 2026)

The software authority now commits principal/request/approved-plan acceptance before
returning `queued`. A separate SQLite connection shares the same journal lease, so admission
and cancellation do not wait behind adapter I/O. Reserved slots count toward the eight-job
limit. Failed acceptance is not queued; retries retain the same ticket. Cancellation intent
is durable and checked at claim/dispatch, alongside the immediate in-memory dispatch gate.

Restart marks unfinished admissions interrupted, retains their identity and never resumes
them. Owner inspection distinguishes accepted-but-not-claimed requests from actual operation
records. Reconciliation still queries receipts rather than replaying operations.

Rust journal schema 1 upgrades transactionally to schema 2 after a consistent private
pre-upgrade snapshot. Failed validation rolls back the schema change and retains the backup.
This does not migrate Python journals or provide a safe stale-backup restore/downgrade path.
New admission stops at 10,000 retained records instead of silently evicting deduplication
evidence; byte quotas and a supported archival procedure remain pending.

The diagnostic retained evidence in `/tmp/edge-authority-KOUlLS/evidence` in WSL. It showed
one software effect, cancelled queued work, authority restart and receipt reconciliation
without replay. Dedicated tests include actual process exit with active and queued requests,
failed inserts, database locks, changed request bindings, corruption and failed migration.

Verification: **104 Rust tests passed**, plus Clippy with warnings denied and the release
build. The authority, preview-service and supervised-console diagnostics passed. Python:
**601 passed, one hardware test deselected**; Ruff and 23 targeted architecture/documentation
checks passed. These are software tests on WSL, not a production qualification certificate.

Physical test devices are unavailable, as clarified by the owner. No procurement was made.
Software/emulator readiness work continues; production status, native effects, independent
security review, long soak and adopter acceptance remain unestablished. The existing public
socket is still preview-only; scoped execution is an in-process host API, not a shipped
cross-platform service or assistant application.

## What works, and what that establishes

| Area | Implemented / observed | Still missing |
| --- | --- | --- |
| Structured control SDK | Explicit target/action/parameters; preview, execution, status, reconciliation | Supervisor, whole-request deadlines, generalized production packs |
| Software lights | Independent power/brightness, reads, ambiguity rejection, durable duplicate/recovery handling | Physical effects, long soak, deployment reliability |
| Deterministic commands | Closed light grammar; separate three-task bounded-commands plugin | Unrestricted language understanding; neither path is learned inference |
| Learned model path | Compact FunctionGemma decisions through compiler and runtime | Representative quality; existing weights do not control lights |
| Installation | Automated clean-wheel checks outside checkout without ML dependencies | Independent adopter installation and recovery exercises |
| Review tooling | Blind review ledger, adjudication and confirmation checks | Actual independent pilot approval; structural validation is not approval |

Control-batch verification baseline (28 September): **583 software tests passed, one
hardware test excluded**, including 37 control tests; lint and clean-wheel acceptance passed.
This is a dated software baseline, not a live test count or production certificate.

## Documentation verification (29 September 2026)

After restructuring: **596 software tests passed, one hardware test deselected**. Ruff,
diff whitespace checks and the parser-generated command reference check passed.
Clean-wheel acceptance ran outside the checkout without ML dependencies. It executed the
tutorial's actual command blocks and public SDK example, checking exact effects, preview and
ambiguity non-actions, unchanged operation records on replay and installed-package imports.
Recursive Markdown checks cover local file links and heading anchors.

This is automated software/documentation evidence. No model was retrained or requalified,
no independent labels were approved, and no hardware, soak or independent adoption gate passed
as part of this change.

## Known model-quality blocker

The real-model numeric development diagnostic passed **26/36**, including a wrong-but-permitted
action: an unsupported upload compound caused a temperature read and display write.
Other errors included unnecessary refusal, incorrect clarification and malformed plans.
This blocks learned-candidate promotion. Strict parsing is retained rather than repairing guesses.

The deterministic numeric baseline passed **36/36** on those exposed development cases.
That is not a model fix, independent holdout result or physical qualification.
Broader validation and numeric reports remain in the [evidence archive](history/qualification-status-through-2026-09-28.md).

## Timing and outcome claims

User smoke runs show that the optimized temperature path can complete the small tested workload
below one second. They do not establish the full three-run release performance gate.
Historical 188–193 ms P95 results used RAM-backed temporary storage; they are not disk-backed
deployment performance. Manual light-demo timings are also not qualification.

Execution success means the runtime completed the proposed operations, not that it proved
user intent. Reconciliation can establish an operation receipt; it does not automatically
resume dependent steps or verify task completion. See [result semantics](reference/results.md).

## Next work

Follow the [single roadmap](roadmap.md#immediate-next-batch): authenticated local authority,
supervised execution, public clients and storage hardening precede live native controls.
App, pairing/relay, named workflows and learned expanded controls follow
their gates. Autonomous jobs/rules are outside the first redesigned release. No independent
label approval, physical qualification, field pilot or new model result is established by
the foundation implementation.
