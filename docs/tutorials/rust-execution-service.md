# Call the execution service from the CLI

[Documentation home](../README.md) · [API reference](../reference/execution-service.md) · [Concepts](../concepts/execution.md)

New to the project? Start with the [SDK quickstart](../getting-started.md). This page is the
lower-level walkthrough for readers who want to inspect each JSON command and credential.

Learn how a client previews an operation, an owner approves it, and the host records its
execution. You will set a **software** volume endpoint to 40 percent and inspect its receipt.
Your computer's audio does not change. No model, GPU, physical device or runtime cloud connection
is involved.

This tutorial covers the experimental Linux/WSL service. It is not an installation guide for
a production daemon or a cross-platform companion app.

## Before you start

Use a Linux terminal or Ubuntu under Windows Subsystem for Linux (WSL), not Windows Git Bash.
You need:

- A checkout of this repository, with your terminal at its root.
- Rust/Cargo available through rustup; the checkout pins Rust 1.90.0.
- A C compiler and linker for bundled SQLite.
- Python 3 for the diagnostic and JSON preparation.
- A private directory on the Linux filesystem for sockets and state, not `/mnt/d`.

Check the tools with `cargo --version`, `cc --version` and `python3 --version`.
If rustup is installed but Cargo is not found, run `source "$HOME/.cargo/env"`.
The first build downloads dependencies; subsequent runtime calls are local.

## Test the complete flow automatically

Run this first:

```bash
bash scripts/test-rust-execution.sh
```

The diagnostic builds the binaries, runs service tests, then drives the actual host and CLI
through enrollment, rejected self-approval, owner confirmation, submission, retry, restart
and revocation. The test program approves its own fixture; this is not independent human consent.

**Success checkpoint:** output includes `PASS: exactly one recorded software write.` and a
report path. The script stops the host processes it started and preserves the evidence.
The directory also contains private credentials: do not upload or share it wholesale.

