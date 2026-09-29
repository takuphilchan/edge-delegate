# Decision: one execution authority across desktop and mobile

Status: approved target architecture; implementation is incremental.

[Active roadmap](../roadmap.md) | [Release contract](../release-contract.md) | [Repository layout](../repository-layout.md)

## Purpose and technology

Build a developer SDK/local host and a companion application as equal products. Both use
the same contracts and authorization boundary. Rust owns the portable core, host and relay;
Python remains the training/evaluation lab. React/TypeScript with Tauri 2 supplies shared
screens, Kotlin and Swift supply mobile bridges. No C# dependency is introduced by default.

The value is controlled, recoverable execution on named targets, not unrestricted screen
automation. A model proposes intent; it cannot grant permissions or emit executable code.
Rust does not automatically improve model understanding, operating-system reliability or
performance. Each needs separate evidence.

## Request path

```text
App / SDK / CLI
  -> authenticated admission
  -> structured request or isolated bounded interpretation
  -> deterministic compiler
  -> target/state/policy checks
  -> preview and bound approval
  -> durable execution authority
  -> installed native/device adapter
  -> receipt, verification and journal
```

The relay carries encrypted peer traffic only. It is not an execution authority.
The destination rechecks permission immediately before each dispatch. Shared UI code cannot
read journal databases, call private adapter functions or access peer private keys.

## Ownership

| Boundary | Owns | Must not own |
| --- | --- | --- |
| Contracts | Strict bounded data types and wire versions | OS, storage, network or model access |
| Core | Target resolution, compiler, policy and state transitions | Concrete adapters or model families |
| Storage | Journal, migration, deduplication and recovery fencing | Intent interpretation |
| Host | Admission, lifecycle, deadlines, workers and adapter assembly | Training or silent cloud fallback |
| Adapters | Installed, typed operations and evidence | New authority or arbitrary model-supplied commands |
| Planner | Bounded decision proposal | Journal credentials or dispatch handles |
| Client/app | Requests, consent UI, status and recovery presentation | Bypassing destination checks |
| Lab | Reviewed data, training, evaluation and artifact production | Production runtime dependencies |

On desktops, one per-user host owns execution. On mobile, pure shared code is embedded in
the foreground application with native bridges. Phones are not miniature desktop daemons:
no Python workers, no unrestricted cross-app controller, no stale offline command queue.

## Action semantics

Capabilities are discovered, not assumed from the OS name. Missing volume controls, absent
app handlers and denied permissions produce explicit unsupported/unavailable results.
Targets bind authority, endpoint/application registration, catalog and observation generation.
Aliases are presentation, never identity; ambiguous aliases require clarification.

The initial workspace pack reads supported status, controls a configured audio endpoint,
requests launch of registered applications and creates/reads app-owned notes. Registered
launch requests have fixed trusted registrations, not executable paths/arguments generated
by language models. iOS does not advertise arbitrary app launch or system-volume control.

The configured workspace workflow creates a session note, sets volume, then requests launch.
It is a bounded sequence on one authority, maximum eight steps, with no distributed rollback.
Stop dependent steps on failure/uncertainty and preserve prior effects. An app launch can
end as handed_off; it does not prove the app is ready.

## Approvals, identity and outcomes

Writes require confirmation by default; reads require granted scopes. An approval binds the
principal, request, exact plan, target generation, parameters and policy/catalog versions.
Default expiration is 60 seconds. Changes require a new preview. Remembered grants remain
visible, narrow and revocable. Pairing is not an execution grant.

Public operations are connect, capabilities, preview, approve, execute, status, events,
cancel, reconcile and close, plus explicit administration for pairing/grants/packs.
The new CLI is edgectl; old Python command names stay intact.

Represent rejection, clarification, awaiting approval, queued/running, success, failure,
pre-dispatch cancellation/expiry, handoff, unknown and partial completion separately.
Evidence is separately API acknowledgement, durable receipt, state readback or independent
observation. Observing a desired state alone does not establish request causality.

Persist intent before dispatch. Atomically bind operation identity to destination, principal,
request, step and argument fingerprint. Exact retries return recorded progress. Changed-input
retries fail. Never blindly replay an uncertain write, infer rollback, or claim exactly-once
physical effects. Neither timeout nor killing a worker proves an OS action stopped.

SQLite migrations, bounded waits, backup and stale-restore fencing are required before live
support. Refuse mutations if evidence cannot be retained; never prune unresolved operations
or deduplication evidence to hide a storage failure. Legacy and Rust executors cannot share
active ownership of a target/journal.

## Connectivity and privacy

Desktop IPC uses restricted Unix sockets or Windows named pipes with enrolled clients.
Peer pairing uses expiring single-use invitations, verified fingerprints and destination
consent. Identity secrets use platform-protected storage; losing keys requires re-pairing.

Direct LAN transport and a self-hosted relay are both in scope. Use established TLS, with
end-to-end authenticated peer identity through the relay. The relay may observe metadata or
deny service but must not read requests, grant authority, or persist execution queues.
Deliver deployment, health, quotas, revocation, key rotation and redacted logging.
Managed accounts, billing and public multi-tenant operation are not included.

No raw user text/model logging by default. Peer disconnect does not establish cancellation;
query the same request identity. Phones accept incoming actions only while foregrounded.

## CPU interpretation and compatibility

Keep deterministic commands and a trained character-ngram baseline separately labelled.
Port data-only classifier inference with exact feature/prediction parity tests. Existing
temperature labels do not become expanded-control labels. Text ambiguity clarifies locally;
no implicit external-model fallback. FunctionGemma remains an optional experimental worker.

Models select actions, candidate references, typed parameters or abstention. They cannot
invent workflow steps or OS commands. The existing pilot, exposure history and failed
reports are retained. Independent review precedes export; select on validation outcomes and
latency, never frozen-test tuning. See the roadmap for numerical qualification gates.

Current v1 controls, Plan IR and artifact protocols retain their old meanings. New contracts
are versioned separately. Move Python lab files only after independent packaging and clean
installation tests; preserve compatibility wrappers until a documented migration removes them.

## Native permission boundaries

Windows uses native endpoint audio and registered-app APIs without elevation. Linux first
qualifies native Ubuntu GNOME/PipeWire, not arbitrary X11/Wayland input injection. macOS uses
Core Audio and application services, without asking for Accessibility privileges unnecessarily.
Android uses supported media and explicit intents; iOS uses its own app actions/App Intents.

These decisions follow the platform APIs, not a promise of identical control powers:
[Tauri native bridges](https://v2.tauri.app/develop/plugins/develop-mobile/),
[Android intents](https://developer.android.com/guide/components/intents-common),
[Android Accessibility policy](https://support.google.com/googleplay/android-developer/answer/10964491?hl=en),
[Apple App Intents](https://developer.apple.com/documentation/appintents).

## Rollout and non-goals

Internal candidate -> qualified developer preview -> supervised field pilot -> supported
platform/pack release. Every promotion requires matching evidence and owner approval.
Keep a last-known-good pack and explicit updates. Requalify affected OS/model/adapter changes.

No autonomous screenshot/accessibility agent, generic input injection, arbitrary shell,
password/payment actions, high-risk actuators, external messaging, arbitrary file deletion,
voice pipeline, background rules, automatic training, signing identity creation or publication.
Physical embedded adapters need their own observed-effect and recovery qualification.
