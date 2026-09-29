# Edge Delegate

**Build local applications that turn requests into controlled device operations.**

Edge Delegate is a developer toolkit for connecting application commands and local models to
devices. You define the operations a device supports. Edge Delegate turns a request into an
explicit plan, checks it against the device's capabilities and your permissions, and records
what happened when it executes.

The goal is to make language-driven device control useful without treating a model's output
as permission to act. The current project includes a working software-device runtime and a
separate model-training and evaluation lab. It is experimental, not a production-ready
controller for arbitrary hardware.

## Why this exists

Understanding “turn the inspection light on” is only one part of controlling a device.
An application also needs to answer:

- Which light did the user mean?
- Is this action supported and allowed?
- Are the arguments valid for that device?
- Did the action finish, fail, or finish without its acknowledgement reaching us?
- Would retrying repeat an operation that already happened?

Edge Delegate provides a common place to handle those questions. A model can help interpret
a request; explicit code checks and carries out the resulting operations. When an outcome
is uncertain, the runtime records that uncertainty instead of assuming the action never happened.

## Who it is for

The intended users are developers building local interfaces for sensors, displays and device
controls—for example, an equipment-status console or an embedded-system gateway.
Today, you can use the software integrations to develop and test those applications before
implementing and qualifying a physical adapter.

Here, **edge** means running the application near the devices, on a local host or gateway.
It does not mean the model already runs inside a microcontroller. The core is Python;
model inference is optional and has separate compute requirements.

If you only need a few fixed buttons calling a known driver, direct application code may be
simpler. Edge Delegate becomes useful when you need a shared boundary for request interpretation,
device permissions, execution records and recovery.

## One example

The included demonstration has two software lights: workbench and inspection.

A request to **“Set the inspection light to 40 percent.”** selects the inspection light,
proposes a brightness value of 40, checks that operation, and changes only that light's
software state when execution is explicitly requested. Brightness does not turn its power on.

**“Turn the light on.”** is ambiguous because both devices have the alias light. The demo
asks which one rather than choosing. Retrying an identical completed request with the same
request ID returns its recorded result rather than issuing a second operation.

This example uses an exact command parser, **not a trained model**. Lights are a reference
integration for exercising targeting and execution—not the limit of the project's intended use.

## How the pieces fit together

There are three responsibilities:

1. **Interpret the request.** Application code can supply an explicit device/action/value.
   A command parser or compatible local model can translate supported text into a proposal.
2. **Check and execute it.** The runtime checks arguments, device state and permissions,
   then uses a device adapter to perform the operation. An adapter is the code connecting
   the runtime to a software device or physical transport.
3. **Improve and measure model behavior.** The lab prepares datasets, fine-tunes compatible
   models and tests whether proposals actually produce the intended outcomes.

The proposal is called **Plan IR**—Plan Intermediate Representation. It is structured data,
not generated Python. The durable operation journal is the runtime's record of attempted
operations and their outcomes. These are implementation tools; the purpose is controlled,
inspectable device execution.

Training changes how a model interprets requests. It does not create device drivers,
grant permissions or guarantee correct intent. See the [architecture](docs/system-architecture.md)
for the complete request path.

## What you can use today

| Path | Available now | Boundary |
| --- | --- | --- |
| Python control interface | Explicitly target software lights; read/set power and brightness | One target per request; no model required |
| Exact text commands | Recognize the documented light commands and a separate temperature/display grammar | Fixed vocabulary, not general language understanding |
| Local-model lab | Train and test planners for reading temperature, displaying a number, and reading then displaying temperature | Existing learned candidates have known quality failures |
| Device integration interfaces | Installed catalogs and adapters; software light, Unix-socket and independent counter examples | New physical integrations need implementation and qualification |

**The light-control and trained-model examples are not yet one learned-control product.**
They share runtime foundations, but the existing temperature model has not learned light
controls. Adding a driver does not automatically teach a model new actions.

External-model delegation is a future direction, not a working fallback. Voice processing,
microcontroller inference, background jobs/rules and a supervised request service are also
outside the current implementation. No physical integration is production-qualified.
See [current evidence and blockers](docs/qualification-status.md), not demo success alone,
when assessing adoption.

## Try it

Start with [Control two software lights](docs/try-it.md). You need Python 3.12 or newer,
Linux or Ubuntu under Windows Subsystem for Linux (WSL), and this repository.
No GPU, model download, account or physical board is needed.

The tutorial covers installation, a preview, an explicit state change, ambiguity and retry.
It explains the expected result after each command and how to recognize common problems.

After that, choose your goal:

- **Build an application:** [public Python interface](docs/reference/control-sdk.md).
- **Connect another device:** [integration guide](docs/extensions.md).
- **Test a local model:** [model tutorial](docs/model-tutorial.md).
- **Understand failures:** [results](docs/reference/results.md) and [recovery](docs/how-to/reconcile.md).
- **Contribute:** [development runbook](docs/development-runbook.md) and [roadmap](docs/roadmap.md).

The [documentation guide](docs/README.md) gives a reading path for each goal.
You do not need to read every document to get started.

## Development checks

From an activated Python environment at the repository root:

~~~bash
python -m pip install -e ".[dev]"
python -m pytest -q
python -m ruff check .
~~~

The normal suite excludes hardware-marked tests. Clean-wheel acceptance also runs the documented
no-model examples outside the checkout. These checks verify software behavior, not model
accuracy or physical reliability.

Project-owned code is [MIT licensed](LICENSE). Model weights have their own licenses and access
requirements.
