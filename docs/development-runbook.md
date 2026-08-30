# Development Runbook

[Documentation home](README.md) | [Glossary](glossary.md)

## Who this is for

Use this page for commands, expected evidence, and troubleshooting. It assumes the boundaries
described in [System architecture](system-architecture.md); it does not redefine them.

## First choose what you are trying to do

| Goal | Needs a Graphics Processing Unit (GPU)? | Needs Hugging Face login? | Command path |
| --- | ---: | ---: | --- |
| Run deterministic demo/tests | No | No | Install `dev`, then run `demo` or `make verify`. |
| Validate an existing plan | No | No | Run `edge-delegate validate`. |
| Generate/evaluate gold data | No | No | Run `edge-delegate-lab generate-data`, then `evaluate --planner gold`. |
| Measure the base FunctionGemma model | Yes for useful speed | Yes | Install `inference`, then run `edge-delegate-lab model-doctor`. |
| Preflight training data | No model weights, but tokenizer access is needed | Yes on first download | Install `training`, then run `edge-delegate-lab train --preflight-only`. |
| Train the Low-Rank Adaptation (LoRA) adapter | Yes; Brain Floating Point 16-bit (BF16) is required by the pilot config | Yes | Run `edge-delegate-lab train` with a fresh output directory. |
| Evaluate a trained adapter | Yes for useful speed | Yes for the base model | Run the lab's `model-doctor` or `evaluate` with `--adapter`. |
| Type arbitrary queries into a trained adapter | Yes for useful speed | Yes for the base model | Run `edge-delegate-lab plan` once or `edge-delegate-lab interactive` for a prompt loop. |

## Use the correct shell

Run Python, Hugging Face, CUDA, training, and test commands inside Ubuntu on Windows Subsystem for Linux (WSL):

```bash
wsl
cd /mnt/d/project/edge-delegate
source /home/phil/.venvs/edge-model/bin/activate
```

The prompt should begin with `(edge-model)`. Do not run the Linux activation path from Git Bash or PowerShell; `/home/phil/...` exists inside WSL, not in the Windows shell.

Git commands can run from WSL or from Windows Git Bash, provided Git considers the repository a safe directory for that user.

## Verify the existing machine environment

```bash
python --version
python -c 'import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name())'
nvcc --version
```

Expected important values on this PC:

- `torch.cuda.is_available()` is `True`.
- Device name is `NVIDIA GeForce RTX 5060 Laptop GPU`.
- PyTorch includes CUDA support.

The CUDA compiler version and the CUDA version packaged with PyTorch do not need identical text labels. The decisive check for this project is that PyTorch can see and use the GPU.

## Install project dependency groups

From the repository root in WSL:

```bash
python -m pip install -e ".[dev]"
python -m pip install -e ".[inference]"
python -m pip install -e ".[training]"
python -m pip check
```

- `dev` installs tests and lint tools.
- `inference` installs real-model inference dependencies. `planner` remains a compatibility alias for older commands.
- `training` installs dataset, Parameter-Efficient Fine-Tuning (PEFT), Transformer Reinforcement Learning (TRL), TensorBoard, and configuration dependencies.

The core runtime itself intentionally has no third-party dependency.

## Authenticate for FunctionGemma

First accept the FunctionGemma license on its Hugging Face model page. Then, inside WSL:

```bash
hf auth login
hf auth whoami
hf download google/functiongemma-270m-it config.json
```

The final command is a small access check. It does not download all model weights.

Do not store a Hugging Face token in the repository, configuration files, shell history, or `.env.example`.

## Inspect model plugins and compute

These commands do not load model weights:

```bash
edge-delegate-lab models
edge-delegate-lab compute-inspect
edge-delegate-lab compute-plan --plugin functiongemma --attention-backend eager
```

Check that the selected precision, attention backend, context limit, effective batch, and video-memory fraction match the intended experiment before training. See [Model plugins, artifacts, and compute](model-plugins-and-compute.md) for each field.

## Workflow 1: deterministic runtime

Run the simulator-backed example:

```bash
edge-delegate demo
```

Expected flow:

```text
read temperature -> validate complete plan -> invoke sensor -> pass result by reference
-> invoke display -> return executed
```

Validate the committed example without executing it:

```bash
edge-delegate validate \
  --capabilities examples/local-display/capabilities.json \
  --state examples/local-display/state.json \
  --policy examples/local-display/policy.json \
  --plan examples/local-display/plan.json \
  --now 2026-01-01T12:00:00Z
```

Exit code `0` means valid, `2` means a well-formed plan failed validation, and `1` means malformed input or an operational error.

## Workflow 2: rebuild and verify the pilot dataset

```bash
edge-delegate-lab generate-data \
  --output data/processed/pilot \
  --seed 17

edge-delegate-lab evaluate \
  --dataset data/processed/pilot/all.jsonl \
  --planner gold \
  --output artifacts/evaluation/gold-self-check.json
```

