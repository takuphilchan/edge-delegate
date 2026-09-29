# System architecture

[Documentation home](README.md) | [Terms](glossary.md) | [Current status](qualification-status.md)

Edge Delegate separates deciding what was requested from deciding what may execute.
Its current adapters control software devices. Physical support and the supervised service
remain unqualified or unimplemented; this page describes existing code.

## Three proposal paths, one execution boundary

| Entry | Interpretation | Output |
| --- | --- | --- |
| Structured control SDK | Explicit target/action/parameters; no language model | ControlRequest compiled to Plan IR |
| Deterministic text command | Full-command grammar, then exact target resolution | Same control request or non-action response |
| Learned planner | Selected model plugin interprets text | TaskDecision compiled to Plan IR, or legacy full Plan IR |

The old fixed-plan demo is a wiring fixture, not a fourth language-understanding system.
Plan IR means Plan Intermediate Representation: typed action data, not executable Python.

A compact view of the implemented paths:

~~~text
Structured request ----> target + catalog binding ----> ControlPlanner ----+
Exact light command ---> grammar + target resolution ---------------------+
                                                                         |
Model request ----------> model plugin --> task compiler / full plan ------+
                                                                         v
                            validation --> authorization --> durable execution
                                                                         |
                                              confirmed / failed / unknown
~~~

The actual coordinator obtains context and validates policy with the plan before calling
the executor; validation and authorization are parts of the same deterministic checks.
The model never receives device-dispatch authority.

## Follow a targeted light request

Consider: Set the inspection light to 40 percent.

1. The demo selects an installed light catalog and exact-command parser.
2. DeviceRegistry resolves inspection light to one stable device/endpoint. The shared alias
   light matches two devices and returns clarification without a plan.
3. ControlSession creates a ControlRequest binding the target registration and catalog
   fingerprints to the action and integer parameter. No model runs.
4. The selected GatewaySession delegates to Coordinator, which obtains the device snapshot
   and capability cards. Its planner wrapper reserves the request in the shared journal;
   conflicting ID reuse across devices or parameters is rejected.
5. For new work, ControlPlanner maps the installed action to a capability and builds one
   Plan IR step. Target binding affects the plan fingerprint used by approvals. The first
   proposal is persisted; identical retries retrieve that saved plan.
6. Coordinator validates the plan's shape, arguments, state, permissions, approval and budget
   constraints against the collected context.
7. Executor binds the plan, claims the operation durably, and checks fresh per-step guards.
   The bound adapter checks identity/configuration again before dispatch.
8. The emulator changes only that light and records a receipt. The journal records the
   confirmed result. The demo separately reads software state for presentation.

ControlSession owns one synchronous GatewaySession per device, sharing a journal. There is
one endpoint per registered device and one target per request. This is not a distributed
multi-device transaction. Concurrent same-session use is rejected, not queued.

The public classes are in [application](../src/edge_delegate/application/); the compiler is
[ControlPlanner](../src/edge_delegate/planner/control.py). The [SDK reference](reference/control-sdk.md)
explains request serialization and lifecycle.

## Follow a learned request

For a temperature request, the host selects and loads a model plugin before handling queries:

- functiongemma-tasks proposes a compact select_task decision. Installed task code compiles it.
- task-classifier selects the same reference tasks through a separately trained baseline.
- Legacy functiongemma proposes a complete plan through submit_plan.
- bounded-commands is a deterministic reference-task grammar, not another learned model.

Those planners do not currently understand the new light-control vocabulary. A new adapter
implementation or capability description does not qualify existing model weights for it.

GatewaySession wraps the planner for persistent request/plan binding. The lab's gateway module
is a compatibility re-export; application ownership is no longer lab-only. Model loading and
preparation remain caller-owned. Profiles used by plan/interactive are saved context, not live
devices; those clients never execute. See the [model tutorial](model-tutorial.md).

## Confirmed, failed and unknown are different

For deadline-aware adapters, Executor uses invoke_bounded with an operation identity and
deadline. Legacy simulation adapters use invoke and in-memory replay; they do not establish
durable live-device guarantees.

If an acknowledgement is lost after a write, the write may already have happened:

- return execution_unknown, not confirmed failure;
- stop dependent steps and block new work on that device while an unresolved claim remains;
- reconcile the original receipt without blindly invoking the write again.

A successful reconciliation settles the recorded operation; it does not resume later steps
or prove a complete user task succeeded. A replayed success is historical, not a fresh reading.

The light emulator can commit state and receipts atomically in SQLite. A physical device
cannot inherit that claim. No exactly-once physical execution or automatic rollback is promised.
See [recovery](how-to/reconcile.md) and [result meanings](reference/results.md).

## Responsibilities and dependencies

| Component | Owns | Must not claim or do |
| --- | --- | --- |
| contracts/ | Bounded request, capability, state, policy and plan types | Interpret arbitrary intent or execute |
| application/ | Sessions, registry, lifecycle, caller-facing composition | Bypass authorization |
| planner/ | Deterministic compilation and optional model translation | Authorize its own output |
| ir/ and policy/ | Validation, fingerprints, permissions, approvals | Dispatch operations |
| runtime/ | Coordination, durable execution and recovery ports | Import lab or simulator implementations |
| adapters/ and simulator/ | Implement device operations and receipt lookup | Claim physical evidence from software tests |
| model_plugins/ | Artifact compatibility and planner factories | Automatically teach old weights new actions |
| edge_delegate_lab/ | Dataset review, training and evaluation | Be required by the core application |

Executable extensions are trusted installed code. Profiles and manifests are data, not arbitrary
module import paths. The deterministic SDK runs without PyTorch or other machine-learning
packages. Dependency tests enforce important import boundaries; they are not a security sandbox.

## Interfaces and versioning

- ControlRequest v1 is an outer, single-target envelope with boolean/integer parameters.
- TaskDecision bounded-task.v1 belongs to the separate reference model path.
- Both can compile to unchanged plan-ir.v0.
- Control results wrap the existing edge-gateway-result.v1 response.
- Candidate pack inspection still requires the legacy local-display catalog and decimal policy.
  It is not yet generalized deployment configuration for the new controls.

Keep these contracts distinct. Existing model artifacts and temperature commands must not
silently acquire new meanings. See [schemas](../schemas/) and [release scope](release-contract.md).

## Command-line boundaries

The [generated command reference](reference/cli.md) is authoritative for the current command
inventory. In brief: edge-delegate owns dependency-free core commands; edge-delegate-lab owns
model/data/diagnostic workflows; edge-delegate-device runs the separate-process Unix emulator.
The control-demo lights are in-process SQLite devices, not that Unix emulator.

## Still planned

The active [roadmap](roadmap.md) covers generalized task packs, spawned inference-worker
supervision, a bounded request queue, whole-request deadlines and cancellation, jobs, rules,
and physical qualification. Neither synchronous session currently implements the production
service or guarantees a whole-request deadline. A step deadline is not an end-to-end deadline.

The [current-status page](qualification-status.md) owns measured results; this architecture
page does not grant a release qualification.
