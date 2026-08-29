# Data workspace

Only manifests, tiny reviewed fixtures, and provenance metadata belong in version control. Raw, interim, and processed data are ignored by default.

Planned flow:

1. Build executable simulator scenarios.
2. Generate canonical plans and outcomes from deterministic rules.
3. Add controlled language variation and selected public-data transforms.
4. Validate every record against the contracts.
5. Split by scenario family before training.
6. Fingerprint the complete build for reproducibility.

