# Submit an approved request through the local execution service

[Documentation home](../README.md) | [Authority internals](rust-authority.md) | [Current evidence](../qualification-status.md)

This is the authenticated **software execution service**, not another model demonstration.
A client previews a request, the owner confirms its exact plan, and the client submits it.
The host authenticates each connection, checks the enrolled client's permissions and sends
accepted work through the existing durable authority. A client cannot approve itself.

**Current scope:** Linux/WSL, one simulated output-volume endpoint, no native audio changes,
physical device, model or cloud call. Windows/macOS/mobile execution transports, native
adapters, application UI, Python/TypeScript clients and production qualification are pending.

## Test the complete flow automatically

From the repository in Linux/WSL:

```bash
source "$HOME/.cargo/env"
bash scripts/test-rust-execution.sh
```

No queries, copied IDs or manual confirmations are needed for this diagnostic. It:

1. Runs socket authorization, framing, cancellation and recovery tests.
2. Starts the real `edge-delegate-host` executable and enrolls a scoped client.
3. Uses `edgectl` to preview a software volume change to 40 percent.
4. Checks that unapproved submission and client self-approval are rejected.
5. Confirms the exact plan **as test-owner code**, then submits as the client.
6. Checks durable status, same-ID retry and exactly one recorded software write.
7. Restarts the host: credentials/results survive, but old approvals cannot resume work.
8. Revokes the client and proves the credential stays rejected after another restart.

The script prints `report.json` and preserves its evidence directory. It terminates only
the host processes it started. The directory also contains **private credentials and
enrollment data: do not upload or share it wholesale**. Test-program confirmation is not
independent human consent review, a performance benchmark or production certification.

## Run a service yourself

Build the three binaries, then start a dedicated service directory:

```bash
cargo build --locked -p edge-host -p edge-cli -p edge-simulator --bins
mkdir -p "$HOME/.local/state"
cargo run --locked -p edge-host -- serve-software \
  --directory "$HOME/.local/state/edge-delegate-service"
```

Keep this terminal running. First startup creates a private directory, software authority,
owner credential and enrollment registry. Subsequent startup requires those identities to
match. Do not reuse a Python journal, preview-service directory or owner-console directory.
Use the Linux filesystem, not `/mnt/d`, for private Unix permissions and sockets.

In a second terminal, enroll a client. The output file must not already exist:

```bash
EDGE_SERVICE_DIR="$HOME/.local/state/edge-delegate-service"
cargo run --locked -p edge-cli -- service \
  --directory "$EDGE_SERVICE_DIR" \
  --credential "$EDGE_SERVICE_DIR/owner.json" \
  --command examples/execution-service/enroll-control.json \
  --save-credential "$EDGE_SERVICE_DIR/sample-client.json"
```

Enrollment uses the owner credential. The CLI saves the new client credential privately,
never prints its token, and refuses to overwrite an existing file. Retrying an identical
owner enrollment returns the same credential; changing its scope or reactivating a revoked
principal is rejected. Use an intentionally new principal for a replacement enrollment.

Preview as the enrolled client:

```bash
cargo run --locked -p edge-cli -- service \
  --directory "$EDGE_SERVICE_DIR" \
  --credential "$EDGE_SERVICE_DIR/sample-client.json" \
  --command examples/execution-service/preview-volume.json
```

Inspect the returned `plan`, destination, `request_id` and `plan_sha256`. Preview does not
invoke the software device. Owner confirmation is a separate command document:

```json
{"method":"approve","principal":"sample-client","request_id":"COPY_REQUEST_ID","plan_sha256":"COPY_PLAN_SHA256"}
```

Replace the placeholders with the actual preview values, save the document to a JSON file
and pass it with `--command FILE` using `owner.json`. Do not approve an uninspected hash.
Then send this document using `sample-client.json`:

```json
{"method":"submit","request_id":"COPY_REQUEST_ID"}
```

Finally query the same ID with `{"method":"status","request_id":"COPY_REQUEST_ID"}`.
These manual command documents are deliberately explicit; the automated diagnostic is the
easier onboarding path. A consumer confirmation screen has not been implemented yet.

## Public Rust client

`edge_client::execution::ExecutionClient` connects with an explicit credential file:

```rust,ignore
use edge_client::execution::{Command, ExecutionClient};
let client = ExecutionClient::connect(service_directory, client_credential_path)?;
let preview = client.call(Command::PreviewVolume { percent: 40, budget_ms: 2000 })?;
// Inspect preview; the owner must confirm its exact request ID and plan hash separately.
```