Continue below to perform the sequence yourself, or go directly to the
[method reference](../reference/execution-service.md#methods) to integrate a client.

## 1. Build and start the host

In **terminal A**, at the repository root:

```bash
cargo build --locked -p edge-host -p edge-cli -p edge-simulator --bins
mkdir -p "$HOME/.local/state"
cargo run --locked -p edge-host -- serve-software \
  --directory "$HOME/.local/state/edge-delegate-service"
```

**Success checkpoint:** the host prints `READY: authenticated SOFTWARE execution service.`
Leave this terminal running. Waiting for connections is expected; it is not stuck.

On first use, the host creates a private service directory, owner credential, enrollment
registry and software authority. Restarting the same service reopens those records. Do not use
a directory belonging to the Python runtime, saved-context preview service or owner console.

## 2. Enroll a client

Open **terminal B**, also at the repository root. Run the remaining commands there:

```bash
EDGE_SERVICE_DIR="$HOME/.local/state/edge-delegate-service"
cargo run --locked -p edge-cli -- service \
  --directory "$EDGE_SERVICE_DIR" \
  --credential "$EDGE_SERVICE_DIR/owner.json" \
  --command examples/execution-service/enroll-control.json \
  --save-credential "$EDGE_SERVICE_DIR/sample-client.json"
```

**Success checkpoint:** the reply includes `"enrollment_saved": true` and principal
`sample-client`. The CLI saves the token privately; it does not print it.

Only the owner can enroll. The new client has a control scope, but cannot approve its own
writes. If this client was already enrolled and its file is present, skip enrollment. Do not
overwrite or delete credentials to bypass a conflict. Revoked clients need an intentionally
new enrollment, not silent reactivation.

## 3. Preview the operation

Read steps 3–5 before running them: the preview must be confirmed while fresh, and approval
expires after 60 seconds. No operation has been submitted at this point.

```bash
cargo run --locked -p edge-cli -- service \
  --directory "$EDGE_SERVICE_DIR" \
  --credential "$EDGE_SERVICE_DIR/sample-client.json" \
  --command examples/execution-service/preview-volume.json \
  > "$EDGE_SERVICE_DIR/preview.json"
python3 -m json.tool "$EDGE_SERVICE_DIR/preview.json"
```

**Success checkpoint:** `kind` is `preview`. Inspect the plan: action `audio.volume.set`,
endpoint `output`, percent value 40, and the intended authority. Keep its `request_id` and
`plan_sha256`. No action has run.

Prepare the command files from that response:

```bash
python3 - "$EDGE_SERVICE_DIR" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
preview = json.loads((root / "preview.json").read_text())
assert preview["kind"] == "preview"
request_id = preview["request_id"]
approval = {
    "method": "approve",
    "principal": "sample-client",
    "request_id": request_id,
    "plan_sha256": preview["plan_sha256"],
}
(root / "approve.json").write_text(json.dumps(approval))
for method in ("submit", "status"):
    (root / f"{method}.json").write_text(
        json.dumps({"method": method, "request_id": request_id})
    )
PY
```

This only writes local command documents. It does not approve or submit anything.

## 4. Approve as the owner

After inspecting the preview, explicitly confirm its exact plan:

```bash
cargo run --locked -p edge-cli -- service \
  --directory "$EDGE_SERVICE_DIR" \
  --credential "$EDGE_SERVICE_DIR/owner.json" \
  --command "$EDGE_SERVICE_DIR/approve.json"
```

**Success checkpoint:** `kind` is `confirmed`, with the same request ID and plan fingerprint.
Approval alone does not dispatch. Using the client credential for this command is rejected.

If the preview expired before submission, obtain a fresh preview and prepare new command files.
If you already submitted, inspect that request's status first; do not overwrite its identity
to work around an uncertain outcome.

## 5. Submit as the client

```bash
cargo run --locked -p edge-cli -- service \
  --directory "$EDGE_SERVICE_DIR" \
  --credential "$EDGE_SERVICE_DIR/sample-client.json" \
  --command "$EDGE_SERVICE_DIR/submit.json"
```

**Success checkpoint:** `kind` is `submission` and `admission_durable` is true for the normal
first submission. This means acceptance was recorded, not that the effect has completed.

## 6. Inspect the result

```bash
cargo run --locked -p edge-cli -- service \
  --directory "$EDGE_SERVICE_DIR" \
  --credential "$EDGE_SERVICE_DIR/sample-client.json" \
  --command "$EDGE_SERVICE_DIR/status.json"
```

**Success checkpoint:** `operation.state` becomes `succeeded`, with a software-adapter receipt.
If the operation is still queued/running or null, repeat this **status** command. Do not create
a new request to poll.

A timeout does not prove failure or cancellation. Preserve the ID and use
[results and recovery](../reference/execution-service.md#results-and-recovery) if the outcome
is unknown. Do not delete the journal.

## 7. Stop and reopen

Press Ctrl-C in terminal A. Start the same host command again, then repeat the status command
in terminal B. The result remains inspectable. Previews, approvals and unfinished work are
not automatically resumed.

Keep the service directory if you need its credentials and execution history. This tutorial
does not include deletion, stale-backup restoration or a production service manager.

## Troubleshooting

| Symptom | What to do |
| --- | --- |
| `cargo: command not found` | Load the rustup shell environment if installed; check that you are in Linux/WSL. |
| C compiler/linker missing | Install your Linux development toolchain before building bundled SQLite. |
| Host prints READY and then waits | Expected. Leave terminal A running and use terminal B for clients. |
| Socket not found / connection refused | Confirm the host is running and both terminals use the same Linux directory. |
| Private-directory or permission error | Use a dedicated Linux filesystem directory. Do not weaken permissions or reuse another journal. |
| Credential output already exists | For the same existing active client, skip enrollment. Do not overwrite its file. |
| `ApprovalRequired` | Confirm the exact preview with the owner credential, then submit as the client. |
| `RepreviewRequired` | Inspect any submitted work first. If none was submitted, preview again and confirm promptly. |
| `Unauthenticated` / `Forbidden` | Check credential, service identity, revocation and method scope. Pairing is not implemented. |
| `NotFound` after restart | Old offers are not restored. Use durable status/reconciliation, not an old submit command. |
| Timeout or unknown outcome | Inspect the same request ID; reconcile existing evidence. Never blindly replay a mutation. |

## Next steps

- Integrate the [public Rust client and methods](../reference/execution-service.md).
- Understand [permission, approval and uncertainty](../concepts/execution.md).
- Review [security and storage limits](../reference/execution-service.md#security-and-storage)
  before using the service beyond this tutorial.
- Check [qualification status](../qualification-status.md) for deployment evidence.

The reference endpoint and these tests establish a software integration boundary, not native
audio control or production qualification.
