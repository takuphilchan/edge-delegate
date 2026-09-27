# Configuration

Committed configuration files describe reproducible candidates and experiments. Machine-specific paths, credentials, and local overrides do not belong here.

| Directory | What consumes it | Status |
| --- | --- | --- |
| `training/` | `edge-delegate-lab train --config ...` | Executable training recipes. |
| `inference/` | Model commands with `--plugin-settings ...` | Opt-in compiled inference and versioned numeric-policy settings; not qualified defaults. |
| `model/` | Human reference | Candidate descriptions, not a universal inference config. Qwen is a scaffold, not an implemented plugin. |
| `evaluation/` | Human reference | Evaluation descriptions; the current CLI takes dataset and model flags, not these YAML files. |
| `local/` | Explicit commands pointing at ignored local files | Machine-specific experiments and plugin settings; never commit credentials. |

To use a trained model, pass its `final-adapter` directory via `--adapter`. To preview against a
device description, pass a directory with capabilities/state/policy JSON via `--profile`.
A profile is not a hardware driver. Start with the [testing walkthrough](../docs/try-it.md).

`inference/numeric-decimal-v1.json` selects the shared strict decimal policy for either bounded
plugin. `inference/functiongemma-tasks-compiled-decimal-v1.json` additionally enables FunctionGemma
compiled decoding. Existing settings files are unchanged and retain legacy numeric behavior.
See [numeric policy](../docs/model-plugins-and-compute.md#versioned-numeric-policy-for-bounded-tasks)
for grammar, compatibility, and test commands.
