# Reconcile an uncertain operation

[Documentation home](../README.md) | [Result meanings](../reference/results.md)

Use this when execution returned execution_unknown or a process stopped around dispatch.
A lost acknowledgement can mean the action completed but its reply was lost.

## 1. Preserve identity and evidence

Keep the gateway journal, device database/receipts, original request and configuration.
Do not delete databases, rename a replacement device to match the old one, issue a new request
ID to bypass a block, or repeatedly call execute until something succeeds.

For structured clients, store the original ControlRequest.to_dict() before execution.
Treat stored request arguments and journals as sensitive. Use the same device registration,
catalog and policy when reopening the application. Configuration drift must fail, not be
silently rebound.

## 2. Query receipts using the original target

With the original ready ControlSession and a persisted request loaded as a dictionary:

~~~python
from edge_delegate.contracts.control import ControlRequest

original = ControlRequest.from_dict(saved_request)
report = control.reconcile(
    target=original.target,
    request_id=original.request_id,
)
~~~

This is a fragment for the application that owns saved_request and control, not a standalone
command. Do not resolve a new name and assume it refers to the old device. See the
[complete SDK example](../reference/control-sdk.md#small-complete-example) for construction.

ControlSession reconciliation dispatches no device actions. A separate temperature gateway
uses its own GatewaySession reconciliation path; the lab run client's help documents its
interactive receipt commands. There is no core edge-delegate reconcile CLI or control cancel
API yet; see the [actual command surface](../reference/cli.md).

## 3. Interpret and stop where necessary

| Reconciliation status | What to do |
| --- | --- |
| reconciled | Inspect each receipt; it establishes recorded operation outcomes, not complete task success |
| unknown | Keep the device blocked for unresolved work; investigate adapter/device evidence |
| not_found | No matching operation record found; not proof that a physical action never happened |

No blind write replay occurs. Reconciliation does not run missing dependent steps or prove a
whole user task finished. Before submitting new work, establish what happened and decide what
is still required. Preserve the original record; do not use a new ID to replay uncertain intent.

## Limits of the demonstration

The light emulator commits software state and receipts in one SQLite transaction. Physical
hardware may not be able to do this. Successful receipt lookup is not proof that a light was
visible or a sensor measurement accurate. Cancellation after dispatch cannot promise undo.

The production backup/restore, migration and stale-restore fencing procedures are roadmap work.
Do not invent a safe restore by copying only one live SQLite file; the gateway and device must
retain consistent identity and receipt history. No production recovery procedure is qualified.
