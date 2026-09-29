# Cross-platform delivery roadmap

[Release contract](release-contract.md) | [Architecture decision](decisions/cross-platform-redesign.md) | [Repository guide](repository-layout.md) | [Current evidence](qualification-status.md)

This is the single active roadmap. The approved direction is a Rust execution core,
Python model lab, and a shared desktop/mobile assistant. SDK and application are equal
products. Windows, native Linux, macOS, Android and iOS are in scope, with different
capabilities. Internet control uses an optional self-hosted relay; interpretation stays local.

The existing Python implementation remains available. **Rust currently provides contracts,
offline preview, bounded framing, a single-operation coordinator, a SQLite journal with
trusted-operator approvals, and a fault-injecting software adapter. A Linux authenticated
preview-only host and Rust client now inspect saved contexts. A separate owner console
supervises a software adapter process with exact-preview confirmation and durable recovery.
An in-process software authority adds scoped handles, durable admission and cancellation.
A separate Linux authenticated software execution service now exposes enrollment, owner
confirmation, submission, status, cancellation and recovery. There is no native adapter,
assistant app or relay.**
A working Rust build is not a production or mobile qualification.

## Delivery order and exit gates

| Stage | Deliverable | Exit gate | Current status |
| --- | --- | --- | --- |
| 0 | Revised scope, behavior, trust assumptions, exact deployment inventory | One contract and recorded native device/toolchain inventory | Contract recorded; five-platform inventory pending |
| 1 | Additive Rust/frontend workspace, locked builds, architecture guards | Legacy tests preserved; native and mobile application startup tested | Rust foundation added; frontend and native app tests pending |
| 2 | Versioned contracts, framing and Rust/Python/TypeScript client parity | All clients pass shared fixtures, negotiation and fake-host tests | Separate preview/execution envelopes and Linux Rust clients implemented; Python/TypeScript clients and other native transports pending |
| 3 | Compiler, approvals, journal, simulator, recovery | Duplicate, drift, authorization, lost-ack and restart tests pass | Single-operation recovery plus Rust schema-1 to schema-2 backup/migration added; legacy import and stale-restore fencing pending |
| 4 | Supervised host, bounded queue, workers, deadlines and cancellation | Zero invocation after pre-dispatch expiry/cancellation; uncertainty retained | Linux software execution RPC, persistent scoped enrollment, owner approval and durable recovery implemented; event stream, native supervisors and planner isolation pending |
| 5 | Native status/notes/audio/registered-app integrations | Each advertised capability has native effect and permission tests | Pending |
| 6 | Assistant onboarding, controls, preview, approvals, activity and recovery | New user completes a local action and fault recovery without a terminal | Pending |
| 7 | Pairing, grants, direct connections and encrypted relay | Revocation, wrong-peer, suspension and reconnect tests pass without replay | Pending |
| 8 | Bounded named workflows | Partial effects, handoff, failures and restart remain truthful | Pending |
| 9 | Independently reviewed data and CPU learned planner | Per-action frozen outcome gates and Python/Rust inference parity pass | Pending; old model evidence is not expanded-control qualification |
| 10 | Lab separation, compatibility migration, installers and signing | Fresh installation works without private imports or machine-specific paths | Pending |
| 11 | Security, performance, restore, soak and adopter qualification | Evidence matches exact artifacts/platforms and all gates pass | Pending |
| 12 | Controlled publication | Independent review and owner sign-off | Pending; no publication authorized by implementation alone |

Stages 0-4 establish the authority boundary before native execution. Platform adapter work
can proceed after the contracts stabilize; app controls use SDK contracts, not private
executors. Data design can start early, but training waits for reviewed exports and stable
semantics. Remote control requires the supervised authority and explicit grants.

## Immediate next batch

1. Add durable events, graceful lifecycle and clean-install/recovery tests around the new
   execution service. Enrollment, revocation and accepted requests persist; previews,
   approvals and live scheduling do not resume on restart. Keep the original preview
   socket non-executing. Add planner restrictions separately; filesystem commits remain
   non-preemptible.
