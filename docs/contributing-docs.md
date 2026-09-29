# Maintaining documentation

[Documentation home](README.md)

Documentation must let a reader complete a task and understand what the result proves.
Do not make readers reconstruct the current system from a chronological development log.

## One owner for each question

| Question | Authoritative page |
| --- | --- |
| What is it / where do I start? | Root README and try-it |
| How do components connect? | system-architecture |
| Which calls and results exist? | reference/ |
| What is implemented or qualified? | qualification-status |
| What should be built next? | roadmap |
| What did an earlier experiment show? | history/ |

Tutorials teach one working path. How-to pages solve one task. References describe interfaces.
Explanations discuss design. Link between these instead of repeating a full quickstart.
Keep old useful URLs as signposts; archive historical evidence rather than deleting failed results.

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
python -m pytest -q tests/architecture/test_documentation.py tests/unit/test_documentation_checks.py
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
