# Run your first approved operation

[Documentation](README.md) · [How it works](architecture.md) · [API reference](reference/execution-service.md)

Start a local service, inspect a request, and decide whether to execute it. This walkthrough
uses a small Rust application that sets a simulated output to 40 percent. It does not change
your computer's audio and needs no model or physical device.

Want a real stored result rather than a software-device example? The separate
[v2 notes walkthrough](reference/execution-service.md#v2-notes-service) creates and retrieves
an app-owned note through an authenticated client. Use its own directory and credentials;
the v1 steps below remain unchanged.

The example is deliberately owner-run: you hold both the owner credential and a separately
enrolled client credential. It demonstrates the API sequence, not a finished approval UI.

## Before you start

Use Linux or Ubuntu in Windows Subsystem for Linux (WSL), not Windows Git Bash. You need Git,
Rust installed with rustup, and a C compiler/linker for SQLite. Check with `git --version`,
`cargo --version` and `cc --version`. If rustup is installed but Cargo is missing from your
shell, run `source "$HOME/.cargo/env"`.

The checkout pins Rust 1.90.0. Your first build downloads its toolchain and dependencies;
the running service needs no internet connection.

If you do not have the repository yet:

```bash
git clone https://github.com/takuphilchan/edge-delegate.git
cd edge-delegate
```

Otherwise, open a terminal at your existing repository root. Do not clone over an existing
checkout. Keep the service's state on the Linux filesystem, not under `/mnt/d`.

## 1. Start the service

In **terminal A**, run:

```bash
cargo build --locked -p edge-host -p edge-cli -p edge-simulator --bins
cargo build --locked -p edge-client --example approved_request
mkdir -p "$HOME/.local/state"
cargo run --locked -p edge-host -- serve-software \
  --directory "$HOME/.local/state/edge-delegate-quickstart"
```

Wait for `READY: authenticated SOFTWARE execution service.` Leave this terminal open.
The host is now waiting for clients; silence after READY is expected.

The directory contains credentials, the operation journal and software-device state. Use it
only for this service. Do not delete it to recover from an error or share its contents publicly.

## 2. Preview and decide

In **terminal B**, at the same repository root:

```bash
cargo run --locked -p edge-client --example approved_request -- \
  "$HOME/.local/state/edge-delegate-quickstart"
```

The application enrolls a client named `sdk-example`, obtains a preview and prints the full
plan. Check its target and parameters. The important fields are:

| Field | Expected value |
| --- | --- |
| Action | `audio.volume.set` |
| Endpoint | `output` |
| Parameter `percent` | Integer `40` |
| Authority | The identity of the local software service |

It then prompts:

```text
Type approve to set the simulated output to 40%, or press Enter to leave it unchanged:
```

**To decline**, press Enter. It prints `Not submitted. No device action was requested.`
Enrollment and the preview still occurred, but the device value is unchanged.

**To proceed**, type `approve` and press Enter. Do this within 60 seconds of the preview.
The example confirms the exact plan using the owner credential, then submits using the client
credential. It does not treat enrollment as approval or ask the client to approve itself.

The example prints a request ID before submission. Keep that ID if an error occurs.

## 3. Read the outcome

On success, the final line is:

```text
Succeeded: simulated output is 40%; receipt recorded.
```

The preceding operation record includes the request ID, state `succeeded` and a receipt.
A receipt is the adapter's recorded result. Here it describes software state, not a physical
measurement or a native audio change.

This completes your first operation. To stop the host, press Ctrl-C in terminal A. Its records
remain on disk. Restarting the same host does not resume unfinished requests automatically.

Each invocation of this example creates a **new request**. It is appropriate to run it again
after declining or confirming success, if you intentionally want another request. It is not
a retry tool for an uncertain operation.

## If something goes wrong

| Symptom | Next action |
| --- | --- |
| Cargo or a compiler is missing | Finish the Rust/Linux build-tool setup before running the commands. |
| The service waits after READY | Leave it running; use terminal B for the example. |
| Socket not found | Check that both terminals use the exact same service directory. |
| Directory permissions rejected | Use the dedicated Linux path above; do not weaken the checks. |
| Preview/approval expired | If you have not submitted, start a fresh preview and decide within 60 seconds. |
| Enrollment conflict | `sdk-example` may have been revoked or enrolled differently. Do not overwrite its credentials; use the [manual enrollment guide](tutorials/rust-execution-service.md). |
| Submission/polling fails, or outcome is unknown | Inspect the printed request ID. Do not rerun the example or delete its journal to clear the error. |

To inspect uncertain work, create a JSON command file containing your actual request ID:

```json
{"method":"inspect","principal":"sdk-example","request_id":"REPLACE_WITH_PRINTED_REQUEST_ID"}
```

Save it as `inspect.json`, then run from terminal B:

```bash
cargo run --locked -p edge-cli -- service \
  --directory "$HOME/.local/state/edge-delegate-quickstart" \
  --credential "$HOME/.local/state/edge-delegate-quickstart/owner.json" \
  --command inspect.json
```

Read [results and recovery](reference/execution-service.md#results-and-recovery) before
attempting reconciliation. A timeout does not mean the action was cancelled.

## Use this in your application

Read the [complete example source](../crates/edge-client/examples/approved_request.rs). It uses
only the public client API: connect, enroll, preview, approve, submit and status. Enrollment
and owner approval belong in trusted setup/consent code; ordinary applications should get
only their enrolled client credential, never `owner.json`.

Next, read [how the pieces fit](architecture.md) and the
[client reference](reference/execution-service.md). To inspect every protocol step manually,
use the [CLI walkthrough](tutorials/rust-execution-service.md).

For automated verification, `bash scripts/test-rust-execution.sh` exercises the service and
examples, including non-approval and recovery. Its test-program approvals are not human review.
