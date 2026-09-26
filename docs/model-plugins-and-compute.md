# Model Plugins, Artifacts, and Compute

[Documentation home](README.md) | [Glossary](glossary.md)

This page owns the model-plugin interface, saved-adapter compatibility, and compute-plan
selection. It explains how models remain replaceable without putting model-family code in the
coordinator or executor.

## The short version

The runtime understands a typed planner, not FunctionGemma, Hugging Face, or Low-Rank Adaptation (LoRA). A model plugin translates between one model family's chat/tool format and the shared Plan Intermediate Representation (Plan IR).

Every model plugin must provide:

- a stable plugin identifier and a versioned compatibility descriptor;
- declared precision, attention, context-length, and training capabilities;
- a factory that returns a typed planner;
- a diagnostic session that reports generation behavior without executing proposals.

A trainable plugin may also provide:

- a model-specific export from the canonical dataset;
- a model-specific trainer invoked by the lab;
- a portable artifact manifest consumed again during inference.

FunctionGemma is the first implementation. Shared lab commands call the plugin interface, while
its tokenizer, prompt format, output parser, data export, and trainer remain isolated in
FunctionGemma-specific modules.

## What is shared and what is isolated

| Shared, model-neutral code | Isolated behind a plugin |
| --- | --- |
| Request, capability, state, policy, and Plan-IR contracts | Chat template and tool-call syntax |
| Strict parser and static validator | Tokenizer and model loader |
| Coordinator, executor, audit, and idempotency | Output parsing errors specific to the model format |
| Canonical dataset records and grouped splits | Supervised fine-tuning export format |
| Evaluation metrics and non-executing doctor | Training recipe and loss mask |
| Artifact and compute contracts | Supported precision, attention, and context length |

This separation matters because adding a better model should improve proposal quality without changing execution authority.

## Where the plugin participates

```mermaid
flowchart TD
    Registry[Plugin registry] --> Plugin[Selected plugin]
    Settings[Bounded settings] --> Plugin
    Artifact[Optional adapter artifact] --> Verify[Compatibility + digest verification]
    Verify --> Plugin
    Plugin --> Planner[Construct Planner]
    Planner --> Coordinator[Coordinator uses only Planner interface]

    Canonical[Canonical dataset splits] --> Export[Plugin training export]
    Export --> Training[Plugin trainer]
    Hardware[Hardware inventory + compute request] --> Compute[Resolved compute plan]
    Compute --> Training
    Training --> Artifact
```

Plugin selection and artifact verification happen when the planner is constructed, before a
request enters the coordinator. The artifact never connects directly to validation or execution;
it only changes the planner's model behavior.

The edge CLI does not currently load a model plugin. Its `demo` command constructs a
`StaticPlanner`. The lab CLI uses plugins for generation exports, training, model diagnosis, and
evaluation. Future applications may use the same registry to compose a production runtime.

## Plugin discovery

The entry-point group is:

```text
edge_delegate.model_plugins.v1
```

An installed Python package registers a stable identifier in its `pyproject.toml`:

```toml
[project.entry-points."edge_delegate.model_plugins.v1"]
my_model = "my_package.edge_delegate_plugin:plugin"
```

`edge-delegate-lab` discovers entry points without loading model weights. Selecting a plugin
loads its Python object and validates the version 1 interface; model weights load only when that
plugin creates a real planner or diagnostic session. The in-repository `functiongemma` plugin is
also available as a source-tree fallback before an editable install is refreshed.

Use:

```bash
edge-delegate-lab models
```

Installing a package is a trust decision because its Python entry point can run code when selected. Plugin discovery is not a sandbox for untrusted packages.

Inference and doctor commands accept `--plugin-settings path/to/settings.json`. The file must be a bounded JSON object with no duplicate keys or non-finite numbers; the selected plugin validates its allowed fields. `--model-id`, `--retrieval-limit`, and `--max-new-tokens` remain convenient explicit overrides for compatible plugins, but they have no generic FunctionGemma defaults.

## Portable model artifact

A completed training run writes `edge-delegate-artifact.json` beside the adapter. The manifest binds:

- plugin Application Programming Interface (API) and package versions;
- exact base-model identifier and resolved revision;
- plan protocol and Plan-IR schema versions;
- saved tokenizer/configuration file paths and SHA-256 fingerprints;
- adapter method, format, file paths, and SHA-256 fingerprints;
- training and validation dataset fingerprints;
- training recipe identifier and version;
- context length and supported precision.

When an adapter is loaded, the plugin checks the manifest, uses its recorded base model unless
the operator explicitly supplies a conflicting one, pins the recorded revision, and verifies
file hashes before creating the planner. Verification checks required coverage as well as
digests: a manifest listing only a configuration file cannot leave the weights unchecked.

