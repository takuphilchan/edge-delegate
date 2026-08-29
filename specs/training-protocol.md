# Training Protocol

Status: pilot LoRA pipeline implemented; corpus expansion required

## Boundary

Training may improve proposal quality, but it never moves the model into the security boundary. Every generated plan remains subject to strict parsing, request binding, static validation, policy checks, and fail-closed coordination before execution.

## Reproducible run

1. Generate simulator-backed labels and grouped splits with a fixed seed.
2. Validate every SFT tool call as Plan IR.
3. Reject train/evaluation record or scenario-group overlap.
4. Render every example with the exact FunctionGemma template and reject any example that would be truncated.
5. Apply a training-only Jinja generation mask around serialized tool-call tokens. The markers change loss selection but not rendered inference text.
6. Train a BF16 LoRA adapter over all linear layers. Never push checkpoints automatically.
7. Select the lowest validation-loss checkpoint, save the adapter and tokenizer, and record configuration, package versions, model revision, dataset fingerprints, hardware, memory, timing, and metrics.
8. Load the saved adapter through the production planner backend and run non-executing diagnostics before any broader evaluation.

## Current pilot limits

The 36-record corpus is a pipeline fixture, not a sufficient training dataset. Its training split has five scenario groups and no deny examples; its validation split has one hybrid group. The pilot adapter learned the FunctionGemma wrapper and Plan-IR envelope but often emitted empty steps, missed clarification content, and confused external, hybrid, deny, and defer behavior.

The next dataset version needs multiple independent scenario groups per route in train, validation, and test; more multi-step and direct-argument plans; safe deny demonstrations distinct from held-out attacks; capability-set variation; policy/state counterfactuals; and multilingual utterances. Improvements must be judged on frozen grouped and safety splits, never on training loss alone.
