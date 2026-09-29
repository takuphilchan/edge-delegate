# Test approvals and recovery in the Rust simulator

[Foundation preview](rust-foundation.md) | [Roadmap](../roadmap.md) | [Repository layout](../repository-layout.md)

This is an experimental **software-only execution path**, separate from the Python runtime.
It changes a SQLite-backed simulated volume value, not your computer's audio. No model,
phone, remote service or physical adapter is involved. The example program itself acts as
the trusted test operator: it is not evidence of a human confirmation UI or authentication.

## Run the automated test

Install Rust using the [official guide](https://rust-lang.org/tools/install/) if cargo is not
available. The repository selects Rust 1.90.0. A C compiler is needed for bundled SQLite;
Windows native builds need the Rust guide's C++ build tools. In Linux/WSL, from the repository:

```bash
bash scripts/test-rust-recovery.sh
```

The script runs formatting, Clippy and all Rust tests, then demonstrates a lost acknowledgement.
It prints a new evidence directory and leaves both databases there. Do not delete real
journals to get around unknown outcomes. These newly generated test records are not live
device evidence or disk-backed performance measurements.

To run just the demonstration in Linux/WSL, supply a **new** directory whose parent exists:

```bash
cargo run --locked -p edge-simulator --example recovery -- "$HOME/edge-delegate-recovery-1"
```

The command refuses an existing directory instead of overwriting its records. Use a different
new directory for another run. On Unix, the journal directory is private (0700) and files
are private (0600); overly broad permissions and final-component symlinks are rejected.
In WSL, use the Linux filesystem (for example your Linux home), not a Windows-mounted
directory that cannot enforce those modes. On native Windows, provide a new path within
your private user directory; native ACL qualification remains pending.

## What the demonstration establishes

1. The trusted program compiles an explicit 40-percent request against fresh simulator context.
2. The journal issues an opaque approval bound to the principal and exact plan.
3. Claim and dispatch intent commit before adapter invocation.
4. The simulator commits the change and receipt, then deliberately loses the acknowledgement.
5. The gateway records **unknown**, not failed or succeeded.
6. Both owners close and reopen. Retrying returns the existing unknown record without invocation.
7. Reconciliation reads the simulator's durable receipt and confirms success.
8. The total software write count remains **one**.

Expected output includes:

```text
After lost acknowledgement: Unknown; software writes: 1
After restart and retry: Unknown; adapter invocations since restart: 0
After receipt reconciliation: Succeeded; total software writes: 1
```

Another automated fault commits an effect without a receipt. Reconciliation deliberately
keeps that result unknown, even though the current value looks right, and new work on that
target remains fenced. A desired state is not proof of which operation caused it.

## API and persistence boundaries

The core execution module defines Journal and Adapter ports. SqliteJournal implements the
journal, while the simulator implements the adapter. Core has no SQLite, filesystem or
platform dependency. This example embeds these components directly, without an execution service.

SqliteJournal::approve is a **trusted operator API**, not a remotely exposed method. The
embedding program must establish the principal; a user-supplied principal string is not
authentication. Approval tokens are random, stored only as hashes, bound to an exact plan
and principal, and expire after 60 seconds using monotonic elapsed time. Reopening the
journal invalidates all old approvals. Revocation/expiry is checked again at dispatch intent.

The schema has an application identity and version. Rust schema 1 upgrades to schema 2 with
a consistent pre-upgrade backup; unknown/legacy Python databases are rejected. This is not
a legacy migration. A per-journal file lock prevents two owners of that same
directory. It does **not** yet prevent two different journals from targeting the same real
device. Global device ownership and Windows permission qualification are host work.

On restart, a committed claim without dispatch intent becomes cancelled-before-dispatch.
A committed dispatch intent without a confirmed receipt becomes unknown. Terminal results
cannot be rewritten. No unfinished work resumes automatically. Failed receipt persistence
leaves dispatch intent available for later reconciliation.

## What is not finished

- A consumer approval UI. The newer software execution service supplies authenticated
  IPC and scoped enrollment; this direct-library example still trusts its embedding caller.
- Planner isolation and hard whole-request deadlines. The newer scoped authority and
  execution service implement durable admission, bounded queues and cancellation.
- Live native adapters, workflows and remote/phone control.
- Legacy journal import, stale-restore fencing, byte quotas and a supported downgrade procedure.
- Physical power-loss, disk-full qualification, field tests and independent review.

Current code checks monotonic deadlines at boundaries, caps adapter budgets and bounds
SQLite lock waits. It cannot preempt a hung synchronous adapter or blocking filesystem commit.
An error after dispatch may mean unknown outcome: look up/reconcile the same request ID,
never automatically replace it with a new request ID. Timeout is not proof that an effect stopped.

The newer [Linux supervised session](rust-supervision.md) adds a child-process software
adapter with bounded transport waits. It does not change this direct-library example or
establish execution-service scheduling, an OS sandbox or hard filesystem deadlines.

Fault tests include actual child-process exit before/after claim and dispatch intent; they
do not simulate a physical power cut. SQL trigger failures exercise failed claim/receipt
persistence; they are not a claim of complete real disk-exhaustion testing.