Each plugin declares `artifact_contracts` in its `ModelPluginDescriptor`. An `ArtifactContract`
names one supported combination of protocol ID, protocol version, Plan-IR schema, adapter
method, and adapter format, plus the adapter and tokenizer files that must have hashes.
The shared verifier checks those declarations; it does not contain model-family filenames.
An empty declaration means the plugin has not opted into loading manifest-bearing artifacts.

FunctionGemma currently supports `functiongemma-submit-plan` version `1`, `plan-ir.v0`, and
LoRA adapters in `peft` format. It requires hashes for `adapter_config.json`,
`adapter_model.safetensors`, `tokenizer.json`, and `tokenizer_config.json`. Additional listed
files, such as `chat_template.jinja`, are also verified. The inference backend currently loads
the processor from the pinned base-model revision, not from the saved tokenizer directory.

Both `artifact-verify` and the FunctionGemma loader call
`manifest.verify_files(root, descriptor=plugin.descriptor)`. This rejects incompatible protocol
versions/schemas, unsupported adapter layouts, missing required hashes/files, and changed file
contents. Package versions remain recorded provenance: a compatible plugin update does not
have to match the training-time package version exactly. These hashes detect inconsistency;
they are not a signature proving an artifact came from a trusted publisher.

Verify an artifact without loading model weights:

```bash
edge-delegate-lab artifact-verify \
  --artifact artifacts/training/functiongemma-pilot-v0/final-adapter
```

Legacy adapter directories without a manifest are temporarily accepted by the FunctionGemma
plugin for compatibility. New artifacts should always contain the manifest. Set
`allow_legacy_artifact` to `false` in plugin settings when testing a strict deployment path.

## Inference context budget

Before generation, the FunctionGemma backend tokenizes the complete prompt, including the
capability cards and tool definition. It requires **prompt tokens + reserved output tokens**
to fit within the context limit. That limit is the smallest of the plugin limit (currently
2,048), the artifact's declared context length when present, and the loaded model's context
limit when available.

An oversized request fails before device transfer or generation; nothing is silently truncated.
Shorten the request, reduce `--retrieval-limit`, or reduce `--max-new-tokens`. A smaller output
budget can still produce an incomplete plan, which the parser rejects. This guard bounds the
context, but does not guarantee that every model configuration fits available GPU memory.

## Compute selection

Compute selection has three inputs:

1. Hardware inventory: logical Central Processing Unit (CPU) cores, system memory, Graphics Processing Unit (GPU), video memory, CUDA runtime, PyTorch version, compute capability, and Brain Floating Point 16-bit (BF16) support.
2. Plugin capabilities: supported precision, attention backend, maximum context, gradient checkpointing, quantized training, and Parameter-Efficient Fine-Tuning (PEFT).
3. Run request: effective batch, context length, requested precision and attention backend, checkpointing choice, and maximum video-memory fraction.

The resolver produces a machine-readable compute plan before model weights are loaded. The current policy is deliberately conservative:

- use CUDA when a compatible GPU is present;
- prefer BF16 when both hardware and plugin support it, otherwise use a declared fallback;
- keep the training microbatch at one and preserve the requested effective batch through gradient accumulation;
- cap the PyTorch process at the configured fraction of GPU memory;
- use at most two data-loading workers on the current small dataset;
- enable pinned memory only for CUDA;
- reject unsupported context, precision, attention, or checkpointing requests.

Inspect the actual machine and resolved plan with:

```bash
edge-delegate-lab compute-inspect
edge-delegate-lab compute-plan --plugin functiongemma
```

Training reports store the inventory, resolved plan, duration, peak allocated GPU memory, peak reserved GPU memory, and token throughput when the trainer provides it.

The resolver does not yet probe several candidate microbatches, sample GPU utilization/power/temperature, or tune for a latency target. Its `selection_source` says `conservative_default_pending_memory_probe` so reports cannot mistake this baseline for an empirical optimum.

## Adding another model correctly

1. Create a separate package or isolated module implementing `InferenceModelPlugin`.
2. Give it a stable lowercase identifier and declare the Plan protocol it understands. For saved artifacts, add `ArtifactContract` entries covering supported versions, schemas, layouts, and every required loader file; call `verify_files(..., descriptor=self.descriptor)` before loading weights.
3. Translate its native output into a typed `PlanIR`; do not return arbitrary text to the coordinator.
4. Implement a diagnostic session so the shared doctor can record model information, selected capabilities, generation telemetry, and model-specific parse failures.
5. If it is trainable, implement the optional training export and trainer methods. Keep its tokenizer, template, loss masking, and trainer code inside that model's implementation.
6. Register the plugin entry point and add a fake-backend contract test that does not download weights.
7. Generate its training export, run preflight, produce a manifest-bearing artifact, and evaluate it on the same frozen canonical records.
8. Only compare deployment candidates after measuring package size, latency, memory, energy, and quality on each declared edge target.

Do not copy FunctionGemma's template or parser into shared code. A second model should share contracts and evaluation records, not model-family assumptions.

[Previous: Contracts and safety](contracts-and-safety.md) | [Next: Model lifecycle](model-lifecycle.md)
