# How a request becomes an operation

[Documentation home](../README.md) · [Try the service](../tutorials/rust-execution-service.md)

Edge Delegate separates proposing an action from authorizing and executing it. This page uses
the experimental Rust software-volume service as an example. The Python runtime has its own
[architecture and contracts](../system-architecture.md); do not mix its wire formats with the
Rust service.

## The participants

| Participant | Responsibility |
| --- | --- |
| Client | Request a preview, submit approved work, and inspect its own results |
| Owner | Enroll clients, confirm exact plans, revoke access and administer recovery |
| Host | Authenticate callers, enforce permissions and approval, and own durable execution |
| Device adapter | Carry out the installed operation and provide evidence about its result |

The current adapter is a separate software process, not your OS audio driver. The owner and
client have separate credentials. There is no consumer consent screen yet: owner approval is
an explicit API or CLI operation.

## Follow one request

1. **Enroll.** The owner creates a client identity with an `inspect` or `control` scope.
   Enrollment alone does not authorize a write.
2. **Preview.** The client requests volume 40. The host produces a plan identifying the
   output, action, value and relevant state. Nothing is dispatched.
3. **Approve.** The owner inspects the plan and confirms its request ID and fingerprint.
   The fingerprint binds approval to the exact plan; it is not an encryption key.
4. **Submit.** The client submits that request ID. The host checks the bound approval and
   records admission before acknowledging it as durable. Queueing is not completion.
5. **Execute.** The authority rechecks conditions, records its intent to dispatch and calls
   the adapter within the remaining budget.
6. **Inspect.** The client reads the durable operation and receipt. If evidence is missing,
   the result remains uncertain until reconciliation establishes more.

Permission answers **“may this client request this class of work?”** Approval answers
**“was this exact plan confirmed?”** Both matter. A client cannot impersonate another client
by supplying its name in a submission.

## Why a timeout is not a failed action

Suppose the adapter changes its software state, but its response is lost. The host cannot
truthfully say the action failed. Issuing a new request could repeat an action that already happened.

Instead, keep the original request ID and inspect its record. **Reconciliation** asks for
evidence about the existing operation; it is not another attempt to perform it. A durable
adapter receipt can establish completion. Observing the desired value alone does not prove
which request caused it.

The **journal** is the persistent execution record. Deleting it to clear an error also deletes
evidence needed for recovery and duplicate detection. Preserve it, including unknown outcomes.

## Retry, cancellation and restart are different

| Situation | What to do | What not to assume |
| --- | --- | --- |
| Submission response is lost | Inspect the same request ID; use its existing record | A disconnect cancelled the request |
| Duplicate submission in the same live session | Reuse the identical request ID | A new ID is a harmless retry |
| Cancel before dispatch | Inspect the returned cancellation disposition | Every cancellation means no action happened |
| Cancel after dispatch | Preserve uncertainty and reconcile | Cancellation rolls the action back |
| Host restarts | Inspect/reconcile durable records with the original enrolled identity | Previews, approvals or unfinished work resume |

The system does not promise exactly-once physical execution. Its goal is to prevent blind
replay and report the evidence it has. The current software tests do not qualify real hardware.

## Where models fit

A model may help propose a supported action. It must not grant permissions, supply executable
code or bypass validation. The current Rust service accepts structured software-volume commands;
it does not run a language model. The separate [Python lab](../model-lifecycle.md) trains and
evaluates planners for a different task catalog.

Next: [execute one approved request](../tutorials/rust-execution-service.md), or look up
[methods and result semantics](../reference/execution-service.md).
