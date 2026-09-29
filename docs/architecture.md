# How Edge Delegate fits into an application

[Documentation](README.md) · [Quickstart](getting-started.md) · [Repository layout](repository-layout.md)

Edge Delegate handles the part between **“I want this action”** and **“here is what happened.”**
Your application supplies the user experience. An installed adapter supplies the device-specific
operation. The execution host sits between them and owns permission checks and execution records.

## The running system

The current Rust service has three processes/roles, with a separate owner credential for approval:

```text
Your application                         Owner's confirmation
  public Rust client                       exact plan approval
          │                                        │
          └──────────── local socket ───────────────┘
                              │
                     Execution host
                  permissions + approvals
                  request queue + journal
                              │
                     Adapter process
                    software volume state
```

The socket is interprocess communication (IPC) on the same machine. It is not an HTTP endpoint
or a connection to a remote phone. The adapter currently changes a software value; native
audio and other device drivers remain future work.

| Part | What it owns | What it must not do |
| --- | --- | --- |
| Application/client | Request entry, preview presentation and result display | Bypass approval or impersonate another client |
| Owner interface | Enrollment and confirmation of an exact plan | Give ordinary clients the owner credential |
| Host | Authentication, policy, queue, approval checks and durable operation records | Treat a model proposal as permission |
| Adapter | A declared device operation and evidence about its outcome | Invent new actions from arbitrary text |

## One operation, from start to finish

For the quickstart's volume request:

1. The client asks for a preview of `audio.volume.set` with percent `40`.
2. The host constructs a plan bound to the selected output and current relevant state.
3. The owner approves that exact plan. A changed target or value requires another preview.
4. The client submits the request ID. The host records acceptance before acknowledging it
   as durable. Accepted work is not yet a completed action.
5. Before dispatch, the host checks permission, approval, cancellation and the remaining budget.
   It records intent before calling the adapter.
6. The adapter returns a receipt. The host records it so clients can inspect the same operation
   after a disconnect or restart.

This is why preview, approval, submission and completion are separate API operations. The
quickstart example puts the steps in one program for learning; it does not merge their credentials.

## What happens when the response is lost?

If the adapter completed the write but its response never arrived, the host cannot safely call
that a failed action. It retains an unknown outcome. Reconciliation looks for a receipt for
the **existing operation**; it does not send the write again.

The journal is the persistent execution record, not a cache to delete when a test fails.
Cancellation after dispatch is not undo. Restart does not replay a pending queue.
See [execution and recovery concepts](concepts/execution.md) for the detailed distinctions.

## Where interpretation belongs

Structured controls already know the target, action and value. Natural-language input needs
an interpreter to propose those values first. That proposal must then pass through the same
execution checks; an interpreter cannot grant itself permissions.

No language model is attached to the current Rust service. The separate Python lab trains
and evaluates temperature/display planners. Those artifacts do not automatically understand
the Rust volume action, lights or application controls.

## Why both Rust and Python exist

The project is migrating incrementally, not replacing the existing runtime in one rewrite.

| Implementation | Available role | Relationship to the Rust service |
| --- | --- | --- |
| Rust host and client | Authenticated local execution against the software-volume adapter | Current service development path |
| Python runtime | Existing light, temperature/display and extension examples | Separate runtime and journal; not a socket client |
| Python lab | Data review, model training and evaluation | Development tooling, not a Rust runtime dependency |

For code ownership, use the [repository guide](repository-layout.md). For the existing Python
request path, use [Python architecture](system-architecture.md).

## What is not in this diagram yet

The intended product adds native adapters, a companion app, paired devices and an optional
relay. Those are [planned components](roadmap.md), not hidden services to enable. The current
host also still needs production lifecycle, backup/restore, retention and security qualification.
Check [current status](qualification-status.md) before choosing a deployment.
