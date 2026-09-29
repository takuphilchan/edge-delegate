# Maintaining documentation

[Documentation home](README.md)

Documentation must let a reader complete a task and understand what the result proves.
Do not make readers reconstruct the current system from a chronological development log.

## One owner for each question

| Question | Authoritative page |
| --- | --- |
| What is it / where do I start? | Root README and docs/README |
| How does Rust execution work? | concepts/execution and reference/execution-service |
| How does the existing Python runtime work? | system-architecture |
| Which calls and results exist? | reference/ |
| What is implemented or qualified? | qualification-status |
| What should be built next? | roadmap |
| What did an earlier experiment show? | history/ |

Tutorials teach one working path. How-to pages solve one task. References describe interfaces.
Explanations discuss design. Link between these instead of repeating a full quickstart.
Keep old useful URLs as signposts; archive historical evidence rather than deleting failed results.

## Page structure

Write for a reader completing a task, not for someone following development history.
Use a descriptive title such as “Execute an approved request,” not an implementation batch name.

| Page type | Required content | Keep elsewhere |
| --- | --- | --- |
| Overview | Purpose, present scope, useful example, one starting path | Chronological feature announcements |
| Tutorial | Outcome, platform/tools, numbered steps, expected results, troubleshooting, next step | Exhaustive API tables |
| How-to | Specific problem, conditions, procedure, verification | General product introduction |
| Reference | Exact names, types, defaults/limits, results, errors and compatibility | Multi-page onboarding narrative |
| Explanation | A mental model, responsibility boundaries, decisions and tradeoffs | Copy-pasted setup commands |
| Evidence | Date, configuration, reproducible check, result and limits | Permanent marketing claims |

Tutorials must say which terminal to use and when a foreground process should keep running.
Show expected output fields, not a screenful of changing IDs. Name placeholders explicitly;
provide a complete invocation after a JSON example. Keep consent visible: generating an approval
document is not the same as submitting it. Put warnings before irreversible or state-changing steps.

## Voice and terminology

Use direct, neutral language: “The host records admission” rather than “Our powerful engine
seamlessly ensures reliability.” Use second person for instructions and present tense for
implemented behavior. Avoid “just,” “obviously,” unexplained acronyms and claims such as
“production-ready” without linked qualification evidence.

Define a term once near first use, then use it consistently. Prefer “request ID” to alternating
between job, task and transaction unless those are genuinely different objects. Qualify “adapter”
as device or model when either meaning is possible. The Python and Rust APIs are separate:
always label which one a page documents.

Keep runtime limits and method tables in reference pages. Tutorials link to them rather than
copying them. Keep test counts in the evidence page, not the root README. Preserve useful headings
when possible; update inbound links when changing one.

## Review checklist

Before merging a documentation change, verify that:

- A new reader can state the purpose and next action after the first two paragraphs.
- Every command identifies its platform, working directory and prerequisites.
- Every write distinguishes preview, approval, submission and completed effect.
- Examples contain no maintainer-only credentials, model paths or environment assumptions.
- A failure path tells the reader what to inspect without deleting recovery evidence.
- Planned features are not presented as usable APIs or installable products.
- Links, interface coverage and executable examples pass the checks below.

## Writing and evidence rules

- Open with the reader's goal, prerequisites and expected outcome before internal terminology.
- Explain why an example exists and whether it demonstrates the product goal or only one part.
- End a workflow with a success checkpoint, common failure guidance and a specific next step.
- Do not require readers to follow a long chain of links to learn the system's purpose.
- Prefer one worked example over an unexplained list of class names or features.
- Expand an acronym on first use and link unfamiliar terms to the glossary.
- Say explicitly whether a path is structured, deterministic text parsing or learned inference.
- Separate proposed route, passing validation, confirmed operation and correct user outcome.
- Label planned, experimental, implemented and qualified capabilities distinctly.
- Use environment-relative paths; a maintainer's virtual environment and model artifact are
  not installation prerequisites. State optional model dependencies before model commands.
- Put software-only/execution warnings beside commands, not only on another page.
- Keep current claims in the status page; dated test counts are not permanently current.
- Do not turn machine checks into independent human approval or physical qualification.

## Verification

From an activated development environment at the repository root:

~~~bash
python -m pytest -q tests/architecture tests/unit/test_documentation_checks.py
python scripts/generate_cli_reference.py --check
python -m ruff check .
~~~

The documentation checker discovers Markdown recursively under docs and specs, plus the root
README and pilot fixture instructions. It checks inline local links and ATX heading anchors,
ignores fenced code, and handles duplicate headings. Use inline links and ATX headings in
maintained docs; reference-style links and raw HTML anchors are not the checked convention.

The command inventory is generated from actual argparse parsers:

~~~bash
python scripts/generate_cli_reference.py
~~~

Generation updates a mechanical reference only. Review descriptions and claims separately.
The --check mode exits unsuccessfully if committed output is stale.

The Python command inventory does not cover Rust. The execution-service reference has a
separate coverage check against the Rust command and error enums. This detects missing entries,
not semantic mistakes; review descriptions against the host and client implementations.
On Linux/WSL, run `bash scripts/test-rust-execution.sh` for the real host/CLI approval and
recovery path. No successful diagnostic establishes independent consent or physical qualification.
That script also runs the maintained service tutorial's actual enrollment, preview, approval,
submission and status command blocks against a fresh software device, then checks its state
and restart result. It substitutes isolated state paths and already-built binaries; it never
uses a maintainer's credentials. The tutorial is trusted repository code, not arbitrary input.

The five marked shell blocks in try-it are consumed by scripts/documentation_checks.py.
The runner accepts only edge-delegate control-demo commands with the one test-directory
placeholder; it does not execute arbitrary shell text. Tests assert preview non-action,
specific target effects, ambiguity non-action and duplicate receipt replay. The SDK example
is also run as an installed-package example in clean-wheel acceptance.

For Linux/WSL clean installation acceptance, build wheels into a new temporary directory:

~~~bash
EDGE_WHEELS=$(mktemp -d)
python -m pip wheel --no-deps . ./examples/plugins/counter --wheel-dir "$EDGE_WHEELS"
python scripts/check_wheel.py \
  --wheel "$EDGE_WHEELS"/edge_delegate-*.whl \
  --extension-wheel "$EDGE_WHEELS"/edge_delegate_counter_example-*.whl
~~~

The acceptance script installs into an isolated environment, clears repository import overrides
and runs outside the checkout without ML dependencies. It reads tutorial source from this
checkout but executes the installed package. Temporary demo state is not latency evidence.

These checks detect drift; they do not prove human usability. Two independent developers
still need to complete installation, a request and fault recovery without maintainer help.
Record that evidence separately before claiming adoption qualification.