Use `call(Command::...)` for the methods below and `close()` to prevent further calls.
`with_credential` also accepts an explicitly supplied credential, such as an enrollment
response. This SDK depends only on contracts/protocol/serialization and transport, not the
executor, database, adapter or model lab. It checks host identity and response bindings and
does not automatically retry submissions or issue approval.

## Permissions and methods

| Credential | Methods | Scope |
| --- | --- | --- |
| `inspect` client | `capabilities`, `preview_volume`, `status` | May preview, never approve or submit; status is limited to its own principal |
| `control` client | Above plus `submit`, `cancel`, `reconcile` | Only its own requests and the installed software output-volume action |
| Owner | `capabilities`, `enroll`, `peers`, `approve`, `inspect`, `recover`, `revoke`, `restart_adapter` | Administrative confirmation, enrollment and recovery; does not submit as a client |

Administrative selectors use `principal`; client submission never accepts a caller-supplied
principal. The authenticated token determines it. Approval also binds the request, exact
parameters, plan hash, policy and target state. A different client or stale plan cannot reuse it.
Both scopes currently describe the software reference action, not generic device permissions.

The new socket is `execution.sock`, with protocol `edge-execution-service.v1`. It is separate
from `preview.sock` and its saved-context protocol. Existing preview commands still cannot
approve or execute. A version-negotiated hello precedes each command; changing credentials
mid-connection is rejected. Frames are limited to 64 KiB, strings/parameters are bounded,
unknown fields and duplicate JSON keys are rejected. There are at most eight active
connections and eight waiting authority jobs; overload is explicit.

## Read results correctly

`submission.admission_durable` reports whether acceptance is durably recorded. A concurrent
retry may still report `persisting`; that is not execution success. Read status for the same
request ID. Progress, admission and operation are separate observations and can advance
while a response is assembled; the durable operation record supplies the effect outcome.

- No operation record can mean accepted but not yet claimed—not necessarily a lost request.
- `succeeded` refers to the simulated operation and its receipt, not physical observation.
- Cancellation before dispatch fences invocation. After dispatch it may return
  `possibly_dispatched`; it does not undo a completed action.
- An unknown operation remains unknown until receipt reconciliation gives stronger evidence.
- An RPC timeout or dropped response is **not cancellation**. Inspect the same request ID.
  Do not replace it with a new request merely to make an uncertain error disappear.
- After restart, use `status`/`reconcile` as the original still-enrolled principal, or owner
  `inspect`/`recover`. Durable records survive; previews and approvals do not. There is no replay.

Useful errors include `approval_required`, `repreview_required`, `not_found`, `conflict`,
`forbidden`, `unauthenticated`, `overloaded`, `capacity` and `persistence_uncertain` on the
wire. The CLI renders their enum names. A persistence-uncertain enrollment/revocation is
not a successful acknowledgement: inspect `peers`, preserve storage and resolve the failure.
Live access is fenced on a failed revocation write, but persistence must succeed before
revocation across a future restart can be relied on.

## Operational and security boundaries

- Credentials persist in private files: directory mode 0700, file/socket mode 0600. They are
  bearer secrets. The server checks Linux peer OS identity in addition to the token.
- This is **not per-application OS isolation**: malicious software running as the same user
  may read that user's files. Installed local applications are trusted. No TCP listener,
  remote pairing, TLS/relay transport, multi-user hosting or OS-protected keychain is claimed.
- Enrollment is bounded to 64 retained principals. Revoked entries are not silently removed.
  The authority retains 128 offers per lifetime and 10,000 durable admissions. At limits,
  new work is refused; long-running archival and byte quota policies remain unfinished.
- Do not delete or restore old copies of `enrollment.json`, credentials, the journal or
  device database to clear a fault. Stale backups can invalidate revocation/deduplication
  evidence; safe restore fencing, key rotation and a supported rollback procedure are pending.
- Ctrl-C stops the host process, not a physical action. Restart preserves uncertainty and
  never resumes work. Graceful system-service shutdown/installation and soak testing remain pending.
- Adapter I/O and framing are bounded; pathological filesystem calls cannot be hard-preempted.
  The simulator child is trusted code, not an OS security sandbox.

Next: durable event delivery and lifecycle/packaging tests, then independent security and
adopter checks. Native adapters and other platforms still require their own evidence.
