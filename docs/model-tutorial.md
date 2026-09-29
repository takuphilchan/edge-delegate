# Optional: test a temperature model

[Documentation home](README.md) | [First-use tutorial](try-it.md) | [Current quality](qualification-status.md)

This path tests learned planning for three temperature/display tasks. It does not teach the model
light controls. Start with the no-model tutorial if you are checking installation.

**What you will learn:** how to load an existing model candidate, inspect its proposal without
acting, then test it against a software device. This tutorial does not train new weights.
If you do not have a compatible artifact yet, you can still complete the no-model tutorial;
missing model files are not a core-installation failure.

The reference tasks are: read temperature, display an explicit number, and read then display
temperature. They are deliberately small so that expected values, effects and non-actions
can be checked. They do not demonstrate arbitrary-device language control.

## Prerequisites

Use Linux/WSL, an activated Python 3.12+ environment, and the repository root for the scripts below.
Install optional inference dependencies into a compatible PyTorch/CUDA environment:

~~~bash
python -m pip install -e ".[inference]"
~~~

See the [development environment guide](development-runbook.md) for compute/authentication setup.
FunctionGemma requires access to its gated base model. Accept its terms and authenticate before
downloading. Offline mode works only after all required files are cached.

A trained adapter is **not bundled with the repository**. Set ADAPTER_DIR to a compatible
artifact you actually trained or obtained from a trusted source; the following is the historical
local candidate path, not a download instruction:

~~~bash
ADAPTER_DIR=artifacts/training/functiongemma-tasks-v1-r2-b16/selected-adapter
edge-delegate-lab artifact-verify --artifact "$ADAPTER_DIR"
~~~

Verification checks declared integrity/compatibility, not model quality. Omitting --adapter
tests the base model. Do not load a legacy functiongemma full-plan artifact as functiongemma-tasks.

## Inspect a saved profile

Use a new output directory:

~~~bash
edge-delegate-lab init-example --output ./my-edge-profile
edge-delegate-lab profile-check --profile ./my-edge-profile
~~~

capabilities.json describes operations; state.json records a snapshot; policy.json defines
permissions and limits. A profile does not implement a device, refresh itself or authorize
every possible plan. Do not extend freshness limits to hide stale live-device state.

## Preview without actions

~~~bash
edge-delegate-lab interactive \
  --plugin functiongemma-tasks --adapter "$ADAPTER_DIR" \
  --profile ./my-edge-profile --format text
~~~

Try Read the temperature., Display -3.5., Show it., and Open the door.
Use /context to inspect inputs, /raw on to inspect generation, and /quit to exit.
Each request is independent. After clarification, submit the complete corrected request;
this is not a conversation with remembered context. Nothing executes in this client.

Passing checks establishes proposal validity under that profile, not correct intent.

## Execute only in software

For a fresh in-memory simulator:

~~~bash
edge-delegate-lab simulate \
  --plugin functiongemma-tasks --adapter "$ADAPTER_DIR" \
  --text "Show the temperature." --format text
~~~

The intended result is a temperature read returning 24.5, then a display write. Inspect the
before/after state and calls. This tests the model/compiler/runtime path, not physical effects.
Each invocation resets simulator state and replay records.

For a persistent session using the managed Unix-socket emulator:

~~~bash
edge-delegate-lab run \
  --plugin functiongemma-tasks --adapter "$ADAPTER_DIR" \
  --emulator-dir "$HOME/.local/state/edge-delegate-model-demo"
~~~

Wait for readiness; initialization/model preparation can take time. This client **can execute
software-device operations**. /quit stops the managed process but retains its databases.
See [gateway usage](gateway-preview.md) for inference settings, explicit IDs and recovery.
Do not delete journals to clear uncertain requests.

## Automatic model tests

With the same activated environment and cached artifact:

~~~bash
bash scripts/test-numeric.sh --artifact "$ADAPTER_DIR"
bash scripts/test-latency.sh --artifact "$ADAPTER_DIR" \
  --settings configs/inference/functiongemma-tasks-compiled-decimal-v1.json
~~~

These create new reports: numeric tests check effects/non-actions; latency diagnostics repeat
a small workload with pauses. The numeric default uses explicit decimal.v1 settings.
A nonzero exit can mean an expected quality gate failed—inspect the report instead of changing
labels to make it pass. These are exposed development checks, not independent release holdouts.

Do not train concurrently with latency measurements. Report storage, settings, artifact/source
identity and all failures. First compilation is startup cost, separate from warm requests.
The [current status](qualification-status.md) records why the existing learned candidate remains
unqualified despite successful familiar phrases. For data/training work follow
[model lifecycle](model-lifecycle.md), not an automatic retraining loop after each smoke test.
