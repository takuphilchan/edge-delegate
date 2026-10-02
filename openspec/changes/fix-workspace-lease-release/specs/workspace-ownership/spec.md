# Spec Delta

## Purpose

Keep the Linux notes store exclusively owned while in use, and allow safe
reopening after teardown or failed initialization without losing execution evidence.

## ADDED Requirements

### Requirement: Exclusive live ownership

The notes store SHALL admit at most one live owner of a dedicated workspace.
A competing open SHALL fail promptly without taking over or releasing the
existing owner's lease, including after a competing initialization attempt fails.

#### Scenario: A second owner attempts access
- **WHEN** a workspace is open and another caller in the same or a different process opens the same store
- **THEN** the second caller receives an ownership error without receiving a usable store
- **AND** the first owner's notes and receipts remain accessible to that owner

#### Scenario: A rejected contender cleans up
- **WHEN** a competing open fails and its temporary resources are destroyed
- **THEN** the live owner retains exclusive access
- **AND** a subsequent third contender is still rejected

### Requirement: Deterministic normal release

After successful owner teardown, the store SHALL be reopenable without a retry,
sleep, journal deletion, or waiting for unrelated process activity. An incidental
duplicate of the released owner's lock handle SHALL NOT extend logical ownership.
Teardown SHALL close database resources before releasing ownership.

#### Scenario: Reopen while an incidental handle remains
- **WHEN** an owner is dropped while a non-operating duplicate of its lock handle remains open
- **THEN** a new owner can open the same store immediately
- **AND** the new owner continues to exclude other owners

#### Scenario: Unrelated child processes run concurrently
- **WHEN** independent child-process tests run while a notes owner is dropped and reopened
- **THEN** reopening succeeds without changing the parallel test configuration
- **AND** the test does not bypass the ownership check or automatically retry opening

### Requirement: Cleanup after failed initialization

If initialization fails after acquiring ownership, the store SHALL release only
that acquired lease after closing its database resources. It SHALL preserve the
original failure and SHALL NOT delete, reset, adopt, or repair persistent state
as part of cleanup.

#### Scenario: Deployment identity does not match
- **WHEN** an otherwise valid store is opened with a different authority or endpoint and initialization fails
- **THEN** no usable store is returned and the original deployment remains unchanged
- **AND** reopening with the original identity succeeds without clearing a lock file

#### Scenario: Storage validation fails
- **WHEN** initialization rejects an incompatible schema or substituted storage path
- **THEN** the original rejection remains observable and the rejected storage remains intact
- **AND** no acquired lease from the failed attempt remains as a phantom owner

### Requirement: Durable recovery without replay

Ownership cleanup SHALL preserve notes, receipt identity, and request deduplication.
After a terminated owner has exited, a new owner SHALL be able to inspect and
reconcile the same operation without invoking an uncertain write again.

#### Scenario: Normal reopen preserves the original result
- **WHEN** a note creation commits, the owner closes, and the store reopens
- **THEN** receipt reconciliation and same-identity lookup return the original note
- **AND** the number of created notes does not increase

#### Scenario: Process death before or after commit
- **WHEN** an owner process exits before committing a note or after committing its receipt
- **THEN** reopening preserves the existing rollback or receipt-recovery behavior respectively
- **AND** an unknown outcome is not converted into a successful result without evidence

### Requirement: Preserve storage security and compatibility

The fix SHALL preserve private-file and directory checks, symlink and deployment
binding checks, existing schemas, credentials, public operations, and the Linux/WSL
support boundary. It SHALL NOT broaden permissions or make shared ownership valid.

#### Scenario: Unsafe files remain rejected
- **WHEN** a caller supplies a symlink, broadly accessible path, or wrong deployment identity
- **THEN** opening remains rejected without replacing the original files

#### Scenario: Existing valid state remains usable
- **WHEN** the updated adapter opens valid existing notes and receipts
- **THEN** it reads them without a schema migration or changed note identifiers
- **AND** client authorization and exact write approval remain the host's responsibility
