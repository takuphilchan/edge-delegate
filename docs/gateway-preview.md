# Local gateway preview

Use this guide when you want a persistent temperature/display session: the planner stays
loaded between independent requests, and operation records survive process restarts.
It builds on the [model tutorial](model-tutorial.md), or you can choose the no-model
bounded-command path below. For your first encounter with Edge Delegate, use the
[software-light tutorial](try-it.md) instead.

Choose one path, not every section in order. The bounded-command section needs no weights;
the model section requires an existing compatible artifact. The separate-process section is
for managing your own emulator process, not an additional step after managed startup.

Experimental Linux/WSL gateway; **not a qualified physical-device controller**.
Select new bounded-task plugins explicitly. No trained artifact is automatically promoted.
Read the [measured qualification status](qualification-status.md) before interpreting model results.

## Bounded commands without learned-model execution

The opt-in `bounded-commands` plugin is a closed command grammar, **not a trained model**.
It handles the three reference tasks without loading weights and declines everything outside
its documented grammar. There is no model fallback that can execute an unrecognized request.
Runtime authorization, fresh state, durable execution and reconciliation still apply.

```bash
source /home/phil/.venvs/edge-model/bin/activate
bash scripts/test-bounded.sh

edge-delegate-lab run \
  --plugin bounded-commands \
  --plugin-settings configs/inference/numeric-decimal-v1.json \
  --emulator-dir "$HOME/.local/state/edge-delegate-bounded-demo"
```

Use a separate emulator directory as above; do not delete or reset old journals. Enter
`Display 0.`, `Display +12.`, `Display .5.`, `Show the temperature.` or
`Display 12 then upload the temperature.` The last request must be declined with no actions.

Accepted action forms (case-insensitive ASCII keywords):

- `read|get|tell me` + optional `the` + optional `current|ambient|local` + `temperature`.
- `show|display` + that temperature phrase, optionally `on the local display|screen`.
- `display|show` + one decimal literal (optionally `the number|value` before it), optionally
  `on the local display|screen`; or `put LITERAL on the local display|screen`.
- Optional leading/trailing `please` and terminal sentence punctuation. Numeric syntax/range
  is still checked against the original text; no stripping invalid characters to salvage values.

Missing values/unbound display references and recognized malformed numeric forms clarify.
Negation, quotations, schedules, extra actions, conditions, other targets and unrecognized
phrasing cannot match a complete action and never execute. Many legitimate English paraphrases
are deliberately unsupported: this baseline is not general language understanding.

The unchanged model-only test is `bash scripts/test-numeric.sh`. Add `--include-raw-output` to
record raw generations for these public development cases; raw output is otherwise omitted.
Reports now include proposed plans, validation, failure messages and planner diagnostics.
Do not compare a grammar pass rate with a learned model's pass rate as though they were the same.

## One-terminal start (recommended on this development machine)

With your existing virtual environment active and trained artifact present, run:

```bash
HF_HUB_OFFLINE=1 edge-delegate-lab run \
  --plugin functiongemma-tasks \
  --adapter artifacts/training/functiongemma-tasks-v1-r2-b16/selected-adapter \
  --emulator-dir "$HOME/.local/state/edge-delegate-demo"
```

The command starts its own software emulator, waits for readiness, loads the planner once, and
opens a readable execution prompt. Type a complete request such as `Show the temperature.`
It performs actions only in this emulator, not your existing separately launched emulator.
There is no second terminal, copied socket path, or background shell job to manage.

