# Spec Delta

## Purpose

Let developers discover the existing edgectl command syntax and execution boundaries without accessing credentials, connecting to a service or performing an action.

## ADDED Requirements

### Requirement: Command-specific help

The CLI SHALL accept exactly `<command> --help` for `preview`, `capabilities`, `service` and `workspace-service`, print command-specific usage to stdout, leave stderr empty and exit 0 on every supported CLI build platform.

#### Scenario: Each command explains its usage
- **WHEN** a user invokes each of the four supported commands with only `--help`
- **THEN** each invocation succeeds and describes that command's required arguments, their required order and at least one concrete invocation example
- **AND** preview help describes both offline `--context` and local-service `--directory` forms
- **AND** service help explains that `--command` takes a JSON file and `--save-credential` is required only for enrollment

### Requirement: Help is independent of execution

Help SHALL require no running host, credential files, input files or state directory. It SHALL NOT connect to services, read credentials or request files, save credentials, dispatch operations or change persistent state.

#### Scenario: Help on an unconfigured machine
- **WHEN** the four command-help forms run in an empty working directory without a running host
- **THEN** they exit 0 and leave that directory unchanged

#### Scenario: Help on a platform without live transport
- **WHEN** a non-Linux CLI build receives `service --help` or `workspace-service --help`
- **THEN** it prints usage successfully instead of returning the platform-unavailable error
- **AND** it states that actual service calls require Linux/WSL

### Requirement: Truthful command boundaries

Help SHALL distinguish saved-context preview from v1 simulated-volume execution and v2 real-note execution. It SHALL describe platform requirements and owner approval for writes without claiming native device support.

#### Scenario: Preview and discovery boundaries
- **WHEN** a user reads preview or capabilities help
- **THEN** help states that these commands do not authorize or execute actions
- **AND** capabilities is identified as discovery from the saved-context preview service, not permission-filtered v2 execution discovery
- **AND** offline preview is distinguished from Linux/WSL local transport

#### Scenario: Service versions and approval
- **WHEN** a user reads service help
- **THEN** v1 help identifies simulated volume and v2 help identifies real app-owned notes
- **AND** both describe separate owner approval and client submission for writes
- **AND** v2 help states that its credentials and state directory are separate from v1

### Requirement: Existing command compatibility

Adding help SHALL preserve root help, no-argument usage, valid non-help command behavior and existing rejection of malformed commands. Help SHALL NOT cause unknown commands or extra unsupported arguments to succeed.

#### Scenario: Existing entry points still work
- **WHEN** root `--help`, no arguments or the existing offline-preview fixture is invoked
- **THEN** usage invocations exit 0 and describe the existing commands
- **AND** the fixture remains non-executing with the same structured result semantics

#### Scenario: Invalid help-like input
- **WHEN** the user invokes `unknown --help`, `preview --help extra`, `service --help extra`, `workspace-service --help extra`, `capabilities --help extra`, `execute` or `preview --execute`
- **THEN** the CLI exits 2, prints a diagnostic to stderr and leaves stdout empty
