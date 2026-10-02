# Project status

[Documentation](README.md) · [Roadmap](roadmap.md) · [Release requirements](release-contract.md)

**Edge Delegate is experimental developer software. No production configuration is qualified.**
The usable Rust paths are Linux/WSL services for a software device and real app-owned notes.
Build coverage on other platforms is not native-device support.

## What you can use

| Component | Available now | Important boundary |
| --- | --- | --- |
| Rust local host and SDK | Client enrollment, preview, owner approval, submission, status, cancellation and reconciliation | One software-volume endpoint; no native audio action |
| Rust operation storage | Persistent admission and receipts, duplicate protection, restart recovery, schema-1 to schema-2 upgrade | No safe stale-backup restore, production archival or cross-journal device ownership |
| Python device runtime | Software lights, temperature/display examples, existing adapter extensions | Separate API and journal, not a client of the Rust service |
| Python model lab | Data review, training and outcome evaluation | Existing learned candidates have unresolved quality failures |
| Generic Rust v2 service | Filtered discovery, enrollment, exact owner approval, execution, status, cancellation, reconciliation and activity events through the public Rust client | Linux/WSL only; no Windows transport, Python client or installed release package |
| Rust notes adapter | Immutable create/read/list, principal ownership, atomic creation/receipt and duplicate checks, now in a supervised worker | Real app-owned storage, not a physical-device test; no Windows ACL implementation |

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

The next service work is secure Windows transport/storage, Python client parity and clean-install
packaging. Native controls and the UI
follow that integration, not direct exposure of the trusted adapter. Follow the
[active delivery sequence](roadmap.md#immediate-next-batch), not old implementation-batch lists.

Contributors can exercise the notes adapter in Linux/WSL with
`cargo run --locked -p edge-workspace --example notes -- NEW_PRIVATE_DIRECTORY`.
The parent directory must exist; use a dedicated directory, not an existing service journal.
It prints a plan and requires `create` before storing a note, then reads the note back.
This is a direct trusted-owner adapter example, **not authenticated SDK/service approval**.
Each run creates a new request; preserve storage and the printed operation ID after an error.
`cargo test --locked -p edge-workspace` checks receipt recovery and non-actions without hardware.
`bash scripts/test-workspace.sh` also checks the example's decline and creation paths automatically.

The generic authority is also executable as a contributor example:
`cargo run --locked -p edge-workspace --example notes_authority -- NEW_PRIVATE_DIRECTORY`.
It previews a note, requires the owner's `create` confirmation, executes with a scoped
client handle, reads the note and prints its durable activity history. The script above
tests its approval and decline paths too. This is trusted in-process embedding, not IPC
authentication or the future public SDK onboarding experience.

This authority supports at most nine concurrent executions (one adapter owner, eight waiting),
128 live offers, 64 principals, 10,000 retained request identities and 100,000 metadata events.
Offers expire after 60 seconds; consent never extends that preview lifetime. Permissions are
rechecked at dispatch under the same gate as revocation. Revoked handles may inspect their
own historical records but cannot start new actions. Restart expires offers, cancels queued
work and preserves dispatched uncertainty; it never resumes execution automatically.
Unknown mutations fence subsequent writes to the endpoint until reconciled.

These count limits are not a production disk quota or retention policy. Direct embedding
still relies on trusted adapters honoring deadlines. The v2 host uses a supervised notes worker:
transport expiry or corruption retires the worker; reconciliation can restart it and query
receipts without invoking the uncertain action again. Terminating a process does not prove
that an action had no effect. This is supervision, not a security sandbox.
Coordinated backups and reserved recovery capacity remain open.

Foundation verification on 30 September 2026: **141 Rust tests passed** (including process-exit
helpers), **604 Python tests passed, one hardware test deselected**, and Clippy, Ruff and
formatting passed. The existing execution-service/tutorial checks and the notes example
checks passed. These are Linux/WSL software results, not a v2 service or native Windows claim.

Subsequent authority verification on 30 September 2026: **152 Rust tests passed**,
**604 Python tests passed, one hardware test deselected**. Clippy, Ruff, formatting,
the existing authenticated execution-service diagnostics and both notes examples passed.
The added coverage includes transactional event failure, immutable request identity,
restart fencing, policy changes, lost acknowledgements, concurrent duplicates, queued
cancellation/expiry/revocation, overload and adapter reconciliation panic. These results
did not establish native-adapter or v2-service behavior; that batch preceded service integration.

Authenticated v2 integration verification on 30 September 2026: **161 Rust tests passed**,
**604 Python tests passed, one hardware test deselected**. Clippy, Ruff, formatting, the new
`scripts/test-workspace-service.sh` diagnostic and the legacy execution-service/tutorial
diagnostics passed. The v2 tests exercise real notes through the public client and worker,
separate owner confirmation, ownership checks, durable revocation, dropped responses,
restart, worker hangs/crashes, malformed replies and lost acknowledgements. This is Linux/WSL
development evidence, not native Windows coverage, performance qualification or a production release.

## Notes ownership regression - 2 October 2026

A deterministic duplicate-handle test reproduced `workspace_already_owned` after
normal owner teardown. The adapter now explicitly releases only its acquired lease
in the acquiring process, after closing SQLite. It does not relax live ownership,
change the storage schema, or replay an uncertain write.

Focused Linux/WSL verification: **three private lease tests passed**, and the
**12-test notes suite passed ten consecutive default-parallel runs**. Coverage
includes actual competing processes, rejected-contender cleanup, initialization
failure, original receipt preservation, permissions and incompatible storage,
and process death before/after commit. An initial integration-test compilation
error in receipt comparison was corrected before these runs. The duplicate-handle
mechanism was reproduced; the exact process interleaving of the earlier flaky
failure was not traced. These are regression checks, not native-device or
production qualification.

The full Rust workspace check is **not green**: the v2 service restart test
`authenticated_notes_approval_ownership_events_and_restart` independently failed
with `service_already_owned`. That service lease is separate from the repaired
notes lease and remains a blocker; the focused results above do not resolve it.

## Earlier evidence

Dated test counts, diagnostics, limitations and failed experiments are retained in
[implementation evidence through 29 September](history/implementation-evidence-through-2026-09-29.md)
and the [earlier model/device evidence archive](history/qualification-status-through-2026-09-28.md).
Moving those notes here does not erase failures, retrain a model or grant release approval.