The gold self-check should be perfect. It confirms that dataset generation and evaluation agree; it does not measure a model.

Generated data is reproducible and ignored by Git. The manifest records counts, split hashes, dataset hash, seed, provenance, and each selected plugin's supervised fine-tuning export.

## Workflow 3: measure the untrained base model

```bash
edge-delegate-lab model-doctor \
  --model-id google/functiongemma-270m-it \
  --output artifacts/model-doctor/functiongemma-prompt-baseline.json
```

The doctor loads the model, runs one controlled case for each route, saves raw proposals and resource measurements, and never executes a proposed capability.

Operational success means the model loaded and generated text. It does not mean the plans parsed or passed policy checks. Inspect both `operational` and `quality_smoke` in the report.

## Workflow 4: preflight before training

```bash
edge-delegate-lab train --plugin functiongemma \
  --config configs/training/pilot.yaml \
  --preflight-only
```

Do not start training unless the report shows:

- no record overlap;
- no scenario-group overlap;
- `truncation_required` is `false`;
- non-zero train and evaluation records;
- the expected routes for each split.

For the current data, the output also warns us through its route lists that training has no deny/hybrid group and validation has only hybrid. That is a dataset limitation, not a software error.

## Workflow 5: smoke-train the pipeline

The smoke configuration performs only two optimizer steps:

```bash
edge-delegate-lab train --plugin functiongemma --config configs/training/smoke.yaml
```

Its purpose is to prove that tokenization, loss masks, CUDA training, checkpoint writing, adapter saving, and later adapter loading all work. It is not expected to create a useful planner.

Training refuses to write into a non-empty output directory. For another run, copy the configuration to ignored `configs/local/`, give it a new `output_dir`, and run that local configuration. Do not mix results from different experiments.

## Workflow 6: train the pilot adapter

```bash
edge-delegate-lab train --plugin functiongemma --config configs/training/pilot.yaml
```

The current PC completed the eight-epoch pilot in about 161 seconds. The best validation checkpoint occurred at epoch 5. A lower training loss after that did not mean better held-out behavior.

Important outputs:

```text
artifacts/training/functiongemma-pilot-v0/training-run.json
artifacts/training/functiongemma-pilot-v0/final-adapter/
```

Before loading an adapter, verify its portable manifest and every recorded file:

```bash
edge-delegate-lab artifact-verify \
  --artifact artifacts/training/functiongemma-pilot-v0/final-adapter
```

To require a manifest during inference, create an ignored local plugin-settings file containing:

```json
{
  "allow_legacy_artifact": false
}
```

Pass it as `--plugin-settings configs/local/strict-artifact-settings.json`. Plugin settings are
bounded JSON and must never contain credentials.

## Workflow 7: evaluate the saved adapter

```bash
edge-delegate-lab model-doctor --plugin functiongemma \
  --plugin-settings configs/local/strict-artifact-settings.json \
  --adapter artifacts/training/functiongemma-pilot-v0/final-adapter \
  --output artifacts/model-doctor/functiongemma-pilot-v0.json
```

For a larger chosen dataset:

```bash
edge-delegate-lab evaluate \
  --dataset data/processed/pilot/test.jsonl \
  --planner functiongemma \
  --plugin-settings configs/local/strict-artifact-settings.json \
  --adapter artifacts/training/functiongemma-pilot-v0/final-adapter \
  --output artifacts/evaluation/functiongemma-pilot-test.json
```

No model proposal should be sent to a real actuator during model-quality evaluation.

## Workflow 8: type queries into a saved adapter

The query client needs a profile directory containing `capabilities.json`, `state.json`, and
`policy.json`. It uses that context to construct the real model prompt and statically validate the
result. It never invokes a capability.

Run one query:

```bash
ADAPTER_DIR=artifacts/training/functiongemma-pilot-v0/final-adapter
edge-delegate-lab plan \
  --plugin functiongemma \
  --adapter "$ADAPTER_DIR" \
  --profile examples/local-display \
  --text "Show the current temperature."
```

The command prints selected capabilities, raw generation telemetry, parsed Plan IR, request-ID
binding, and deterministic validation issues. Exit code `0` means the proposal parsed and passed
validation, `2` means the model produced an invalid proposal, and `1` means setup or inference
failed.

Keep the model loaded for several queries:

```bash
edge-delegate-lab interactive \
  --plugin functiongemma \
  --adapter "$ADAPTER_DIR" \
  --profile examples/local-display
```

Interactive commands:

| Command | Effect |
| --- | --- |
| `/context` | Show the active capability IDs, complete state snapshot, and policy. |
| `/raw on` or `/raw off` | Include or hide raw model output in later results. |
| `/help` | Show the command summary. |
| `/quit` | Exit the client and unload the model. |

Use `--plugin-settings configs/local/strict-artifact-settings.json` when you want missing artifact
manifests to fail closed. `--omit-raw-output` starts either client with raw output hidden.

