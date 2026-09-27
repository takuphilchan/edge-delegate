# First production-roadmap batch: using the tooling

[Roadmap](roadmap.md) | [Evidence](qualification-status.md)

These foundations do not make the current model or gateway production-ready.

## Numeric challenge test

```bash
cd /mnt/d/project/edge-delegate
source /home/phil/.venvs/edge-model/bin/activate
bash scripts/test-numeric.sh
```

Loads the actual planner once and runs 36 numeric/non-action development cases through compiler,
validation and simulation. Checks calls, arguments, returns, state and status. Creates a new
report under artifacts/numeric, checkpoints every case and exits nonzero for failures. No
training, network model call or physical action. These author-written exposed cases are not
independent holdouts. Use --help for another artifact/plugin/settings; explicit decimal.v1 is required.

## Actual review, without rewriting the pilot

Give the reviewer REVIEW.md before PROPOSED-ANSWERS.md. The tool cannot authenticate people or
prove they followed that instruction. For each case, their submission JSON has exactly:

```json
{
  "stage": "blind",
  "actor": "actual-reviewer-identifier",
  "decision": {"task": "clarify", "parameters": {}},
  "rationale": "Reviewer supplies their actual reasoning.",
  "blind": true,
  "effects_reviewed": false
}
```

This is a format example, **not an answer or approval to copy**. Use the actual worksheet ID
and the reviewer's real submission file:

```bash
python -m edge_delegate_lab.review_history \
  --directory data/review/pilot-v2 --ledger data/review/pilot-v2/review.sqlite \
  append --record-id ACTUAL_RECORD_ID --submission ACTUAL_SUBMISSION.json
```

Then record adjudication with the owner's decision/rationale, followed by approval from the
original reviewer, with effects_reviewed true and blind false. Approval requires agreement with
the record and adjudication and binds complete context/effects. Original disagreements remain.
If labels/context change, create a new draft/version and review its new fingerprint. Never edit
historical snapshots or ledger events to make an approval fit.

After every pilot row has complete blind/adjudication/approval history:

```bash
python -m edge_delegate_lab.review_history \
  --directory data/review/pilot-v2 --ledger data/review/pilot-v2/review.sqlite \
  export --output data/review/pilot-v2-reviewed-1
```

The output directory must not exist. Original data stays untouched. Empty holdouts remain empty;
pilot review export is not training approval or a dataset freeze. SQLite guards accidental event
edits, not malicious file owners. Protect the ledger and its backups. This batch created no
actual reviewer submissions or approvals. Full near-duplicate, rights and freeze tooling remains pending.

## Public synchronous SDK

```python
from edge_delegate.application import GatewaySession
from edge_delegate.contracts import PlanningRequest

# planner, device and policy are caller-configured installed components.
# device must implement the deadline-aware gateway contract.
with GatewaySession(planner, device, policy, journal_path="gateway.sqlite") as gateway:
    request = PlanningRequest("unique-request-id", "Show the temperature.")
    preview = gateway.preview(request)  # reads context; no action/request reservation
    result = gateway.execute(request)   # explicit validation/execution
    health = gateway.status()
    recovery = gateway.reconcile(request_id=request.request_id)
```

The context manager checks adapter reachability and closes session ownership, not caller-owned
planner/device resources. It never deletes state. Loading/warmup remain caller-owned. Existing
edge_delegate_lab.gateway imports and handle retain the old result schema. Concurrent use of
one session is rejected rather than queued. status identifies this as unsupervised.

Still pending: spawned worker, service/client, global device-owner lock, queue, whole-request
deadlines and request cancellation. This API is not the planned service readiness contract.

## Candidate task packs

Use edge-delegate pack-check --manifest PATH to inspect without model loading or device actions.
The edge-task-pack.v1 manifest has exactly:

- schema_version, pack_id, catalog_version, decision_protocol, numeric_policy, plugin_id.
- files: artifact_manifest, settings, runtime_policy, catalog, evidence; each has a relative path
  and byte sha256, all inside the pack directory.
- compatibility: adapter_id, adapter_api, firmware_id, hardware_id.

Use bounded-task.v1, explicit decimal.v1, and the same numeric policy in settings. Catalog JSON
has version local-display.v1, tasks listing the three actions plus clarify/deny, and
parameter_semantics decimal.v1. Artifact files are checked against the installed plugin contract.
Runtime policy disables external delegation; evidence is qualification.v2, even when failed.

This verifies declared metadata/integrity, not live adapter/firmware compatibility, signatures,
or release readiness. It always returns qualified false. No pretend production pack was created.

## Qualification v2

Existing edge-delegate-lab qualify flags remain; --review-directory supplies actual reviewed
records. Omitting it fails review, regardless of a manifest review-complete boolean. Reports can
load up to a bounded 64 MiB; settings retain the smaller size limit.

Output separates evidence_gates_passed, qualified, developer_preview_qualified and
physical_device_qualified. All release flags stay false until the operational release evaluator
exists; this command does not evaluate security, installation, soak or independent sign-off.

New producers must instrument edge-outcome-evidence.v1 completeness/authorization/numeric
dispatch and edge-release-benchmark.v1's three runs of burst/idle_3s/idle_15s. Current generic
evaluation and six-query benchmarks remain ineligible. Merely changing their version strings
does not establish the missing measurements.
