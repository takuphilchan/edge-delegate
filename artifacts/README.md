# Local artifacts

Generated reports, checkpoints, adapters, and TensorBoard logs are ignored by Git. They may contain model outputs or machine-specific paths and should not be published without review.

Expected local paths include:

- `model-doctor/` for prompt-only and adapter integration diagnostics
- `training/<run>/training-run.json` for reproducibility metadata
- `training/<run>/final-adapter/` for the selected Parameter-Efficient Fine-Tuning (PEFT) adapter
- `training/<run>/final-adapter/edge-delegate-artifact.json` for the portable plugin, base revision, protocol, tokenizer, dataset, recipe, and file-fingerprint binding

The deterministic source data can be regenerated; trained weights require the matching run metadata and dataset fingerprints to be reproducible.

See [Model plugins, artifacts, and compute](../docs/model-plugins-and-compute.md) for compatibility rules, [Model lifecycle](../docs/model-lifecycle.md) for how these files are produced, and [Development runbook](../docs/development-runbook.md) for the commands that create and inspect them.
