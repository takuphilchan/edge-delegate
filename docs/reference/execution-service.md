# Rust execution-service reference

[Documentation home](../README.md) · [Tutorial](../tutorials/rust-execution-service.md) · [Concepts](../concepts/execution.md)

**Experimental. Linux/WSL. Software adapter only.** This page describes the implemented
`edge-execution-service.v1` interface, not the planned cross-platform API. The only installed
action is `audio.volume.set` on endpoint `output`. It does not change native audio.

## Connect and call

Start the host with `edge-delegate-host serve-software --directory PRIVATE_DIRECTORY`.
The installed simulator worker must be beside the host executable. Use a dedicated private
Linux directory; the host creates `execution.sock` and persistent enrollment files there.

Call through the CLI:

```text
edgectl service --directory DIR --credential FILE --command JSON_FILE
edgectl service --directory DIR --credential OWNER_FILE --command ENROLL_JSON --save-credential NEW_FILE
```

The flag order shown is required by the current parser. Enrollment requires a new output file
and never prints the credential token. Other successful calls print a JSON reply. Errors go to
standard error with exit code 2. The CLI renders error enum names such as `ApprovalRequired`;
the wire uses `approval_required`.

The public Rust entry point is `edge_client::execution::ExecutionClient`:

```rust,ignore
use std::path::Path;
use edge_client::execution::{Command, ExecutionClient, Reply};

fn inspect(directory: &Path, credential: &Path) -> std::io::Result<Reply> {
    let mut client = ExecutionClient::connect(directory, credential)?;
    let result = client.call(Command::Capabilities {})?;
    client.close();
    Ok(result)
}
```

This snippet assumes the workspace `edge-client` crate; no published package is claimed.
`with_credential` accepts a supplied credential instead of loading a file. `call` makes a
fresh authenticated connection. `close` prevents further calls. The client checks host identity
and response bindings; it does not approve automatically or retry a submission on failure.
It depends on contracts/protocol and transport, not runtime, storage or model-lab internals.

## Authentication and scopes

A credential binds the authority identity, principal and bearer token. A **principal** is the
enrolled client identity. The server also checks the connecting Linux user. Only the owner
credential can enroll clients and confirm plans. Client commands cannot supply a principal
to act on someone else's request.

| Scope | Allowed client methods |
| --- | --- |
| `inspect` | `capabilities`, `preview_volume`, `status` |
| `control` | Above, plus `submit`, `cancel`, `reconcile` |

The owner can administer and approve work but cannot submit as a client. Approval binds the
principal, request, plan, parameters, policy and relevant target state. Its lifetime is 60
seconds. Approval waiting is outside execution time. Changed state requires a new preview.

These scopes apply to the software reference action. They are not generic permissions for
arbitrary devices. Pairing, remote grants and a consumer consent interface are not implemented.

## Methods

CLI command files contain a JSON object with `method` and the fields listed below. Unknown
fields and duplicate keys are rejected. For example:

```json
{"method":"preview_volume","percent":40,"budget_ms":2000}
```

| Method | Caller | Required fields beyond `method` | Reply kind |
| --- | --- | --- | --- |
| `hello` | Credential holder; SDK-managed | `minimum_version`, `maximum_version` | `hello` |
| `capabilities` | Owner or client | None | `capabilities` |
| `preview_volume` | Client | `percent` integer 0–100; `budget_ms` integer 1–5000 | `preview` |
| `submit` | Control client | `request_id` | `submission` |
| `status` | Client | `request_id` | `status` |
| `cancel` | Control client | `request_id` | `cancelled` |
| `reconcile` | Control client | `request_id` | `reconciled` |
| `enroll` | Owner | `principal`, `scope` (`inspect` or `control`) | `enrolled` |
| `peers` | Owner | None | `peers` |
| `approve` | Owner | `principal`, `request_id`, `plan_sha256` | `confirmed` |
| `inspect` | Owner | `principal`, `request_id` | `status` |
| `recover` | Owner | `principal`, `request_id` | `reconciled` |
| `revoke` | Owner | `principal` | `revoked` |
| `restart_adapter` | Owner | None | `adapter_restarted` |

`hello` is the connection handshake, not a second command to send using `call`. The SDK handles
it. Re-enrolling an identical active principal/scope returns the same credential; a different
scope or a revoked principal produces a conflict. `owner` is reserved, not an enrollable client.

Client status and reconciliation address only that principal's records. Owner `inspect` and
`recover` are explicit administrative lookups. `restart_adapter` restarts the software worker;
it does not replay a request or resolve its outcome by itself.

## Results and recovery

The service response envelope contains `schema_version`, `call_id` and `reply`. The CLI prints
the reply directly. Its `kind` identifies the response type; it is not an execution outcome.

| Response field | Meaning |
| --- | --- |
| `preview.request_id` | Identity to use for approval, submission and later inspection |
| `preview.plan_sha256` | Fingerprint of the exact plan the owner must inspect and confirm |
| `submission.admission_durable` | Whether admission is recorded durably; not a completion claim |
| `status.progress` | Live scheduling state, or `not_in_memory` after restart |
| `status.admission` | Durable accepted-request record, or null |
| `status.operation` | Durable operation and available receipt, or null |

