# Rust execution-service reference

[Documentation home](../README.md) · [Tutorial](../tutorials/rust-execution-service.md) · [Concepts](../concepts/execution.md)

**Experimental. Linux/WSL.** There are two separate services. The v1 reference below controls
only a software volume endpoint. The [v2 notes service](#v2-notes-service) creates and reads real
app-owned notes through a generic client and supervised worker. Neither controls native audio
or provides the planned cross-platform API. Their credentials, sockets and journals are separate.

## Find command help

From the repository root, inspect usage without starting a host or supplying credentials:

```bash
cargo run --locked -p edge-cli -- preview --help
cargo run --locked -p edge-cli -- capabilities --help
cargo run --locked -p edge-cli -- service --help
cargo run --locked -p edge-cli -- workspace-service --help
```

With `edgectl` on your PATH, use `edgectl <command> --help` directly. Help works on all
CLI build platforms; actual local service calls still require Linux/WSL. It prints usage
and performs no service connection or action. The examples in help show the required flag
order; service examples assume you have already created their JSON inputs and credentials.

`preview` and `capabilities` inspect saved context and cannot authorize or execute actions.
`service` calls the v1 simulated-volume service; `workspace-service` calls the v2 real-note
service. They are not interchangeable: v2 uses separate credentials and state. Both execution
services require separate owner approval and client submission for writes.

## Connect and call

For a complete, runnable client, use the [approved-request example](../../crates/edge-client/examples/approved_request.rs)
and [quickstart](../getting-started.md). The example is owner-run; do not give its owner credential
to an ordinary client application.

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

## V2 notes service

Use this path to create and retrieve real notes without a model or physical device. It uses
`edge-execution-service.v2`, `edge-action-credential.v2` credentials and a separate state
directory. Never reuse the v1 software-service directory or credentials.

For an automatic check from the repository root in Linux/WSL:

```bash
bash scripts/test-workspace-service.sh
```

The diagnostic creates private test notes, checks consent and same-ID retries, runs worker
fault tests, and stops its host. It retains journals and credentials for inspection; do not
upload that directory. Fixture approval is automated test evidence, not independent consent.

For the interactive example, start **terminal A**:

```bash
cargo build --locked -p edge-host -p edge-workspace -p edge-cli --bins
cargo build --locked -p edge-client --example workspace_client
mkdir -p "$HOME/.local/state"
cargo run --locked -p edge-host -- serve-workspace \
  --directory "$HOME/.local/state/edge-delegate-workspace-v2"
```

Leave it running after `READY`. In **terminal B**, from the same repository:

```bash
cargo run --locked -p edge-client --example workspace_client -- \
  "$HOME/.local/state/edge-delegate-workspace-v2" \
  "$HOME/.local/state/edge-delegate-workspace-v2/owner-v2.json" \
  workspace-note-1
```

Inspect the preview and type `create` to approve; Enter declines without creating a note.
The example is an owner-run tutorial using separate owner and client connections. An actual
application receives only its enrolled client credential, not the owner's credential.

Successful output includes an opaque note ID, the readback and durable activity. Repeating
the command with `workspace-note-1` returns the same completed note, not another creation.
Use a new request ID only when intentionally requesting a new note. After timeout or an
unknown outcome, inspect/reconcile the original request rather than rerunning with a new ID.
A declined or expired identity cannot be revived into a new action.

### V2 client and methods

The public Rust entry point is `edge_client::actions::GatewayClient`. It imports no runtime
or training code. `connect` reads a private credential file; `with_credential` accepts a
supplied credential. Every call verifies host identity and re-authenticates. `close` prevents
further calls. See the [complete client example](../../crates/edge-client/examples/workspace_client.rs).

| Method | Access | Meaning |
| --- | --- | --- |
| `capabilities(after, limit)` | Client | Exact permitted action/endpoint pairs; at most 20 entries |
| `preview(request)` | Client | Bind caller-generated request ID, target, typed arguments and budget; no dispatch |
| `approve(principal, id, hash)` | Owner | Confirm one exact, current preview; a client cannot self-approve |
| `execute(id, hash)` | Client | Execute or return existing progress; never auto-retry a mutation |
| `status(id)` | Client | Inspect that client's durable record |
| `events(after, limit)` | Client | Cursor-ordered metadata, at most 100 entries, no note bodies |
| `cancel(id)` | Client | Fence undispatched work; dispatched work may remain uncertain |
| `reconcile(id)` | Client | Query receipt evidence without invoking the action again |
| `call(Enroll/Inspect/Revoke)` | Owner | Explicit permissions, inspection or durable revocation |

`call(Command)` exposes the same versioned operations for CLI integrations. Use
`edgectl workspace-service --directory DIR --credential FILE --command JSON_FILE`.
Enrollment additionally requires `--save-credential NEW_FILE` and never prints a token.
The old `edgectl service` remains v1. The parser requires the flag order shown.

V2 enrollment command shape:

```json
{"method":"enroll","principal":"my-app","permissions":[{"endpoint":"notes","action":"notes.create"},{"endpoint":"notes","action":"notes.read"},{"endpoint":"notes","action":"notes.list"}]}
```

Permissions are exact pairs. They do not authorize unapproved writes. Reads need explicit
action permission and enforce resource ownership; knowing another client's note ID is not
permission to read it. Existing enrollment cannot silently broaden permissions or reactivate
a revoked principal. V1 `control` scopes have no meaning here.

### Worker and recovery boundary

The host launches the installed `edge-delegate-workspace-worker` beside its executable.
Only trusted host setup supplies its path and arguments. Client commands cannot select
an executable or send raw worker messages. The worker receives no enrollment tokens.
The private inherited socket carries bounded frames and sequence-bound responses.

The notes workspace has one exclusive live owner. Normal teardown closes SQLite
before explicitly releasing the ownership lease; failed initialization also releases
an acquired lease without discarding the original error. Rejected contenders cannot
release the current owner's lease. A still-running owner returns
`workspace_already_owned`: allow that owner to finish or stop it normally, rather
than deleting the lock file, notes database, or journals. Reopening preserves the
original notes and receipts; it does not retry an uncertain operation. Inspect and
reconcile its original request ID.

The host enforces observation/invocation transport deadlines and discards late responses.
Timeout, disconnect or corrupt transport retires the child. Observation or explicit
reconciliation may restart it; restart does not resend the uncertain invocation. On Linux,
the worker also exits when its parent dies. This is process supervision, **not a sandbox**
against trusted installed code or other programs running as the same OS user.

`execute` currently waits for a result; callers may poll `status` from another connection.
There are at most 16 connection handlers and nine concurrent executions (one adapter owner
plus eight waiting). Saturation is rejected, not buffered indefinitely. Status/cancellation
do not wait for a hung worker. Client wait timeouts are not cancellation acknowledgements.

Unknown writes fence further writes to that endpoint until reconciliation. A terminated
worker may already have committed a note. Conversely, absence of a receipt after a crash is
not proof of no effect. Never delete journals or manufacture a successful receipt to clear
this fence. No stale-backup recovery procedure or production release is claimed.
