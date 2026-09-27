# Try Edge Delegate and know what you tested

[Documentation home](README.md) | [Next milestones](roadmap.md)

Edge Delegate has a runtime you can build an application around, a simulator that stands in for
a device, and a model-development lab. The lab is a **test harness**: it supplies inputs, runs a
component, and records what happened. It is not the device runtime itself.

Start with the following steps in order. You do not need a GPU or model for the first two.

For explicitly bounded interactive commands without learned-model execution, see
[the command-grammar path](gateway-preview.md#bounded-commands-without-learned-model-execution).
It is a separate deterministic baseline, not a fix to the trained model's weights.

## 1. Prove the runtime works without AI

In your Ubuntu/WSL terminal, from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
edge-delegate demo
```

Python 3.12+ is required. If you already have an activated project environment, reuse it
instead of creating another. All following commands run from the repository root.

The example reads a simulated temperature of `24.5` and writes it to a simulated display.
Look for `status: executed` and `display_value: 24.5`.

This proves that a **fixed, known plan** can pass validation and execute. It does not prove a
model understands English, control physical hardware, or call a cloud service.

To check the complete current synthetic dataset against its known answers:

```bash
edge-delegate-lab evaluate --planner gold
```

`gold` means the evaluator is given the correct plans. Its perfect scores are a harness
self-check, not model accuracy. To run the automated software regression suite:

```bash
python -m pytest -q
python -m ruff check .
```

## 2. Inspect the context you will give the model

```bash
edge-delegate-lab init-example --output /tmp/my-edge-profile
edge-delegate-lab profile-check --profile /tmp/my-edge-profile
```

Use a new directory. This command also works from a wheel-only install and never overwrites
an existing profile. The generated snapshot is current when created, then becomes stale.

A profile consists of three ordinary JSON files:

| File | Question it answers | What it does not do |
| --- | --- | --- |
| `capabilities.json` | Which operations exist, and what values do they accept/return? | Implement sensor or display code. |
| `state.json` | What did the device state look like at a particular time? | Poll live hardware or refresh itself. |
| `policy.json` | Which permissions, approvals, and limits apply? | Give the model permission to override those rules. |

The command checks the file contracts and unique capability IDs without loading weights. It
shows policy restrictions, missing permissions, and timestamp warnings. A valid profile is not
proof that any particular plan is authorized. Use `--format json` for scripts.

The bundled profile is a **saved demonstration fixture**. Its unusually generous state-age
limit keeps the example usable. Do not copy that limit into a live-device deployment, or refresh
a timestamp without actually observing new device state.

## 3. Ask your model for a preview

Before downloading weights, you can test the installed command-to-device path with an
**exact-command fixture**, not AI. Install the independent example:

```bash
python -m pip install --no-deps ./examples/plugins/counter
edge-delegate-lab plan --plugin display-demo --profile /tmp/my-edge-profile \
  --text "Show the temperature."
```

`display-demo` recognizes only that exact phrase; other requests are denied. For explicit
execution in one terminal:

```bash
edge-delegate-lab run --plugin display-demo \
  --emulator-dir "$HOME/.local/state/edge-delegate-demo"
```

Wait for `READY: planner loaded`, then enter `Show the temperature.`. Use `/quit` to stop.
It starts and stops its own emulator and retains the database/journal. Readable results distinguish
successful steps, replayed results, and uncertain outcomes. This is an exact-command fixture,
not an AI model. The same managed mode works with a trained model; see [gateway usage](gateway-preview.md).

If you specifically want to manage the two processes separately, start an emulator in one terminal:

```bash
EDGE_DEMO_DIR=$(mktemp -d)
echo "$EDGE_DEMO_DIR"
edge-delegate-device --socket "$EDGE_DEMO_DIR/device.sock" \
  --database "$EDGE_DEMO_DIR/device.sqlite"
```

In a second activated terminal, set `EDGE_DEMO_DIR` to the printed directory:

```bash
edge-delegate-lab run --plugin display-demo \
  --socket "$EDGE_DEMO_DIR/device.sock" --journal "$EDGE_DEMO_DIR/gateway.sqlite" \
  --policy /tmp/my-edge-profile/policy.json \
  --text "Show the temperature." --request-id first-demo
```

Expect `executed` with a temperature read and display write. Repeating the same command replays
the recorded steps; it does not perform a fresh sensor read. Use a new request ID for new work.
This validates installation/integration, not language understanding.

### Optional: your trained model

This stage needs the inference dependencies and access to the base model. See the
[setup instructions](development-runbook.md) if the environment is not ready.

Set the adapter directory to a run that actually exists on your machine. For the current
compact-task run, if you have trained it or received a verified candidate bundle:

```bash
ADAPTER_DIR=artifacts/training/functiongemma-tasks-v1-r2-b16/selected-adapter
edge-delegate-lab artifact-verify --artifact "$ADAPTER_DIR"
edge-delegate-lab interactive \
  --plugin functiongemma-tasks \
  --adapter "$ADAPTER_DIR" \
  --profile examples/local-display
```

Type:

```text
Show the current temperature on the local display.
```

The readable result says whether the proposal passed checks, lists proposed steps or a
clarification question, and explains failures. **Nothing executes in this client.** Each query
is independent, even when the model stays loaded; answering a clarification as if this were a
chat conversation does not carry forward the earlier request. Submit the complete revised request.

Use `/raw on` to inspect generation, `/format json` for full structured results, `/context` to
inspect the saved context, and `/quit` to exit. Raw output is hidden by default in interactive
mode. The one-shot `plan` command retains JSON output by default:

```bash
edge-delegate-lab plan --plugin functiongemma-tasks --adapter "$ADAPTER_DIR" \
  --profile examples/local-display --format text \
  --text "Show the current temperature on the local display."
```

When supplied, a compact-task adapter must have a compatible manifest. Omitting `--adapter`
tests the base model, not your trained candidate. Legacy `functiongemma` uses a different output
protocol; do not mix these artifacts or interpret one good answer as evidence of reliable quality.

## 4. Run the model through the actual runtime

```bash
edge-delegate-lab simulate --plugin functiongemma-tasks --adapter "$ADAPTER_DIR" \
  --text "Show the current temperature on the local display."
```

Unlike the preview, `simulate` passes the selected model's proposal through `Coordinator` and
`Executor`. It can execute approved operations **only in a fresh in-memory local-display
simulator**. It does not execute the arbitrary declarations in a profile, contact physical
hardware, or send external-model requests. Each invocation resets simulated state and replay
records; this is not a persistent application session.

For the intended plan, expect:

- `Runtime outcome: executed`;
- two device invocations: temperature read, then display write;
- `display.last_value` changing from `null` to `24.5`.

If the model emits malformed output or a forbidden plan, the command reports the failure and
does not execute those proposed steps. A valid refusal or clarification also performs no work.
Exit `0` means local execution completed; `2` means it did not; `1` means setup/input failed.
Use `--format json` for automated assertions about status, steps, and before/after state.

If the model writes the wrong number using an otherwise permitted operation, runtime checks
can still pass. Compare the actual result with the intended result. The command explicitly
reports intent correctness as `not_evaluated`; only a test with a known answer can measure it.

## 5. Test automatically instead of typing every query

For this checkout's existing trained adapter and WSL model environment:

```bash
cd /mnt/d/project/edge-delegate
source /home/phil/.venvs/edge-model/bin/activate
bash scripts/test-latency.sh
```

This script requires the cached model, selected adapter, and installed model dependencies;
it does not download or train them. It uses the compiled settings by default. Initial loading
and compilation can take a few minutes and are reported separately from request latency.
Do not run training or another model session during measurement.

The script sends these six requests automatically: read temperature, show temperature, display
12, display -3.5, "Show it", and "Open the door". Each phase sends 12 requests (two repetitions):
back-to-back, with three-second pauses, then back-to-back again. Each request has a fresh ID,
so replayed answers cannot make the benchmark artificially fast.

It checks response status, attempted device calls and returned values, final output, and final
device state. Clarification and refusal must produce no device calls or state changes. A failure
remains in the timing results and makes the script exit nonzero. These six known examples are
a smoke test, **not** a general language-accuracy or production-readiness qualification.

The terminal prints PASS/FAIL and the report path under `artifacts/performance/latency-*/report/`.
`report.json` includes every request, stage timings, phase median/P95/maximum, hardware, model
identity, and filesystem information. A checkpoint is saved after every request; an interrupted
run is marked incomplete. P95 with this small sample is diagnostic, not a reliable release estimate.

For a shorter run, or to reproduce delays after longer pauses:

```bash
bash scripts/test-latency.sh --count 6 --idle-seconds 3
bash scripts/test-latency.sh --count 6 --idle-seconds 15
```

`--count` is requests **per phase**, not total. `--help` lists all options. You can override
`--artifact`, `--settings`, and `--plugin`; other plugins must implement the same reference tasks
to pass these assertions. This is a checkout helper, not a new installed CLI command.

Each run owns and stops a fresh software emulator. Temporary state and journal files are created
under `~/.local/state/edge-delegate-profiles/`, then removed; your existing interactive demo is
untouched. Reports are retained. `--state-root PATH` changes the storage being measured. On this
WSL machine `/tmp` is RAM-backed, so it is **not representative of disk-backed journal latency**.
The report records the actual filesystem rather than assuming home storage is always disk.

Timing details: `preprocessing_breakdown_ms` splits tokenization, input transfer, resource setup,
and remaining preparation. Journal connection/setup/body/commit/close times are a **subset** of
`validation_persistence_other_ms`; do not add them to it. CPU-side timing around CUDA calls is
not a GPU kernel trace. Independent before/after smoke observations occur outside the timed
gateway request; request timing still includes inference, validation, persistence, transport,
and device acknowledgement. The model is not reloaded between requests.

## What each test proves

| Test | Real model? | Executes? | Evidence it provides |
| --- | --- | --- | --- |
| `demo` | No | Fixed plan, simulator only | Runtime wiring works. |
| `evaluate --planner gold` | No | Known valid plans, simulator only | Labels and evaluation harness agree. |
| `profile-check` | No | No | Saved files decode and their basic restrictions are visible. |
| `plan` / `interactive` | Depends on selected plugin | No | A planner can propose plans against saved context. |
| `run --plugin display-demo` | No | Separate-process emulator | Installed gateway execution/replay works for an exact phrase. |
| `simulate` | Yes | Valid local plans, simulator only | Model-to-runtime integration and observable device effects. |
| `bash scripts/test-latency.sh` | Yes | Fresh separate-process emulator | Six known outcomes and burst/idle latency on recorded storage. |
| `model-doctor` | Yes | No | Controlled generation and validation diagnostics, not a benchmark. |
| `evaluate --planner functiongemma --dataset ...` | Yes | Eligible proposals, simulator only | Correctness against specified gold cases; strength depends on the dataset. |

## If a test fails

- **Setup fails:** verify the WSL environment, installed extras, model access, and adapter path.
- **Profile fails:** fix its JSON/contracts or duplicate IDs before loading the model.
- **No usable plan:** inspect raw output; do not relax the parser to accept arbitrary text.
- **Context budget exceeded:** shorten the prompt or lower the reserved output budget. Do not silently truncate.
- **Plan rejected:** read the issue code. Fix the proposal or legitimate context; do not automatically grant permissions.
- **Executes but does the wrong thing:** this is an intent/planning failure. Add an independently reviewed test case and improve the model/data.

The [roadmap](roadmap.md) defines what must be demonstrated before calling this a reliable
device application.
