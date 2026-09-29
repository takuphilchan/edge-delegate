# Current implementation and qualification status

[Roadmap](roadmap.md) | [Release contract](release-contract.md) | [Historical evidence](history/qualification-status-through-2026-09-28.md)

**Experimental developer software. No supported physical deployment or production release is qualified.**
This page summarizes current capabilities; the dated archive preserves measurements, artifact
paths and failed experiments. Documentation changes do not retrain or qualify models.

## What works, and what that establishes

| Area | Implemented / observed | Still missing |
| --- | --- | --- |
| Structured control SDK | Explicit target/action/parameters; preview, execution, status, reconciliation | Supervisor, whole-request deadlines, generalized production packs |
| Software lights | Independent power/brightness, reads, ambiguity rejection, durable duplicate/recovery handling | Physical effects, long soak, deployment reliability |
| Deterministic commands | Closed light grammar; separate three-task bounded-commands plugin | Unrestricted language understanding; neither path is learned inference |
| Learned model path | Compact FunctionGemma decisions through compiler and runtime | Representative quality; existing weights do not control lights |
| Installation | Automated clean-wheel checks outside checkout without ML dependencies | Independent adopter installation and recovery exercises |
| Review tooling | Blind review ledger, adjudication and confirmation checks | Actual independent pilot approval; structural validation is not approval |

Control-batch verification baseline (28 September): **583 software tests passed, one
hardware test excluded**, including 37 control tests; lint and clean-wheel acceptance passed.
This is a dated software baseline, not a live test count or production certificate.

## Documentation verification (29 September 2026)

After restructuring: **596 software tests passed, one hardware test deselected**. Ruff,
diff whitespace checks and the parser-generated command reference check passed.
Clean-wheel acceptance ran outside the checkout without ML dependencies. It executed the
tutorial's actual command blocks and public SDK example, checking exact effects, preview and
ambiguity non-actions, unchanged operation records on replay and installed-package imports.
Recursive Markdown checks cover local file links and heading anchors.

This is automated software/documentation evidence. No model was retrained or requalified,
no independent labels were approved, and no hardware, soak or independent adoption gate passed
as part of this change.

## Known model-quality blocker

The real-model numeric development diagnostic passed **26/36**, including a wrong-but-permitted
action: an unsupported upload compound caused a temperature read and display write.
Other errors included unnecessary refusal, incorrect clarification and malformed plans.
This blocks learned-candidate promotion. Strict parsing is retained rather than repairing guesses.

The deterministic numeric baseline passed **36/36** on those exposed development cases.
That is not a model fix, independent holdout result or physical qualification.
Broader validation and numeric reports remain in the [evidence archive](history/qualification-status-through-2026-09-28.md).

## Timing and outcome claims

User smoke runs show that the optimized temperature path can complete the small tested workload
below one second. They do not establish the full three-run release performance gate.
Historical 188–193 ms P95 results used RAM-backed temporary storage; they are not disk-backed
deployment performance. Manual light-demo timings are also not qualification.

Execution success means the runtime completed the proposed operations, not that it proved
user intent. Reconciliation can establish an operation receipt; it does not automatically
resume dependent steps or verify task completion. See [result semantics](reference/results.md).

## Next work

Follow the [single roadmap](roadmap.md#next-engineering-batches): finish generalized pack/evidence
binding, supervised deadlines and admission, actual reviewed data and qualified candidates,
then named hardware and operational acceptance. Jobs, rules and a public local service remain
planned. No independent approval, physical qualification, field pilot or new model result is
created by the documentation refactor.
