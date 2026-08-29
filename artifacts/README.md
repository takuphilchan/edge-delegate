# Local artifacts

Generated reports, checkpoints, adapters, and TensorBoard logs are ignored by Git. They may contain model outputs or machine-specific paths and should not be published without review.

Expected local paths include:

- `model-doctor/` for prompt-only and adapter integration diagnostics
- `training/<run>/training-run.json` for reproducibility metadata
- `training/<run>/final-adapter/` for the selected PEFT adapter

The deterministic source data can be regenerated; trained weights require the matching run metadata and dataset fingerprints to be reproducible.
