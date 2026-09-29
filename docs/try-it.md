# Control two software lights

[Tutorial index](README.md) | [Current status](qualification-status.md)

**Mode:** deterministic commands; software emulator only; no model or physical actions.
This tutorial takes you from installation to a checked state change and a safe retry.

## What you are learning

Imagine your application has two controls that happen to accept similar requests.
This example shows how to select the correct one, inspect an operation before acting,
and keep a retry from becoming another operation.

The lights are software devices stored in local files. Both begin off, with brightness 100,
when you use a fresh directory. You will change only the inspection light. No lamp will
physically turn on, and no model is trained or loaded.

By the end, you should be able to explain the difference between a preview, a completed
operation, a clarification and a replayed result. Those same distinctions matter when
building an application with the [Python interface](reference/control-sdk.md).

## Before you start

You need a checkout of this repository and a terminal in its root directory—the directory
containing README.md and pyproject.toml. If you have not downloaded it yet:

~~~bash
git clone https://github.com/takuphilchan/edge-delegate.git
cd edge-delegate
~~~

Use Linux or Ubuntu in Windows Subsystem for Linux (WSL), with Python 3.12 or newer.
All commands below run in the same terminal. You can check the interpreter with
`python3 --version`. You do not need the author's virtual environment or model artifacts.

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

- `mode` is `preview`;
- `response.gateway.execution_attempted` is `false`;
- `response.gateway.validation.issues` is empty;
- both lights still have power `false` and brightness `100`.

**Checkpoint:** you have asked “would this operation pass the checks?”, not “perform it”.

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

**Checkpoint:** one device changed, the other did not. This is the difference between
selecting a specific target and broadcasting a command.

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

This client does not remember a conversation. To resolve the ambiguity, submit the complete
request, such as “Turn the inspection light on.”, with a new request ID. The name alone is
not a follow-up answer the client can interpret.

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

The request ID identifies one piece of work; it is not the device's name or your login.
Use a different ID when you intentionally want a new operation, even if the wording is the same.

## 6. Understand the result

The full JSON is useful for applications. For a person, focus on:

1. `response.target`: which device identity was selected, when a target resolved;
2. `response.gateway.validation.issues` for a preview, or
   `response.gateway.result.validation.issues` after execution: any rejected checks;
3. `response.gateway.result.status` and its `execution.steps`: what happened on an execution path;
4. `state`: current software observations.

A clarification uses a different response: look at `response.status`,
`response.choices` and `response.execution_attempted`; it has no gateway execution result.

Read the [result reference](reference/results.md) for failures, uncertainty, and exit codes.
A successful control says nothing about learned-model accuracy.

## If something does not match

| What you see | What to check or do |
| --- | --- |
| command not found | Activate the environment where you installed the package; run `python -m pip show edge-delegate` to check it |
| Activation path does not exist | Use the environment you created in step 1, in the same checkout; do not copy another user's home path |
| No visible physical change | Expected: these are software devices; inspect the returned state |
| Unexpected starting values | You reopened an existing demonstration directory; for a separate fresh tutorial use a new directory, preserving old records |
| Exit status 2 for “Turn the light on.” | Expected clarification; it is not a failed installation |
| request_conflict | The ID has been used for different work; inspect the original record rather than changing IDs to bypass an uncertain operation |
| execution_unknown | Follow [reconciliation](how-to/reconcile.md); do not delete journals or blindly retry with another ID |

Do not continue to model training to fix an installation or exact-command demonstration problem.
The model is not involved in this tutorial.

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
