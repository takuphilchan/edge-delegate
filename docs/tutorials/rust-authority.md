# Test scoped requests and cancellation

[Documentation home](../README.md) | [Supervised console](rust-supervision.md) | [Roadmap](../roadmap.md)

This experiment gives an application separate **owner** and **client** handles. The owner
grants a client specific permissions and confirms its exact preview. The client can then
submit that request, inspect progress and request cancellation. One execution thread owns
the journal and supervised software adapter.

It changes a **simulated volume value**, not your computer's audio. It is a Linux/WSL Rust
embedding API, not a network execution service, stable cross-language SDK or assistant app.
The existing Unix-socket client still supports preview only. No model is involved.
That statement refers to the original preview client. The newer
[execution service](rust-execution-service.md) exposes this authority through its own
authenticated socket and SDK, while this page documents the in-process building block.

## Run the complete diagnostic

From this repository in Linux/WSL:

```bash
source "$HOME/.cargo/env"
bash scripts/test-rust-authority.sh
```

No queries need to be entered. The script builds the worker, runs cancellation, admission
and recovery tests, then runs a complete example:

1. Enroll a client restricted to the software output's volume-setting action.
2. Verify that an unapproved submission is rejected.
3. Confirm two exact previews as the test owner.
4. Submit one request; deliberately hang its worker after the software effect.
5. Submit and cancel the second request while it waits in the queue.
6. Cancel the active request. Its possible effect remains **unknown**, not undone.
7. Restart the authority and reconcile the first request's durable receipt.
8. Check that only one software write occurred and the queued request was not resumed.

The script prints the location of `report.json`, the journal and simulator database. Each
run uses a fresh directory and preserves its evidence. Temporary directories may be cleared
by the operating system; copy the whole directory after the process exits if you need it.
These are test-program confirmations, not independent human consent or production evidence.

Read the [complete executable example](../../adapters/simulator/examples/authority.rs) for
the API sequence and outcome checks. Python 3 only locates the Cargo build directory in
the script; the authority and worker are Rust programs.

## Who can do what?

The types live in `edge_host::authority`. They are experimental host integration types,
not methods on the public transport client in `edge-client`.

| Handle | Operations | Meaning |
| --- | --- | --- |
| `SoftwareAuthority` | `start`, `enroll`, `approve`, `revoke` | Trusted setup creates scopes; only the owner confirms a stored plan fingerprint |
| `ScopedClient` | `preview_volume`, `submit`, `status`, `cancel`, `reconcile` | Each method checks its granted permission and request ownership |
| `SoftwareAuthority` | `ticket_status`, `inspect_admission`, `inspect`, `reconcile_record` | In-memory progress, durable acceptance, operation records and receipt recovery |
| `SoftwareAuthority` | `restart_adapter`; drop the handle to close | Explicit worker restart without replay; shutdown cancels pending work and joins the owner thread |

A grant names one principal and allowed actions, endpoints and operations. There are no
wildcard grants or client-side approval methods. Endpoint/action scope is intersected with
the adapter's policy during preview and fresh pre-dispatch checks. A principal cannot be
re-enrolled within the same authority lifetime, even after revocation.

Only simulated `audio.volume.set` on endpoint `output`, with integer percent 0–100, is
exposed by this API. Other device controls, natural-language interpretation and native audio
are not implemented here. Installed embedding code is trusted: handing out scoped handles
does not sandbox malicious code running in the same process or under the same OS account.

## Submission, deadlines and cancellation

There is one execution owner and at most **eight waiting jobs**, shared by preview, approval,
execution and queued administrative operations, including reserved slots while acceptance
is being saved. A full queue returns `authority_overloaded`;
it does not silently accept more work. Status and cancellation do not wait behind that queue.
Retrying submission of the **same offer ID** returns the same ticket without another job.
`Persisting` means a concurrent submission has reserved a slot but acceptance is not yet
acknowledged. `Queued` is returned only after the principal, full request and approved plan
have committed to SQLite. A persistence error never places that request on the execution queue.

`preview_volume` takes an explicit budget of 1–5,000 ms. Preview consumes its own budget;
execution receives that budget afresh at submission, and queue time counts against it.
Approval waiting is outside execution time. The preview must be confirmed within 60 seconds;
the approval token then lasts at most 60 seconds. Reconfirmation does not extend a token.
Expired/stale approvals cannot authorize dispatch.

