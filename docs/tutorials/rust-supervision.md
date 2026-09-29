# Approve and execute through a supervised software adapter

[Documentation home](../README.md) | [Preview service](rust-local-service.md) | [Roadmap](../roadmap.md)

This contributor example isolates one Rust execution layer. The host owns approval and the journal; a
separate child process owns the software device. If that process hangs or disconnects, the
host stops waiting, preserves the uncertain operation and requires explicit recovery.

**This changes a simulated volume value, not your computer's audio.** It uses no model,
native audio API, physical device or remote service. The original saved-context socket remains
preview-only. The newer [execution service](rust-execution-service.md) is separate; for first
use, follow the [SDK quickstart](../getting-started.md).

## Run everything automatically

In Linux/WSL, from the repository root:

```bash
source "$HOME/.cargo/env"
bash scripts/test-rust-supervision.sh
```

The script builds the host/worker, runs fault tests, then demonstrates:

1. A preview cannot execute without approval.
2. The test program confirms the exact preview fingerprint.
3. The adapter commits one software write, then deliberately hangs before acknowledging it.
4. The supervisor stops waiting, terminates that worker and records unknown.
5. Retrying returns the existing unknown operation without another invocation.
6. An explicit adapter restart does not replay anything.
7. Reconciliation confirms the stored receipt. The write count is still one.

It leaves report.json, the journal and simulator database in the printed evidence directory.
It also drives the real owner console through preview, rejected unapproved execution, exact
confirmation, execution, status, replay and cancellation. That second session is retained in
the adjacent console directory.
Each run uses a new directory; existing journals are never deleted or overwritten. The script
approves its own known fixture as test code. It is not independent human approval, model
accuracy, a performance benchmark or physical qualification. Python 3 locates the Cargo
build directory and drives the console diagnostic; the running host/adapter do not require Python.

## Try the owner console

Build both binaries, then start a session in a dedicated Linux directory:

```bash
cargo build --locked -p edge-host -p edge-simulator --bins
cargo run --locked -p edge-host -- software-session --directory "$HOME/.edge-delegate-software-session"
```

The companion worker binary must be beside the host binary. Do not use a preview-service
directory, a Python journal directory or /mnt/d for this private Linux session storage.

At the software prompt, enter:

```text
preview 40
```

Read the returned plan: destination, action, percent, request ID and plan_sha256. Copy the
actual fingerprint from this preview, then enter `approve ` followed by that fingerprint.
Approval alone does not act. Finally enter:

```text
execute
```

The result should be succeeded with value 40. That value belongs only to the software device.
Entering execute again returns the same operation record, without an additional write.

| Command | Meaning |
| --- | --- |
| `preview 40` | Observe software state and propose a new 40-percent operation; no invocation |
| `approve PLAN_SHA256` | Confirm the exact currently pending preview; recheck its binding |
| `execute` | Submit the approved request, or retrieve its previously recorded outcome |
| `status REQUEST_ID` | Read the durable request record, even when the adapter is unavailable |
| `cancel REQUEST_ID` | Revoke a pending preview, or retain uncertainty for previously dispatched work; never undo an effect |
| `restart-adapter` | Kill/reap the old child, start a new one and check identity; never resubmit an operation |
| `reconcile REQUEST_ID` | Ask for the receipt of an uncertain operation; never invoke it again |
| `quit` | Close the session and stop/reap its adapter |

Use the actual request ID displayed by preview, not the literal REQUEST_ID. A null status
means no durable operation record exists. Cancelling an undispatched in-memory preview also
returns null: the preview was removed, and no operation had been claimed or invoked.

A new preview supersedes the previous in-memory preview and revokes its approval. It does
not erase any executed/uncertain journal record. Preserve uncertain request IDs for recovery.
The preview must be confirmed within 60 seconds; the approval token then lasts at most
60 seconds. Repeated confirmation does not extend an existing token. Restart loses pending
previews and invalidates journal approvals; it never resumes unfinished work.

## How the boundary works

```text
Trusted owner console
  -> fresh software observation -> deterministic preview -> exact hash confirmation
  -> journal claim + dispatch intent
  -> private inherited framed channel -> supervised simulator process
  <- receipt or uncertain outcome
```

The worker receives typed operations and a remaining duration, not an authorization token,
model-generated command line or host monotonic timestamp. It does not own the host journal.
The supervisor checks response identity/version and validates returned data. A transport
failure poisons that channel: no further calls use it until explicit restart.

The worker has a fixed installed executable and database path. Its environment is cleared;
the inherited private channel avoids a listening dispatch endpoint. Linux also terminates
the child when its spawning parent dies, including the startup race check. This limits orphan
workers but does **not** prove a dispatched effect did not finish.

The worker is trusted installed code running as the same user. It is **not sandboxed** against
reading unrelated files or opening the network. Environment clearing/process separation is
not a security boundary against malicious code. Do not replace it with an untrusted plugin.

## What remains unfinished

- This owner console is trusted embedding code, not a consumer app. The separate
  [execution service](rust-execution-service.md) implements scoped enrollment and execution
  IPC; it does not change the original non-executing preview socket.
- The console is synchronous: it cannot accept cancel while execute is running. Cancellation
  during execution requires the separate [scoped authority API](rust-authority.md), which
  has a bounded queue and out-of-band cancellation. That API is not yet exposed over IPC.
  Ctrl-C is process termination, not a confirmed no-effect cancellation.
- Adapter I/O has deadlines and hung workers are terminated. SQLite commits, process startup
  and pathological kernel I/O are not hard-preemptible; whole-request deadline qualification
  is still pending. A late/missing acknowledgement stays uncertain.
- Database locks serialize this software device. This does not establish global ownership
  for arbitrary native devices, nor migration, stale-backup fencing, quotas or physical safety.
- No planner process, native adapter, Windows/macOS supervisor or mobile lifecycle support
  is qualified by this Linux/WSL test.

The separate execution service now supplies enrolled transport clients and owner-only
confirmation. Durable events, lifecycle qualification and a consumer consent interface
remain pending.
