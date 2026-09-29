# Glossary

[Documentation home](README.md)

Use this page whenever a term in the code, configuration, reports, or documentation is unfamiliar. Acronyms are expanded before the project-specific meaning is explained.

## Acronyms

For the gateway preview: a **task decision** selects a supported operation; the **task catalog**
contains trusted code that builds its steps. The **operation journal** records work before it
is dispatched. **Reconciliation** asks the device what happened to an earlier operation.
An **unknown outcome** means the action may have happened; it is not permission to retry.
**P95 latency** is the time at or below which 95% of measured requests completed.

| Acronym | Full term | Meaning in Edge Delegate |
| --- | --- | --- |
| API | Application Programming Interface | A defined way for software components to communicate. The public application SDK and device adapter interfaces are APIs; external-model dispatch remains unimplemented. |
| BF16 | Brain Floating Point, 16-bit | A compact number format used for model training and inference. It reduces memory use while keeping a useful numerical range. The RTX 5060 supports it. |
| BM25 | Best Matching 25 | A text-ranking method. Edge Delegate uses it to select the capability descriptions most relevant to a request without loading another model. |
| CI | Continuous Integration | Automated tests run when code changes are proposed or pushed. |
| CLI | Command-Line Interface | A terminal interface. `edge-delegate` is the small runtime CLI; `edge-delegate-lab` owns host-side data, model, training, and evaluation commands. |
| CPU | Central Processing Unit | The computer's general-purpose processor. Reports use CPU memory measurements even when model computation runs on the GPU. |
| CUDA | NVIDIA's parallel-computing platform | The software layer PyTorch uses to run model computation on an NVIDIA GPU. |
| GB | Gigabyte | A unit used for model size and memory measurements. Hardware vendors and software may calculate it slightly differently. |
| GPU | Graphics Processing Unit | The processor used here for FunctionGemma inference and LoRA training. |
| ID | Identifier | A stable name that distinguishes a request, capability, step, record, or scenario group from others. |
| IR | Intermediate Representation | A small structured format between natural language and execution. `Plan IR` is the project's typed plan format. |
| JSON | JavaScript Object Notation | The structured text format used for public contracts and plans. |
| JSONL | JSON Lines | A dataset format containing one complete JSON object per line. |
| LLM | Large Language Model | A language model capable of general text processing. FunctionGemma is much smaller and specialized for function calling; a future external LLM may handle complex text. |
| LoRA | Low-Rank Adaptation | A training method that learns a small set of adapter weights while leaving the base model weights frozen. |
| MCU | Microcontroller Unit | A small embedded processor. Direct MCU deployment is future work, not part of the current simulator runtime. |
| ML | Machine Learning | The optional model-related portion of the project. The deterministic core does not require ML packages. |
| PEFT | Parameter-Efficient Fine-Tuning | The Hugging Face framework used to attach and load the small LoRA adapter instead of retraining every model parameter. |
| RSS | Resident Set Size | An operating-system measurement of how much physical memory a process currently occupies. Model diagnostics report CPU RSS before and after load/generation. |
| SDK | Software Development Kit | Public application interfaces that other programs can use without importing lab internals. |
| SFT | Supervised Fine-Tuning | Training on examples that contain an input and a known correct output. The selected plugin defines the output: legacy full-plan calls or compact task decisions. Reviewed labels are required before promotion. |
| SHA-256 | Secure Hash Algorithm with a 256-bit output | A stable fingerprint used to bind approvals to an exact canonical plan and to fingerprint datasets. It identifies content; it does not encrypt it. |
| TRL | Hugging Face TRL post-training library | The library that provides `SFTTrainer`. Its historical name refers to Transformer Reinforcement Learning, but this project uses its supervised fine-tuning support. |
| WSL | Windows Subsystem for Linux | The Ubuntu/Linux environment used for Python, PyTorch, CUDA access, training, and tests on this Windows PC. |
| YAML | YAML Ain't Markup Language | The human-readable configuration format used by files such as `configs/training/pilot.yaml`. |

## Project concepts