2. Enforce device ownership across journals, then implement legacy import/stale-restore
   fencing and byte quota handling. Rust schema upgrades retain a pre-upgrade snapshot;
   that does not yet establish a safe stale-backup restore or downgrade procedure.
3. Add Python/TypeScript clients against the versioned execution service and cross-language fixtures.
4. Introduce the frontend only with executable startup and public-client tests.

The v2 preview is saved-context inspection. Its Linux transport authenticates the local owner,
but the preview cannot certify current state, issue an approval, or authorize a side effect.
Try the [local-service test](tutorials/rust-local-service.md) without entering queries manually.
The separate [software recovery example](tutorials/rust-recovery.md) exercises execution
with trusted test-operator approval, without claiming user authentication or native control.
The [supervised session](tutorials/rust-supervision.md) exercises child-process hangs and
crashes with an owner-confirmed preview; it is not a remotely callable permission service.
The [scoped authority diagnostic](tutorials/rust-authority.md) tests permissions, overload,
concurrent duplicate requests, cancellation and restart recovery without manual queries.
The [execution-service diagnostic](tutorials/rust-execution-service.md) drives the real host
and CLI through enrollment, approval, execution, restart and persistent revocation.

## Qualification requirements

For learned action families: >=98% correct completed outcomes; ambiguity clarification and
unsupported refusal each >=95%; zero wrong-target, unauthorized, task-forbidden or
wrong-but-permitted mutations in final suites. Report counts, confidence intervals and
family correlations. Keep deterministic and learned results separate.

Collect at least 100 independently sourced frozen cases per action family, plus ambiguity,
parameter, unsupported and safety suites. Keep related variants together, preserve exposure
history, and require independent review before training export. The existing pilot and
failed reports are preserved, never auto-approved or relabelled as successful.

On each recorded CPU baseline: structured fast controls P95 <250 ms, bounded interpretation
P95 <150 ms, learned immediate local requests P95 <1000 ms, baseline ready within 10 seconds,
host idle RAM <=128 MiB and total baseline desktop app/host/classifier RAM <=768 MiB.
These are targets, not measurements. Test three runs of >=200 requests per burst, 3-second
idle and 15-second idle phase on disk-backed storage. Include every failure/abstention.
Report application launch, workflows, network RTT and relay overhead separately.

Require a 72-hour host/relay soak, seven-day native/mobile lifecycle testing, two independent
SDK adopters, and a fourteen-day supervised pilot with two operators and >=500 independently
labelled requests. Require migration, backup/restore, overload, cancellation, storage and
security fault evidence, signatures, independent review and owner approval.

A platform or pack can remain experimental while another qualifies. Embedded hardware
needs separate physical qualification. Neither compilation nor WSL tests establish that.

## Ownership and boundaries

Engineering implements code, tests and evidence producers. The owner supplies native device
access, accounts/signing resources, independent contributors and release authorization.
The owner has now clarified that physical test devices are not available. Continue software,
emulator, packaging and fault testing without procurement. Native/mobile and physical effect
qualification remain blocked on access; WSL does not substitute for them. The near-term
deliverable is a software developer preview, not a five-platform production certificate.
Portable desktop CI jobs have passed; see [recorded build coverage](qualification-status.md#platform-coverage).
Those jobs do not establish native controls or physical qualification. Do not invent that evidence.

No purchases, paid infrastructure, signing identity creation, public publication, fabricated
review approvals or automatic model promotion. Preserve unresolved journals. Keep one
last-known-good pack and explicit updates. Requalify changed semantics.

## Historical material

The [previous device-control roadmap](history/roadmap-through-2026-09-29.md) and
[earlier three-task roadmap](history/roadmap-through-2026-09-28.md) remain historical.
Their Linux-only and no-network assumptions do not define the new product.
Legacy artifact behavior remains unchanged until a versioned, tested migration is available.
