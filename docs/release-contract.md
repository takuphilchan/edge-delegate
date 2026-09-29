# Release-one contract

[Roadmap and gates](roadmap.md) | [Current evidence](qualification-status.md)

Owner-approved direction recorded 27 September 2026. This is a development contract,
not a support claim or purchase authorization.

Scope revision, 28 September 2026: the product direction now includes targeted device
control, followed by jobs and bounded automation. The first implementation adds two software
lights with explicit power/brightness control and a public structured SDK. It is experimental,
not an extension of physical support or existing model qualification. See the
[expanded delivery sequence](roadmap.md#expanded-device-control-delivery) and
[implemented control contract](device-control.md). The three-task behavior below remains the
legacy model/artifact contract; it must not silently acquire new meanings.

## Behavior

One configured sensor/display; English text; stateless requests. Return Celsius readings;
display an explicit number; or read and display temperature. Clarify unbound references,
missing/ambiguous values and unsupported numeric formats. Decline unsupported compounds
as a whole. Quoted-only and negative-only requests do nothing (encoded as deny).

Strict explicit-number policy: decimal.v1, inclusive [-1000, 1000], at most two fractional
digits, optional sign/leading decimal point, negative zero normalized. No rounding, arithmetic,
unit conversion, scientific notation, separators or inferred values. This literal policy is
not a complete intent detector. Device authorization is always a separate runtime decision.

## Support matrix

| Component | Development evidence | Supported release requirement |
| --- | --- | --- |
| Gateway | Existing RTX 5060 laptop under WSL | Exact native Ubuntu x86-64 CUDA host selected and tested; not selected yet |
| OS/Python/driver/libraries | Record per experiment | Immutable version inventory, hashes, pinned dependency bundle |
| Model | Existing FunctionGemma compact adapter; classifier baseline | Validation-selected artifact, pinned base revision, strict task pack, frozen qualification |
| Device | Software emulator | Named ESP32-S3 sensor/display assembly, firmware/wiring revision, qualified USB adapter |
| Storage | Home ext4 for durable experiments; /tmp is RAM-backed on this WSL host | Named disk/filesystem, backup/migration/recovery evidence |
| Environment/measurement | No physical measurements | Owner-approved ambient range, wiring/cable limits, reference accuracy and calibration procedure |

Do not substitute the sensor's advertised range for the assembled system's tested operating
envelope. Unfilled support-matrix cells are release blockers, not automatic defaults.

## Threat assumptions and boundaries

Trusted installed plugins, model packages and local operators. Profiles/manifests are data,
never Python imports. Physical USB access is trusted; hostile local administrators and modified
firmware are not sandboxed by this SDK. Checksums detect drift, not malicious signed releases.

Untrusted requests may contain malformed numbers, misleading quotations, prompt injection or
unsupported actions. Validation limits authority but cannot prove intent. Wrong-but-permitted
actions therefore remain a separate release gate. Runtime must fail closed on stale context,
uncertain operations, identity mismatch, overload and missing evidence.

No TCP listener, cloud calls, speech pipeline, MCU inference, multi-tenant hosting, dynamic
uninstalled tools or high-risk actuators in release one. Use readings/status only, never an
operational safety interlock. Journals can contain sensitive arguments/receipts; protect storage
and backups even when ordinary raw-text logging is disabled.

Release review must exercise malicious inputs, artifact loading, dependency provenance, socket/
USB permissions, worker isolation, storage exhaustion and recovery. This document is not a
completed security audit. Independent review and publication approval remain required.
