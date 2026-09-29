# Project status

[Documentation](README.md) · [Roadmap](roadmap.md) · [Release requirements](release-contract.md)

**Edge Delegate is experimental developer software. No production configuration is qualified.**
The usable Rust path is a Linux/WSL execution service backed by a software device.
Build coverage on other platforms is not native-device support.

## What you can use

| Component | Available now | Important boundary |
| --- | --- | --- |
| Rust local host and SDK | Client enrollment, preview, owner approval, submission, status, cancellation and reconciliation | One software-volume endpoint; no native audio action |
| Rust operation storage | Persistent admission and receipts, duplicate protection, restart recovery, schema-1 to schema-2 upgrade | No safe stale-backup restore, production archival or cross-journal device ownership |
| Python device runtime | Software lights, temperature/display examples, existing adapter extensions | Separate API and journal, not a client of the Rust service |
| Python model lab | Data review, training and outcome evaluation | Existing learned candidates have unresolved quality failures |

For a working path, use the [quickstart](getting-started.md). For exact methods and limits,
use the [service reference](reference/execution-service.md).

## Platform coverage

The published [Rust CI run for commit 5dc76a8](https://github.com/takuphilchan/edge-delegate/actions/runs/36575812586)
passed on 29 September 2026. The [Python CI run](https://github.com/takuphilchan/edge-delegate/actions/runs/36575812526)
also passed.

| Environment | Evidence | Not established |
| --- | --- | --- |
| Linux / WSL | Rust software-service tests, adapter process tests and CLI diagnostics | Physical device effects and supported production deployment |
| Windows and macOS | Portable Rust build, lint, tests and recovery example | Native execution transport, native controls or companion app |
| Android and iOS targets | Contracts/core library compilation | Mobile application builds, lifecycle behavior or device tests |

The status-polling race found by CI was reproduced and corrected in `5dc76a8`.
The corrected workspace passed **121 Rust tests** locally, including concurrent reads and
corrupted-record rejection. The service and concurrent-read tests passed ten repeated runs.
These are results for that commit, not a promise that every future revision is green.

## Known model-quality blocker

The real-model numeric development diagnostic passed **26/36** cases. One unsupported compound
request caused a temperature read and display write: a wrong-but-permitted action.
Other failures included unnecessary refusal, incorrect clarification and malformed plans.

The deterministic baseline passed **36/36** on those exposed cases. That does not fix or qualify
the model. Existing trained artifacts have not learned the expanded computer/phone controls.
See the [model evidence archive](history/qualification-status-through-2026-09-28.md) before
selecting a learned candidate.

## What is not ready for deployment

- Native device adapters, companion UI, paired devices and relay transport are not implemented.
- Service lifecycle, events, packaging, retention, restore fencing and independent security
  review remain release work.
- No physical-effect qualification, required soak, independent adopter trial or field pilot
  has been completed.
- Temporary-storage smoke timings do not establish the disk-backed performance gates.
  Historical 188–193 ms P95 results used RAM-backed storage.

A successful operation means the proposed action completed with the recorded evidence. It
does not establish correct model interpretation or independent physical observation.

## Next work

The next service work is durable events, graceful lifecycle and clean-install/recovery tests,
followed by storage hardening and additional public clients. Follow the
[active delivery sequence](roadmap.md#immediate-next-batch), not old implementation-batch lists.

## Earlier evidence

Dated test counts, diagnostics, limitations and failed experiments are retained in
[implementation evidence through 29 September](history/implementation-evidence-through-2026-09-29.md)
and the [earlier model/device evidence archive](history/qualification-status-through-2026-09-28.md).
Moving those notes here does not erase failures, retrain a model or grant release approval.