The two-step smoke adapter is expected to fail most queries; use it to verify loading and error
reporting, not model quality. Do not type angle-bracket placeholders such as `<run>` into Bash:
the shell treats them as file redirection. Assign an actual path to `ADAPTER_DIR` as shown above.

## Workflow 9: software verification

```bash
make verify
make test-hardware
python -m compileall -q src scripts
python -m pip check
```

- `make verify` runs lint and all non-hardware tests.
- `make test-hardware` explicitly checks the configured CUDA target.
- Hardware tests are separated so ordinary continuous integration can run without a GPU.

## Artifact map

| Path | Meaning | Tracked by Git? |
| --- | --- | ---: |
| `data/processed/pilot/manifest.json` | Reproducibility metadata for generated data | No; reproducible |
| `data/processed/pilot/*-sft-*.jsonl` | FunctionGemma training/evaluation lines | No; reproducible |
| `artifacts/model-doctor/*.json` | Raw model integration diagnostics | No |
| `artifacts/evaluation/*.json` | Evaluation reports | No |
| `artifacts/training/{run-id}/checkpoint-*` | Intermediate adapters | No |
| `artifacts/training/{run-id}/final-adapter/` | Selected adapter used with `--adapter` | No |
| `artifacts/training/{run-id}/final-adapter/edge-delegate-artifact.json` | Portable plugin/base/tokenizer/protocol/dataset/file binding | No |
| `artifacts/training/{run-id}/training-run.json` | Config, versions, fingerprints, hardware, and metrics | No |
| `configs/training/*.yaml` | Reproducible committed experiment settings | Yes |
| `configs/local/` | Machine-specific or one-off settings | No |

## Common problems

| Symptom | Meaning | Resolution |
| --- | --- | --- |
| `/home/phil/.../activate: No such file or directory` | Linux virtual-environment path was used outside WSL. | Enter WSL first, then activate. |
| `hf: command not found` | The active environment lacks Hugging Face tooling or is the wrong shell/environment. | Activate `edge-model`, install the inference/training extra, and retry. |
| `Permission denied (publickey)` from GitHub | Git SSH authentication is unrelated to Hugging Face model access. | Fix the SSH key in the shell performing Git operations; do not add the same key twice on GitHub. |
| Model load says license/access failed | Hugging Face account has not accepted the gated model terms or the WSL environment is not authenticated. | Accept the license, run `hf auth login`, then the small `hf download` access check. |
| `training output directory is not empty` | Run isolation guard prevented mixed checkpoints. | Use a new run name/output directory in an ignored local config. |
| `SFT examples exceed max_length` | At least one label would be silently cut off. | Increase the declared context limit if hardware/model allow it, or deliberately reduce prompt content; do not bypass the check. |
| `unsupported FunctionGemma chat template` | Upstream template changed, so the loss-mask anchors may no longer be safe. | Review the new template, then update and test the marker logic before training. |
| TRL warns that an end token is outside the assistant mask | TRL's generic probe uses ordinary assistant text, while this dataset targets tool calls. | Require the preflight `assistant_loss_mask` checks to pass for every record; do not ignore an empty or incomplete mask. |
| CUDA is unavailable | PyTorch cannot use the NVIDIA GPU in the active WSL environment. | Recheck `torch.cuda.is_available()`, WSL driver visibility, and the activated environment. |
| Out-of-memory error | Batch/context/adapter settings exceed GPU memory. | Reduce per-device batch first; preserve complete examples and use gradient accumulation rather than truncating labels. |
| All generations succeeded but quality is zero | The model ran, but its proposals failed parsing or correctness checks. | Inspect raw doctor outputs and failure categories; this is a model/data problem, not proof that the runtime failed. |
| `invalid choice: interactive` or `invalid choice: plan` | The active editable install predates the query client. | From the repository root, rerun `python -m pip install -e ".[training]"`, then check `edge-delegate-lab --help`. |
| `external_required` result | The route is valid, but connector execution is intentionally not implemented. | Treat it as an explicit handoff requirement, not a completed external answer. |

## Decision gates before moving forward

| Gate | Required evidence |
| --- | --- |
| Software gate | Lint, software tests, hardware test, compilation, and dependency check pass. |
| Data gate | Labels validate/execute, provenance exists, grouped splits do not overlap, and route coverage is visible. |
| Training gate | No truncation, finite loss/gradients, run metadata written, and best adapter saved. |
| Integration gate | Adapter loads through the production backend and model doctor generations all complete. |
| Quality gate | Frozen test/safety metrics improve in static validity, routing, exact plans, execution, and safety. The current pilot does not pass this gate. |
| Deployment gate | Target-device latency, memory, package size, energy, persistent safety controls, and hardware adapters meet declared limits. Not implemented yet. |

[Previous: Model lifecycle](model-lifecycle.md) | [Next: Glossary](glossary.md)
