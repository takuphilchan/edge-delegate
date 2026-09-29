# Control two software lights

[Tutorial index](README.md) | [Current status](qualification-status.md)

**Mode:** deterministic commands; software emulator only; no model or physical actions.
This tutorial takes you from installation to a checked state change and a safe retry.

## 1. Install

Use Linux or Ubuntu/WSL, Python 3.12 or newer, and a checkout of this repository.
From the repository root:

~~~bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
~~~

If a project environment is already activated, reuse it instead of creating another.
Do not run these Linux activation commands in Windows Git Bash.

Create a fresh tutorial directory in this terminal:

~~~bash
EDGE_LIGHT_DIR=$(mktemp -d)
echo "$EDGE_LIGHT_DIR"
~~~

Keep that path: it contains two software-device databases and their shared operation journal.
This temporary directory is for functional learning, not performance qualification.
Do not delete it to resolve an uncertain operation. To resume in another terminal, activate
the same environment and set EDGE_LIGHT_DIR to the printed path.

## 2. Preview without acting

<!-- tutorial: preview -->
~~~bash
edge-delegate control-demo \
  --directory "$EDGE_LIGHT_DIR" \
  --text "Set the inspection light to 40 percent." \
  --request-id tutorial-brightness
~~~

Look for:

- mode is preview;
- response.gateway.execution_attempted is false;
- response.gateway.validation.issues is empty;
- both lights still have power false and brightness 100.

Initialization creates databases. Preview reads state and builds a plan; it does not reserve
this request ID or write an action receipt. A valid preview is not an execution approval that
survives arbitrary changes to device configuration.

## 3. Execute explicitly

<!-- tutorial: execute -->
~~~bash
edge-delegate control-demo \
  --directory "$EDGE_LIGHT_DIR" \
  --text "Set the inspection light to 40 percent." \
  --request-id tutorial-brightness --execute
~~~

Expected: response.gateway.result.status is executed, inspection brightness is 40, and
workbench brightness is still 100. Both lights remain off: brightness and power are separate.

To turn on only the inspection light:

<!-- tutorial: power -->
~~~bash
edge-delegate control-demo \
  --directory "$EDGE_LIGHT_DIR" \
  --text "Turn the inspection light on." \
  --request-id tutorial-power --execute
~~~

Inspection power becomes true while brightness remains 40. Workbench stays off at 100.
These values describe software state, not a visible physical lamp.

## 4. See ambiguity handled without an action

<!-- tutorial: ambiguous -->
~~~bash
edge-delegate control-demo \
  --directory "$EDGE_LIGHT_DIR" \
  --text "Turn the light on." \
  --request-id tutorial-ambiguous --execute
~~~

Both devices have the alias light. Expected: clarification_required, two choices,
execution_attempted false, and unchanged state. The command exits with status 2 intentionally;
that is a non-executing response, not a setup failure. No model guesses which light you meant.

## 5. Retry the original request

<!-- tutorial: replay -->
~~~bash
edge-delegate control-demo \
  --directory "$EDGE_LIGHT_DIR" \
  --text "Set the inspection light to 40 percent." \
  --request-id tutorial-brightness --execute
~~~

Expected: the step status is replayed and the recorded result is 40. No new operation is issued.
An old receipt describes that old action, not a fresh observation. Use a new ID for new work;
reusing an ID with another value or device is a request conflict.

## 6. Understand the result

The full JSON is useful for applications. For a person, focus on:

1. target: which stable device identity was selected;
2. validation.issues: whether the plan was rejected;
3. result.status and execution.steps: what happened;
4. state: current software observations.

Read the [result reference](reference/results.md) for failures, uncertainty, and exit codes.
A successful control says nothing about learned-model accuracy.

If setup fails, check the active environment and directory permissions. If execution is
unknown, follow [reconciliation](how-to/reconcile.md); do not delete journals or choose a new
request ID merely to retry an uncertain write.

## Next steps

- Run automatic control regressions from the checkout:
  install with `python -m pip install -e ".[dev]"`, then `bash scripts/test-control.sh`.
- Build an application using the [SDK reference](reference/control-sdk.md).
- Inspect the [architecture](system-architecture.md).
- Try the [optional learned-model tutorial](model-tutorial.md).

The marked command blocks above are replayed in clean-wheel acceptance tests. Those tests
check effects, non-actions and receipts, not just whether each command exits.

## Automatic model testing

Learned-model latency instructions live in
[model testing](model-tutorial.md#automatic-model-tests). The light regression script above
does not load a model. Neither smoke suite grants production qualification.
