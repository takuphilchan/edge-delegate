# Data workspace

Only manifests, tiny reviewed fixtures, and provenance metadata belong in version control. Raw, interim, and processed data are ignored by default.

Implemented flow:

1. Build executable simulator scenarios.
2. Generate canonical plans and outcomes from deterministic rules.
3. Add controlled, hand-reviewed language variation.
4. Validate every record against the contracts.
5. Group by template, paraphrase cluster, and device family before training; isolate safety cases.
6. Fingerprint the complete build for reproducibility.

Run `edge-delegate generate-data --output data/processed/pilot --seed 17`. The output includes `all.jsonl`, four grouped split files, `manifest.json`, and a FunctionGemma SFT export for each split. Each SFT record carries a scenario group ID and expected route so training preflight can reject record or group leakage. Processed output remains ignored because it can be regenerated from committed scenarios.

The current 36-record pilot is deliberately small. Its 20-record training split covers local, clarify, defer, and external routes; validation contains one hybrid scenario family; isolated safety contains deny cases. This is enough to test the adapter pipeline, but it is not balanced enough for a deployment-quality model.

The generated manifest currently marks the corpus `UNLICENSED` because this repository has no committed project license. Select and commit a project license before publishing or redistributing dataset builds.
