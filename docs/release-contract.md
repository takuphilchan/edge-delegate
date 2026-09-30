# Cross-platform release contract

[Roadmap](roadmap.md) | [Architecture decision](decisions/cross-platform-redesign.md) | [Current evidence](qualification-status.md)

Approved direction: 29 September 2026. This is the target product contract, not a support claim.

Near-term delivery update, 30 September: Windows and Linux desktop SDK first, then the small
desktop application. The first useful workflow creates a note, sets a selected output's
volume and requests a registered application launch. Other platforms and remote connectivity
remain the longer-term direction. The current Windows development machine is Windows 11 Pro
x64 build 26200; that inventory is not native qualification. Linux native testing is gated on
access to a suitable Ubuntu desktop; WSL software tests do not satisfy it.

## Product

Two equal products: a developer SDK/local execution host and a desktop/mobile assistant.
Rust owns shared contracts, authorization, compilation, durable execution and transport.
Python owns model training/evaluation and experimental model workers. React/TypeScript with
Tauri 2 supplies the shared UI; Kotlin and Swift implement mobile native bridges.

Target Windows, native Ubuntu GNOME/PipeWire, macOS, Android and iOS. CPU is the baseline;
GPU models are optional. Phones control paired hosts and perform supported local actions.
Incoming phone execution is foreground-only. Suspend/disconnect never queues surprise actions.

## Initial behavior

- Workspace: supported status, explicit audio endpoint volume, registered application launch,
  and Edge Delegate-owned notes.
- Companion: discover paired capabilities, preview requests, inspect progress and revoke grants.
- Device reference: preserve software lights and temperature/display demonstrations.
- Named workflow: create session note, set configured audio volume, request registered app launch.
  One destination authority; no distributed transaction or automatic rollback.

Reads require granted scopes. Writes require preview and confirmation by default.
Remembered permissions bind a specific principal, action and target. Pairing alone grants
no execution authority. Unsupported capabilities are not replaced by arbitrary screen clicks.
Application launch may be only a handoff; state readback does not prove action causality.

Notes are immutable and client-owned: create, read by opaque identifier and list summaries.
Titles allow at most 256 UTF-8 bytes; bodies 4096; NUL is rejected. List pages contain at most
20 summaries and never bodies. There is no arbitrary path, edit, delete or implicit sharing.
Note creation and the adapter receipt must commit atomically. The host supplies authenticated
principal context; resource ownership is not inferred from possession of a note ID.

Planned remembered grants default to 24 hours, cap at seven days and 100 executions, and bind
principal, action, exact target registration and parameter constraints. Reservations persist;
restart never renews a grant. Revocation, catalog changes, expiry and clock rollback fence
automatic authorization. Remembered grants are not implemented by the notes adapter.

## Support matrix

| Platform | Intended integration | Evidence still required |
| --- | --- | --- |
| Windows | Per-user host, status/audio/registered apps | Native build, permissions, effects, recovery and install |
| Linux | Native Ubuntu GNOME/PipeWire per-user host | Exact OS/audio stack, disk-backed effects, recovery and install |
| macOS | Native host, Core Audio, registered apps | Native build, signing/permissions, effects, recovery and install |
| Android | Companion, owned notes, supported media/intents | Physical lifecycle, permission and effect tests |
| iOS | Companion, owned notes and App Intents | Physical lifecycle, signing, permissions and supported action tests |

Record exact hardware, OS, toolchain, dependencies, settings and artifacts before qualifying.
WSL is development evidence only. The current machine cannot stand in for the other four
platforms. Native/mobile compile jobs do not establish application/device correctness.
The owner clarified on 29 September that physical test devices are unavailable. Hardware
procurement is not authorized. Software/emulator readiness work continues; native/physical
support remains unqualified until independently observed effects can be tested.

## Trust and connectivity

Local clients use permission-restricted IPC and enrolled client identities. Paired peers use
explicit short-lived invitations, verified identities and revocable scoped grants.
Direct local-network connections and an optional self-hosted relay are in scope.
The relay forwards end-to-end authenticated ciphertext and never queues execution commands.
No central accounts, public managed relay or cloud model interpretation in this release.

Installed adapters are trusted code. Model workers do not receive dispatch authority.
OS sandbox restrictions must be tested; a subprocess alone is not a security sandbox.
The UI never directly accesses journals, adapters or private pairing keys.

## Limits

One active interpretation request, eight waiting requests, one mutation owner per target.
Service frames <=64 KiB; request text <=4 KiB UTF-8; workflows <=8 steps.
Preview/immediate budgets default to 2 seconds and cap at 5 seconds. Registered app launch
caps at 10 seconds and workflows at 30 seconds. Approval lifetime is 60 seconds; approval
waiting is outside execution time. Remote execution budget starts at destination admission.

The current immediate-request v2 subset permits only 1..5000 ms. Longer execution classes
are pending, not silently accepted by the foundation CLI.

No arbitrary shell/scripts, generic input injection, autonomous Accessibility/screenshot agent,
high-risk actuators, payments/passwords, arbitrary file deletion, message sending, voice,
background rules, always-on phone execution or automatic model updates.

## Compatibility and implementation status

Existing Python imports, commands, v1 control requests, Plan IR and model artifacts retain
their legacy behavior. Rust v2 is an additive experimental protocol, not a reinterpretation
of a legacy artifact. No journal is automatically migrated or shared by two executors.

Implemented Rust foundation: strict immediate requests, target bindings, offline preview,
bounded framing, a single-operation coordinator, bound 60-second trusted-operator approvals,
SQLite operation tracking, cancellation fences and software-device recovery. Existing edgectl
preview commands stay non-executing; the new service command can submit authenticated software
requests. A separate edge-delegate-host software-session console requires exact
preview confirmation before dispatch to a supervised software adapter child process.
Linux now has an owner-authenticated saved-context preview service and Rust discovery/preview
client. That original socket has no execution endpoint. A separate software authority offers
scoped handles, durable admission, bounded queueing, cancellation and owner-only confirmation.
Its new authenticated Linux execution service adds persistent scoped enrollment/revocation
and an owner-only confirmation command. Previews, approvals and live scheduling do not
resume on restart. Rust schema-1 journals receive a consistent backup and transactional
schema-2 upgrade. The separate generic in-process authority now records policy revisions and
activity events transactionally and routes real notes and test adapters through scoped handles.
Its separate authenticated v2 listener and public Rust client now use a supervised notes worker.
This Linux/WSL integration has no native control qualification. Consumer consent UI,
planner isolation, migration/restore,
other native transports, native adapters, frontend, Python/TypeScript clients and relay remain
pending. This is not a production permission service or a per-application identity system.

The [archived legacy contract](history/release-contract-through-2026-09-29.md) preserves the
numeric policy and original artifact assumptions; it is not the new support matrix.