Here, dotted names describe fields within the corresponding reply kind, not extra wrapper
objects. Progress, admission and operation are separate observations; work can advance while
a response is assembled. Read the operation record for the effect outcome.

Progress values are `persisting`, `queued`, `running`, `cancelled_before_dispatch`,
`expired_before_dispatch`, `completed`, `needs_inspection` and `not_in_memory`.
`completed` means scheduling finished, not necessarily that the requested effect succeeded.
Null operation can mean work is accepted but not yet claimed. It is not permission to resubmit
under a new identity.

- `succeeded` is completion backed by a software-adapter receipt, not independent physical observation.
- An `unknown` operation remains uncertain until receipt reconciliation provides stronger evidence.
- Cancellation returns `prevented_dispatch`, `possibly_dispatched` or `already_finished`.
  Only prevented dispatch establishes that cancellation stopped invocation. Cancellation is not undo.
- A client timeout or dropped response is not cancellation. Inspect the same request ID.
- After restart, still-enrolled clients can use `status`/`reconcile`; the owner can use
  `inspect`/`recover`. Credentials and records survive. Previews, approvals and live scheduling
  do not. A pre-restart request is not automatically resubmitted.

## Errors

| Wire code | Meaning and next action |
| --- | --- |
| `unauthenticated` | Credential is invalid or revoked. Check the intended service and enrollment; do not copy another client's credential. |
| `forbidden` | Caller lacks permission. Use the appropriate client scope or a separate owner operation. |
| `invalid_request` | Fields or values violate the contract. Correct the command; do not relax validation. |
| `incompatible_version` | Protocol versions differ. Use a compatible client and host. |
| `negotiation_required` | A raw connection did not begin with hello. Use the public client or implement the handshake. |
| `overloaded` | Connection or queue capacity is exhausted. Back off; inspect any previously submitted request before retrying. |
| `approval_required` | No owner confirmation exists for this request. Preview and obtain explicit confirmation. |
| `repreview_required` | Approval expired, was consumed, or no longer matches. Inspect existing work before obtaining a new preview. |
| `not_found` | No matching in-memory offer/request/peer was found. After restart, inspect durable status instead of reusing an old approval. |
| `conflict` | Identity or enrollment was reused with different content. Do not repurpose the existing identity. |
| `capacity` | Retained enrollment, offer or admission limit reached. Preserve evidence; there is no supported pruning shortcut. |
| `persistence_uncertain` | Enrollment/revocation could not be acknowledged durably. Preserve storage and resolve the failure. |
| `rejected` | Other host validation/storage/adapter failure. Preserve the request ID and inspect its record; rejection is not proof of no effect. |

A failed revocation write fences live access, but persistence must succeed before revocation
across restart can be relied on. Inspect `peers` to understand live registry state; it does not
independently prove a failed storage write became durable.

## Protocol and limits

The service uses local interprocess communication (IPC), not HTTP. The SDK sends a
version-negotiated hello followed by one command per connection. Switching credentials
mid-connection is rejected. The original `preview.sock` protocol remains non-executing and
is not compatible with `execution.sock`.

| Boundary | Implemented limit |
| --- | --- |
| Frame | 64 KiB; strict JSON |
| Active service connections | 8 |
| Waiting authority jobs | 8, including admission reservations |
| Hello and command framing | One shared 2-second deadline |
| Response delivery | Separate 2-second deadline |
| SDK command-response wait | 10 seconds; timeout does not cancel execution |
| Execution budget | `budget_ms` from the preview, 1–5000 ms; queueing counts |
| Retained client principals | 64, including revoked entries; owner is separate |
| Offers | 128 per authority lifetime |
| Durable admissions | 10,000 |

See the [wire types](../../crates/edge-protocol/src/execution.rs),
[client](../../crates/edge-client/src/execution.rs) and
[host](../../crates/edge-host/src/execution_service.rs) for implementation details.

## Security and storage

Service directories use mode 0700 and credential files/sockets use mode 0600. Credentials
are bearer secrets. Do not commit, print or upload them with diagnostic evidence.

This is not per-application OS isolation. Malicious software running as the same user may read
that user's files. Installed applications and the adapter child are trusted code, not a
security sandbox. There is no TCP listener, remote pairing, TLS relay, multi-user hosting or
OS-protected keychain integration.

Keep service, preview, software-session and Python journal directories separate. Do not delete
or restore older enrollment/journal/device databases to clear a fault. An old backup can discard
revocation and duplicate-detection evidence. Safe restore fencing, key rotation, archival and
byte quotas remain unfinished. At retained-record limits, new work is refused rather than
silently discarding evidence.

Ctrl-C terminates the host process. Restart preserves records and never resumes queued work.
Graceful system-service shutdown, installation and soak qualification remain pending. Adapter
I/O and framing are bounded, but pathological filesystem calls cannot be hard-preempted.

See [current evidence](../qualification-status.md) before making deployment claims.
