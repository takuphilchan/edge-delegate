# Connect to the Rust preview host

[Documentation home](../README.md) | [Roadmap](../roadmap.md) | [Software recovery](rust-recovery.md)

This is the first client/server path in the Rust redesign. A client connects to a local host,
authenticates, discovers the host's saved catalog and asks it to preview a structured request.
The result is the same as the offline preview, but the compiler runs in a separate host process.

**Nothing executes.** This host does not load a model, contact a device, issue approvals,
open a journal or change your computer's volume. The example catalog describes a fictional
audio endpoint. It is not discovery of your real audio hardware.

## Fastest test: one command

Use Linux or WSL, from the repository root. Rust 1.90.0 and Python 3 are required; Python is
used only to compare the demonstration reports, not by the Rust host or client.
If Rust was just installed, refresh your current shell:

```bash
source "$HOME/.cargo/env"
bash scripts/test-rust-service.sh
```

The script builds the two binaries, starts a host, inspects its capabilities, previews the
40-percent fixture through the client, and compares that result with offline preview. It
prints PASS, stops the host automatically and leaves the reports in the printed temporary
directory. No queries need to be entered manually. Cargo may download locked dependencies
on the first build; the running service makes no network or external-model calls.

The host directory contains a private client credential. Do not upload client.json with the
reports. A new host start rotates that credential. Temporary storage is not performance or
disk-backed deployment evidence.

## Explore it with two terminals

First terminal, from the repository root:

```bash
cargo run --locked -p edge-host -- serve-preview --directory "$HOME/.edge-delegate-preview" --context conformance/contracts/preview-v2/context.json
```

Wait for READY. The process then waits for connections; this is normal, not a stuck model.
Leave that terminal running. Use a dedicated directory on the Linux filesystem, not a legacy
journal directory or /mnt/d, whose permissions may not satisfy the private-directory checks.

Second terminal, also from the repository root:

```bash
cargo run --locked -p edge-cli -- capabilities --directory "$HOME/.edge-delegate-preview"
cargo run --locked -p edge-cli -- preview --request conformance/contracts/preview-v2/request.json --directory "$HOME/.edge-delegate-preview"
```

Expect execution_attempted: false and a proposed plan requiring approval. There is deliberately
no approve or execute service method yet. Ctrl-C in the first terminal stops the host. A stale
socket after interruption is recovered on the next start only after exclusive ownership is
acquired; regular files and symlinks are not removed to make startup succeed.

The host reads its saved context once at startup. Editing that file does not update a running
host. The returned target generations describe the saved fixture, not fresh device state.

## Rust SDK

The workspace package edge-client depends only on contracts and protocol, not core execution,
storage or the model lab. Its current Linux API is:

```rust,ignore
use edge_client::local::LocalClient;
use edge_contracts::ControlRequest;
use std::path::Path;

let mut client = LocalClient::connect(Path::new("/absolute/private/host-directory"))?;
let catalog = client.capabilities()?;
let request = ControlRequest::parse(request_json_bytes)?;
let preview = client.preview(&request)?;
client.close();
```

This is an API sketch: use your own absolute directory and validated request bytes. Runnable
cross-process usage is the script above. The package is not published. Each call uses a fresh
connection and version negotiation. There are no automatic retries. An old client fails after
host restart; reconnect explicitly to reload the rotated credential.

Python/TypeScript clients, Windows named pipes and macOS transport are still pending. On those
desktop platforms, the existing offline Rust preview remains separate from this Linux service.

## Authentication and limits

- Linux verifies both peers have the current effective user ID using OS peer credentials.
- The directory must be private and owned by that user. Socket/credential permissions exclude
  other users; symlink paths are rejected at the checked endpoint.
- Owner startup generates a random credential mapped to the host-defined local-owner principal.
  Clients cannot supply a principal or confer permissions on themselves. Authentication enables
  inspection only; it is not a device-control grant or human approval.
- Credentials rotate on restart and are not printed or included in diagnostics.
- Messages use strict JSON with duplicate/unknown-field rejection and a 64-KiB frame cap.
- The first message negotiates protocol version 1. Incompatible versions do not downgrade.
- At most eight connections are handled concurrently, with no application waiting queue.
  Excess connections receive overloaded. This is a preview-connection limit, **not** the planned
  execution scheduler with one active request and eight waiting requests.
- A connection has a two-second read/write budget shared across partial frames and negotiation.
  Slow partial messages cannot renew the budget indefinitely. This is not a hard-real-time
  execution deadline or an OS scheduler guarantee.

All programs running as the same user are in the trust boundary: they can read that user's
credential file. This is not per-application isolation, multi-user enrollment, remote pairing,
TLS or protection against a compromised owner account. The host does not listen on TCP.

## Troubleshooting and next boundary

Missing cargo: source the Rust environment above or reopen WSL. Missing socket: start the host
and use exactly the same directory in both terminals. Permission error: use a new dedicated
private directory on the Linux filesystem; do not weaken checks or delete journals. Already
owned: stop the other preview host first. Authentication failure after restart: reconnect the
client; never paste a token into the command line.

The separate [supervised owner session](rust-supervision.md) now runs a software adapter child,
but does not expose its approval methods here. The next work is the execution authorization
boundary: independently enrolled client scopes, trusted consent, whole-request deadlines and
asynchronous cancellation. The existing [library recovery example](rust-recovery.md) cannot simply
be exposed as unrestricted RPC. Native control and the assistant application follow those checks.
