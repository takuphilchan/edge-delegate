# Edge Delegate

Edge Delegate is an experimental local-first device-control SDK (software development kit).
It turns structured requests or supported text commands into typed plans, checks device
permissions and constraints, and records confirmed or uncertain outcomes.

A model can propose an action; it cannot grant permission to execute it.

## Start here

Follow **[Control two software lights](docs/try-it.md)**. It needs no model, GPU, account, or
physical device. You will preview a command, execute it, see an ambiguous target rejected,
and retry without repeating the operation.

Use Linux or Ubuntu under Windows Subsystem for Linux (WSL), with Python 3.12 or newer.
From this checkout, a basic installation is:

~~~bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
~~~

Reuse an activated environment if you already have one. The tutorial explains state storage,
expected results and troubleshooting; model dependencies are optional.

## What exists now

| Path | What it does | Important limit |
| --- | --- | --- |
| Structured control SDK / exact light commands | Targets named software lights; reads or sets power and brightness | No learned inference; one target per request |
| Temperature model lab | Fine-tunes and tests planners for the three reference temperature/display tasks | Current model candidates are not qualified |
| Shared execution runtime | Validates plans, checks authorization, records operations and reconciles receipts | No qualified physical adapter or supervised request service |

The light demo does not prove that the trained model learned new controls. There is no cloud
delegation, voice pipeline, or arbitrary-device support. Project code is MIT licensed;
model licenses are separate.

The [current status](docs/qualification-status.md) distinguishes implemented features,
measured evidence, and release blockers. Do not interpret successful demos as production readiness.

## Choose your next task

- **Understand the design:** [architecture](docs/system-architecture.md).
- **Use the Python SDK:** [control API reference](docs/reference/control-sdk.md).
- **Add an integration:** [extension guide](docs/extensions.md).
- **Try a trained model:** [optional model tutorial](docs/model-tutorial.md).
- **Recover an uncertain operation:** [reconciliation guide](docs/how-to/reconcile.md).
- **Contribute or inspect commands:** [development runbook](docs/development-runbook.md).
- **See remaining work:** [single active roadmap](docs/roadmap.md).
- **Find a term:** [glossary](docs/glossary.md).

## Verify a checkout

~~~bash
python -m pip install -e ".[dev]"
python -m pytest -q
python -m ruff check .
~~~

The normal test suite excludes the hardware-marked test. It does not train or qualify a model.
Clean-wheel acceptance also exercises the documented no-model tutorial outside the checkout.

## Repository boundaries

| Location | Responsibility |
| --- | --- |
| src/edge_delegate/application/ | Public sessions, device registration, candidate pack checks |
| src/edge_delegate/contracts/, ir/, policy/, runtime/ | Contracts, validation, authorization, execution and recovery |
| src/edge_delegate/planner/, model_plugins/ | Deterministic compilation and optional learned planners |
| src/edge_delegate/adapters/, simulator/ | Transport adapters and software devices |
| src/edge_delegate_lab/ | Data review, training, diagnostics and evaluation |
| schemas/, specs/ | Wire formats and normative/draft contracts |
| docs/, tests/ | Human documentation and executable verification |

See the [documentation index](docs/README.md) for the full reading map.