The dispatch gate serializes cancellation against invocation. It is checked **after**
dispatch intent is durably written and immediately before adapter invocation. Cancellation
that wins this gate prevents invocation even if intent was already saved. Only that trusted
coordinator proof can close a dispatch intent as a no-dispatch cancellation.

| Cancellation disposition | What it establishes |
| --- | --- |
| `PreventedDispatch` | This execution attempt cannot invoke the adapter |
| `PossiblyDispatched` | Invocation crossed the gate; an effect may have occurred. Inspect/reconcile, never assume undo |
| `AlreadyFinished` | The execution attempt ended; inspect its outcome. It may still be unknown |

Active adapter I/O checks cancellation in bounded slices. Cancelling retires the channel
and terminates the worker; this is **not evidence that the device operation stopped**.
Explicit restart is required before further adapter calls. Revocation immediately rejects
new client use and cancels its admitted requests through the same gate.
Cancellation first sets that gate, then records cancellation intent on a second connection
to the same journal. It does not wait for adapter I/O. Storage contention can still delay or
fail the durable update; an error does not undo the already-set in-memory fence. If admission
is still being saved, its completion path checks the fence before queueing. Restart never
resumes interrupted acceptance, including when cancellation persistence was interrupted.

`Completed` means the attempt produced a durable operation record, not necessarily success:
inspect `operation.state`. `NeedsInspection` means an error prevented a definitive response;
use owner inspection and recovery. Never create a new request ID merely to clear uncertainty.

## What survives restart?

**Acknowledged admission is durable; automatic resumption is forbidden.** The journal stores
acceptance separately from execution. A request can therefore have an admission record but
no operation record: it was accepted but had not reached the execution claim.

Client handles, grants, previews, approval handles and live scheduling still exist in memory.
Restart discards those handles and marks unfinished admissions `interrupted`; it never
executes them. An `interrupted` admission is not proof of no effect. Inspect its operation
record and reconcile any uncertain outcome. A `finished` admission describes an attempt,
not physical success; the operation record is authoritative for the actual outcome.

Keep the principal and request ID with the caller's own records. After restart, the owner
can call `inspect_admission(principal, request_id)`, `inspect(principal, request_id)` and
`reconcile_record(principal, request_id)`.
Reconciliation asks for a receipt; it does not invoke the operation again. New client
enrollment does not restore old approvals. Preserve the journal and device database together.

Memory retention is deliberately bounded: at most 64 enrolled clients and 128 offers per
authority lifetime. At capacity, new enrollment/previews fail; entries are not silently
evicted to make an old request look new. These development limits are not a finished
long-running retention or quota policy. Do not delete a journal to reset them.
Durable acceptance is capped at 10,000 records; at capacity, new admissions are rejected.
No unresolved or deduplication record is automatically pruned. Full byte-level storage
quotas and a supported archival procedure remain pending.

## Existing Rust journal upgrade

Opening a Rust schema-1 journal now makes a consistent, private SQLite snapshot named
`before-schema-2-UUID.sqlite` in the journal directory, then upgrades to schema 2 in one
transaction. The new table records admissions. Existing operation records are preserved;
normal restart transitions still fence unfinished operations. If validation or migration
fails, startup fails and the schema transaction rolls back. The backup remains for diagnosis.

This is **not migration of a legacy Python journal**. Unknown schemas remain rejected.
Older Rust builds that support only schema 1 will reject the upgraded database. Do not
replace the live journal with a stale backup to downgrade: stale-restore fencing and a
supported rollback/import procedure are not implemented yet. Preserve the entire stopped
authority directory and seek recovery guidance rather than deleting its journal.

## Limits and next step

- The separate [execution service](rust-execution-service.md) supplies authenticated IPC,
  persistent enrollment and owner-only confirmation. This in-process API itself does not
  authenticate callers. A consumer consent UI and durable event stream remain pending.
- Filesystem commits and pathological process/kernel stalls cannot be hard-preempted.
  No-dispatch cleanup may use an additional two seconds to persist a fence; it never
  renews the execution budget or permits an adapter call.
- The installed worker is not an OS security sandbox. Native workers, planner isolation,
  legacy migration, stale-restore fencing, byte quotas and platform-wide device ownership remain pending.
- These tests establish software behavior, not CPU latency, model quality, physical safety,
  native Windows/macOS/mobile operation or production qualification.

The execution-service boundary is now implemented for the software adapter. Next come
durable events and lifecycle/packaging qualification before introducing native devices.