For opt-in CUDA acceleration, add
`--plugin-settings configs/inference/functiongemma-tasks-compiled.json` to that command.
The first compilation can take tens of seconds or more before planner readiness; subsequent
queries reuse the loaded model. Warm-up does not execute device actions. See
[inference settings and reproducible comparison](model-plugins-and-compute.md#faster-resident-inference-experimental)
for memory/startup trade-offs and measured limitations. This does not qualify the model's accuracy.

`/help` lists controls; `/quit` stops the owned emulator. `/reconcile REQUEST_ID` checks recorded
receipts without executing steps. `/cancel REQUEST_ID` explicitly requests device-side fencing
of unresolved operations; it cannot undo completed actions. These commands operate on the current
session's journal. Every ordinary query is independent, not a conversational reply.

The private directory retains `device.sqlite`, `gateway.sqlite`, and `emulator.log` across restarts.
Only one managed session can own it at a time. Linux/WSL is required; use a Linux filesystem path
short enough for a Unix socket. An existing directory must be owned by you and have mode `700`.
Never delete those databases to clear uncertainty. A model-load failure stops the owned child
without deleting state. Ctrl+C during a request may leave an uncertain operation: recover its
receipt before new work. Restart with the same directory to access the same device and journal.

For a one-shot request add `--text "Show the temperature." --request-id example-1`. Repeating
the same request ID/input reuses its saved proposal and receipts. Managed mode defaults to text;
add `--format json` for scripts. Progress goes to stderr. The existing `--socket` mode keeps JSON
as its default and now also accepts `--format text`. Model timing diagnostics are attached to
execution results when the selected plugin provides them. A replay has no new generation timing.

For a fresh checkout without weights, first use the exact-command fixture in
[Try Edge Delegate](try-it.md). That checks infrastructure, not model quality.

## Prepare the small baseline

On this development machine, the `tasks-v1-r2` corpus and both trained artifacts already exist.
Skip generation/training to try them. The commands below are for a fresh checkout; to reproduce
in an existing checkout, choose new output paths in the training configuration first.

From the repository root in your activated WSL environment:

```bash
python -m pip install -e '.[dev,training]'
edge-delegate-lab generate-data --dataset-version v1 --output data/generated/tasks-v1-r2
edge-delegate-lab train --plugin task-classifier --config configs/training/task-classifier.json
edge-delegate-lab evaluate --planner task-classifier \
  --adapter artifacts/training/task-classifier-v1-r2-quality/final-adapter \
  --dataset data/generated/tasks-v1-r2/test.jsonl
```

Output directories must be new/empty. Preserve frozen datasets. The corpus contains 4,000
functional cases from 100 source templates and 200 adversarial cases. State/policy variants
are not independent language examples. The manifest records independent review as incomplete.

For compact FunctionGemma use plugin `functiongemma-tasks` and configuration
`configs/training/functiongemma-tasks.yaml`. Run `train --preflight-only` first. Its adapter
protocol is intentionally incompatible with the legacy full-plan protocol.

New compact-model training runs select retained checkpoints using canonical validation task
outcomes and write `selected-adapter/` plus `task-selection.json`. `final-adapter/` is the
trainer's provisional loss-selected export, not the deployment recommendation. The classifier
also selects checkpoints on task outcomes. Neither selection examines the frozen test set.

Compact inference uses four PyTorch CPU threads by default; `cpu_threads` in plugin settings
overrides this process-wide thread-pool choice. Offline evaluation uses batches of eight.
Interactive inference and gateway benchmarks use individual requests, never evaluation batches.

## Start the separate-process device emulator

Use a private directory on the Linux filesystem, not `/mnt/d`:

```bash
EDGE_DEMO_DIR=$(mktemp -d)
echo "$EDGE_DEMO_DIR"
edge-delegate-device --socket "$EDGE_DEMO_DIR/device.sock" \
  --database "$EDGE_DEMO_DIR/device.sqlite"
```

Leave that terminal running. In another activated WSL terminal, set `EDGE_DEMO_DIR` to the
printed path, then run:

```bash
edge-delegate-lab run --plugin task-classifier \
  --adapter artifacts/training/task-classifier-v1-r2-quality/final-adapter \
  --socket "$EDGE_DEMO_DIR/device.sock" --journal "$EDGE_DEMO_DIR/gateway.sqlite" \
  --policy examples/local-display/policy.json
```

To try the compact language-model candidate instead, use `--plugin functiongemma-tasks` and
`--adapter artifacts/training/functiongemma-tasks-v1-r2-b16/selected-adapter` with the same command.
After training/download has populated the model cache, set `HF_HUB_OFFLINE=1` for an offline
session, so model loading also avoids Hub requests. Neither candidate is qualified for deployment.

Type complete requests, one per line. The model stays loaded. `/quit` exits. Unlike
`interactive`, **`run` executes** permitted operations on the connected emulator. It does not
access physical devices. For recovery tests use `--text "Display 12" --request-id demo-12`.
Never reuse a request ID for a different request. The socket directory requires mode `700`.

The journal now binds each request ID to a device, an input digest (including locale/metadata),
and the first complete proposal. Retries load that proposal without calling the model. A new
proposal cannot append steps under an old ID; changed input returns `request_conflict`.
Current policy/state checks still apply before any new dispatch. A retry can continue unfinished
steps of the original plan; receipt-only `reconcile` never does. Completed reads return recorded
values, not fresh readings. Use a new request ID for a new observation.

The journal stores plan arguments/results for recovery; it is sensitive application state even
though raw request text is stored only as a digest and audit events omit arguments. Keep one
authoritative journal per device deployment, protect its directory, and preserve the device
database/identity with it. New emulator databases have distinct persisted identities. Legacy
databases keep `reference-emulator` for compatibility; do not treat multiple legacy copies as
independent devices. Losing or replacing a device database loses its receipts and fencing history.

## Failure and recovery

The journal persists an operation before dispatch. A lost response produces
`execution_unknown`: the write might have happened. Dependent steps stop and new work on
the device is blocked. A retry that still passes planning/validation can reuse a recorded
operation instead of blindly repeating a write. If the action changed its own precondition,
or permissions/approvals changed, the original request may no longer validate. Use receipt-only
recovery in that case; it needs neither a model nor a newly authorized plan:

```bash
edge-delegate-lab reconcile \
  --socket "$EDGE_DEMO_DIR/device.sock" --journal "$EDGE_DEMO_DIR/gateway.sqlite" \
  --request-id demo-12
```

`reconciled` means the selected recorded operations now have confirmed outcomes, including any
confirmed failures. It does **not** mean the complete task succeeded. This command never
dispatches actions, resumes unstarted steps, or takes a device snapshot. Missing/bad responses
leave operations `unknown`; exit `2` means unresolved or not found. A successful status lookup
does not renew permission to act. Check current device state before submitting new work.

Existing journal rows are preserved during an additive schema upgrade. Older rows without request
metadata can be selected with `--operation-id` instead of `--request-id`. Recovery events exclude
request text and action arguments. This does not promise exactly-once physical execution.

The emulator supports `--fault delay|disconnect|malformed|lost_ack|stale|stale_after_read`. Restart with the same
device database and a fresh socket path to test recovery. Operations without confirmed
receipts remain unresolved; there is no automatic force-retry command. No existing socket
or database is silently removed.

### When the device has no receipt

A crash between journal claim and dispatch can leave `unknown` forever. If the adapter supports
durable cancellation, explicitly request a device-side fence:

```bash
edge-delegate-lab reconcile --socket "$EDGE_DEMO_DIR/device.sock" \
  --journal "$EDGE_DEMO_DIR/gateway.sqlite" --request-id demo-12 --cancel-unknown
```

This changes device recovery metadata: the device atomically returns an existing completed
receipt or persists a cancellation tombstone preventing a late dispatch of the same operation ID.
It never rolls back an action. A confirmed cancellation is recorded as `failed`, while lost
responses remain `unknown`. After all uncertain operations are confirmed, inspect state and use
a new request ID for new work. Never delete the journal to unblock a device. An adapter without
this contract must stay blocked until a device-specific, independently verified recovery procedure
establishes the outcome. The emulator persists fences across restart; this is not a hardware guarantee.

Old operations without a saved request plan are supported through receipt-only recovery, not
automatic replanning. Use a new request ID after inspecting the recovered outcome.

## Read results correctly

Evaluation v2 reports `task_success_rate` and `task_assessed_count` using expected state,
return values, and invocation traces. `outcome_accuracy` is a deprecated **status-only** alias,
not a measure of task completion. Legacy data without effects is marked unassessed.

Training, independent label review, quality/performance qualification, and hardware
qualification are separate gates. Consult the roadmap before describing this as supported.

## Benchmark and check the release gates

With the emulator running and no training in progress:

```bash
edge-delegate-lab benchmark --plugin task-classifier \
  --adapter artifacts/training/task-classifier-v1-r2-quality/final-adapter \
  --socket "$EDGE_DEMO_DIR/device.sock" --journal "$EDGE_DEMO_DIR/benchmark.sqlite" \
  --policy examples/local-display/policy.json --output artifacts/benchmark/classifier.json
```

This performs three runs of five warmups and 200 timed mixed requests. Failures remain in
latency samples; expected action/refusal paths are checked separately. Timings distinguish
planning, generation, transport, and combined validation/persistence overhead. Do not call
the combined overhead a pure validator benchmark. Cold load and first-query timing are separate.
Generative plugins also expose tokenization/preprocessing and output-decoding timings. Status
groups have separate latency summaries. The command checkpoints measurements to a sibling
`.partial.json` every 50 requests and after each run. Partial reports cannot qualify a release;
the requested final output is written only after all runs finish.

Evaluate `test.jsonl` and `safety.jsonl` with the same plugin, artifact, and inference settings,
using `evaluate --output ...`. Then supply those paths:

```bash
edge-delegate-lab qualify --test-report artifacts/evaluation/classifier-quality-test.json \
  --safety-report artifacts/evaluation/classifier-quality-safety.json \
  --benchmark artifacts/benchmark/classifier.json \
  --manifest data/generated/tasks-v1-r2/manifest.json
```

Exit `2` means the candidate is not qualified. This is expected until independent review and
every quality/performance gate pass. The command checks matching data/model evidence and never
changes the default model. Physical-device qualification remains false even if these gates pass.