| Term | Plain-language definition |
| --- | --- |
| Actuator | Hardware that changes the physical world, such as a relay, motor, valve, or display. Actuator operations receive stricter side-effect and idempotency checks than sensor reads. |
| Adapter | Ambiguous without a qualifier: a model adapter is learned weights loaded with a base model; a device adapter is installed code implementing transport, snapshots and bounded invocation. They are not interchangeable. |
| Approval | A temporary authorization tied to one request, one capability, an expiry time, and the fingerprint of one exact plan. |
| Artifact | A generated file such as a model report, checkpoint, adapter, or TensorBoard log. Artifacts are stored locally and ignored by Git. |
| Artifact manifest | The versioned `edge-delegate-artifact.json` file that binds an adapter to its plugin, exact base revision, tokenizer, protocol, datasets, recipe, and file fingerprints. |
| Attention backend | The implementation used for the model's attention calculation, such as eager attention or PyTorch Scaled Dot Product Attention (SDPA). A plugin declares which implementations it supports. |
| Base model | The original `google/functiongemma-270m-it` weights before project-specific training. |
| Backend | The implementation that actually asks a model to generate output. Tests use a scripted backend; real inference uses the Transformers backend. |
| Canonical plan | A plan serialized in one stable key order and number/string representation so the same plan always gets the same fingerprint. |
| Capability | One operation the device declares it can perform, such as reading temperature or writing to a display. |
| Capability card | The typed description of a capability: identifier, arguments, result, side effects, permissions, approval requirement, privacy classes, preconditions, and resource cost. |
| Checkpoint | Adapter weights saved at a point during training, usually after an epoch. Selection depends on the recipe: legacy training can use validation loss; compact-task candidates are compared on validation outcomes. Lower loss alone is not qualification. |
| Chat template | Model-specific rules that serialize roles, messages, tools, and tool calls into the exact text/token sequence expected by a model. |
| Context window | The maximum number of tokens a model can receive and generate in one operation. A training label must fit completely; silently cutting it off would teach incomplete plans. |
| ControlRequest | A typed single-target action request bound to a device/endpoint, registration and catalog fingerprint. It is compiled to Plan IR, not dispatched directly. |
| ControlSession | The synchronous public SDK that owns targeted preview, execution and receipt reconciliation. It is not a supervised service. |
| Endpoint | An operation target within a device. Current controls support one endpoint per device, named main by default. |
| Receipt | A durable record of an operation outcome. Replaying a receipt is not a fresh device observation. |
| Qualification | Evidence that an exact supported configuration passed declared gates. Implemented features or a passing demo are not qualification. |
| Contract | A versioned agreement about fields, types, limits, and meaning at a component boundary. Contracts let different implementations exchange data without guessing. |
| Coordinator | The runtime component that obtains state, asks a planner for a proposal, validates it, chooses the route outcome, and allows execution only when safe. |
| Compute plan | A machine-readable choice of device, precision, attention backend, microbatch, gradient accumulation, data-loading workers, and memory ceiling resolved before model weights load. |
| Deterministic | Given the same valid inputs and state, the code follows the same explicit rules instead of sampling a model response. |
| Device gateway | The runtime interface that exposes the clock, capability cards, a state snapshot, and capability invocation. The simulator implements it today; future hardware adapters must implement the same interface. |
| Edge runtime | The dependency-free `edge_delegate` package path that owns contracts, validation, coordination, and execution. Model training and evaluation are not part of this boundary. |
| Epoch | One complete pass over the training split. |
| Fail-closed | When parsing, validation, authorization, or execution is uncertain or fails, the system rejects or stops instead of continuing. |
| Fine-tuning | Additional training that adapts an existing base model to a narrower task. This project fine-tunes an adapter, not every base-model weight. |
| Fingerprint | A SHA-256 identifier computed from canonical content. A changed plan or dataset has a different fingerprint. |
| Function call / tool call | Structured model output that names a function and supplies arguments. Legacy FunctionGemma uses `submit_plan`; the compact-task plugin uses `select_task`. Neither function invokes a device directly. |
| FunctionGemma | Google's 270-million-parameter model specialized as a starting point for function-calling tasks. It is expected to be fine-tuned for a specific workflow. |
| Gold plan | A known correct plan authored by project rules and verified through the deterministic validator/simulator, not copied from model output. |
| Gradient accumulation | Combining gradients from several small training steps before updating weights. It creates a larger effective batch without requiring all examples to fit in GPU memory together. |
| Handoff | A bounded package of redacted context and questions that may eventually be sent to an external model. The contract exists; the connector does not. |
| Harness | Test tooling that supplies inputs, runs a component, and records or checks outcomes. The lab contains model/evaluation harnesses; the reusable runtime is not just a harness. |
| Hardware adapter | Code that implements declared capabilities against real sensors and actuators while preserving the same typed runtime boundary used by the simulator. |
| Host lab | The `edge_delegate_lab` package and CLI used on a development machine for data generation, plugin inspection, training, artifact verification, and evaluation. It is not imported by the runtime. |
| Hyperparameter | A training setting chosen before or around a run, such as learning rate, adapter rank, batch size, or epoch count. |
| Idempotency key | A key used to detect repeated calls. An identical input with a recorded successful result replays that result; conflicting reuse is rejected. Persistent gateway sessions use durable SQLite claims and receipts; simple simulator paths can be in-memory. Unknown writes require reconciliation, not blind replay. This is not exactly-once physical execution. |
| Inference | Running a trained model to generate an output. It changes no model weights. |
| Learning rate | The size of optimizer updates during training. Too large can destabilize learning; too small may make the run ineffective. |
| Loss mask | A token-level selector telling training which output tokens should contribute to the error calculation. Here it selects only the assistant's tool call. |
| Model doctor | A small integration diagnostic that loads the real model, generates controlled cases, records resource use, and validates proposals without executing them. |
| Model plugin | An installed, versioned adapter that turns one model family's input/output format into the shared typed planner interface. It may also own model-specific data export and training. |
| Microbatch | The number of examples processed on a device in one forward/backward step. Gradient accumulation combines multiple microbatches into a larger effective batch. |
| Optimizer | The training algorithm that updates adapter weights from calculated gradients. |
| Overfitting | Learning the small training set so specifically that measured training performance improves without reliable behavior on unseen requests. |
| Plan IR | The Plan Intermediate Representation: route, ordered capability steps, arguments, reason codes, confidence, and optional clarification. It is data, not executable code. |
| Planner | A replaceable component that proposes Plan IR. It may be a static test planner, scripted backend, base model, or trained adapter. |
| Planning request | The typed input containing a request ID, natural-language text, locale, and bounded metadata. A proposed plan must repeat the same request ID. |
| Policy | Deterministic configuration describing permissions, capability allow/deny rules, approvals, external-processing rules, state freshness, and resource budgets. |
| Precondition | A condition that must be true in current device state before a capability may run. |
| Preflight | Read-only checks performed before training: label validity, split leakage, tokenizer rendering, and truncation risk. |
| Prompt | The serialized instructions and context given to a model for one proposal. Prompt changes can change model behavior even when weights stay the same. |
| Quantization | Representing model weights with fewer bits to reduce memory and sometimes improve edge inference speed. It is a future export/benchmark choice, not part of the current pilot training path. |
| Query client | The non-executing `plan` or `interactive` lab command used to try arbitrary requests against a model, device profile, parser, and validator. It is a diagnostic interface, not a chatbot or actuator controller. |
| Query profile | A directory containing `capabilities.json`, `state.json`, and `policy.json`. It supplies the typed context required to interpret and validate an arbitrary query. |
| Resource budget | Policy limits on step count, latency, memory, energy, and timeout for one plan. |
| Route | The plan's high-level outcome: `local`, `hybrid`, `external`, `clarify`, `defer`, or `deny`. |
| Safety split | Held-out adversarial or dangerous examples used to measure unsafe behavior. They are isolated from ordinary training and evaluation groups. |
| Scenario group | Related examples that share a template, paraphrase cluster, and device family. The complete group stays in one dataset split to prevent leakage. |
| Schema | A machine-checkable description of a public JSON contract. The files in `schemas/` define required fields, allowed values, and limits. |
| Sensor | Hardware that observes the world without intentionally changing it, such as a temperature or battery sensor. |
| Simulator | Software standing in for a device. The project has in-process fixtures, persistent software lights and a separate-process Unix-socket emulator. None verifies physical effects. |
| Side effect | A declared consequence of a capability: no change, a logical write, or a physical-world action. It determines which additional safety rules apply. |
| Static validation | Checking the entire proposal without executing it. This includes shape, capability, type, policy, approval, state, connectivity, and resource rules. |
| TensorBoard | A local tool for viewing training metrics recorded over steps and epochs. Its logs are generated artifacts and are not committed. |
| Test split | Held-out examples used for final comparison after training choices are made. They must not guide optimizer updates or checkpoint selection. |
| Token | A piece of text represented by one model input/output identifier. Token count affects context size, memory use, and training truncation. |
| Tokenizer | Model-specific code that converts text and structured chat content into token IDs and converts generated IDs back into text. |
| Training loss | A number measuring token-prediction error on training examples. Lower loss does not by itself mean the generated plans are safe or correct. |
| Training export | A model-specific view of canonical scenario records, such as FunctionGemma chat messages and tool calls. Canonical labels stay model-neutral. |
| Training split | Examples used to calculate gradients and update adapter weights. |
| Validation split | Examples excluded from optimizer updates and used to choose a checkpoint during training. This differs from runtime static validation. |
| Validated plan | A capability-, policy-, state-, and plan-bound object issued only after deterministic checks pass. The executor accepts this object, not raw model text or an ordinary Plan IR object. |

## Similar terms that should not be confused

| Terms | Difference |
| --- | --- |
| Training validation vs. static validation | Training validation compares candidate predictions/outcomes (and sometimes loss) on held-out validation examples. Static validation checks whether one proposed plan is executable under current contracts and policy. |
| Permission vs. approval | Permission is an ongoing policy grant. Approval is temporary and bound to one exact plan. A capability may require both. |
| Base model vs. adapter | The base model contains the original weights. The adapter contains the small project-specific changes and cannot run alone. |
| Model doctor vs. benchmark | The doctor checks integration with six controlled cases. A benchmark needs a much larger, frozen, representative dataset. |
| `external_required` vs. external execution | `external_required` is a coordinator status. The current project does not yet send anything to an external model. |

[Previous: Development runbook](development-runbook.md) | [Documentation home](README.md)
