#![cfg(target_os = "linux")]
use edge_contracts::{admission::AdmissionState, operation::OperationState};
use edge_core::cancellation::CancelDisposition;
use edge_host::authority::{
    Grant, MAX_OFFERS, MAX_WAITING, Permission, ScopedClient, SoftwareAuthority, TicketStatus,
};
use edge_protocol::adapter::SimulatorFault;
use rusqlite::Connection;
use std::{
    collections::BTreeSet,
    path::Path,
    thread,
    time::{Duration, Instant},
};

fn grant(principal: &str) -> Grant {
    Grant {
        principal: principal.into(),
        actions: BTreeSet::from(["audio.volume.set".into()]),
        endpoints: BTreeSet::from(["output".into()]),
        permissions: BTreeSet::from([
            Permission::Preview,
            Permission::Execute,
            Permission::Status,
            Permission::Cancel,
            Permission::Reconcile,
        ]),
    }
}
fn start(root: &Path, fault: SimulatorFault) -> SoftwareAuthority {
    SoftwareAuthority::start(
        root,
        Path::new(env!("CARGO_BIN_EXE_edge-delegate-simulator-worker")),
        fault,
    )
    .unwrap()
}
fn approved(owner: &SoftwareAuthority, client: &ScopedClient, ms: u32) -> String {
    let offer = client.preview_volume(40, ms).unwrap();
    owner
        .approve(client, &offer.request_id, &offer.plan_sha256)
        .unwrap();
    offer.request_id
}
fn wait(client: &ScopedClient, id: &str) -> TicketStatus {
    let limit = Instant::now() + Duration::from_secs(4);
    loop {
        let status = client.status(id).unwrap();
        if !matches!(status, TicketStatus::Queued | TicketStatus::Running) {
            return status;
        }
        assert!(Instant::now() < limit, "ticket did not finish");
        thread::sleep(Duration::from_millis(2));
    }
}
fn writes(root: &Path) -> i64 {
    Connection::open(root.join("device.sqlite"))
        .unwrap()
        .query_row("SELECT writes FROM state", [], |r| r.get(0))
        .unwrap()
}
fn await_running(client: &ScopedClient, id: &str) {
    let limit = Instant::now() + Duration::from_secs(2);
    while !matches!(client.status(id).unwrap(), TicketStatus::Running) {
        assert!(Instant::now() < limit);
        thread::sleep(Duration::from_millis(1));
    }
}

#[test]
fn owner_confirmation_and_client_scopes_are_not_interchangeable() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("authority");
    let owner = start(&root, SimulatorFault::None);
    let alice = owner.enroll(grant("alice")).unwrap();
    let bob = owner.enroll(grant("bob")).unwrap();
    let offer = alice.preview_volume(40, 2000).unwrap();
    assert!(alice.submit(&offer.request_id).is_err());
    assert_eq!(writes(&root), 0);
    assert!(
        owner
            .approve(&bob, &offer.request_id, &offer.plan_sha256)
            .is_err()
    );
    assert!(
        owner
            .approve(&alice, &offer.request_id, &"0".repeat(64))
            .is_err()
    );
    owner
        .approve(&alice, &offer.request_id, &offer.plan_sha256)
        .unwrap();
    alice.submit(&offer.request_id).unwrap();
    assert!(
        matches!(wait(&alice,&offer.request_id), TicketStatus::Completed { operation } if operation.state == OperationState::Succeeded && operation.principal == "alice")
    );
    assert!(bob.status(&offer.request_id).is_err());
    assert!(bob.cancel(&offer.request_id).is_err());
    assert!(bob.submit(&offer.request_id).is_err());
    assert_eq!(writes(&root), 1);
    assert!(owner.enroll(grant("alice")).is_err());
}

#[test]
fn denied_permissions_targets_and_actions_do_not_create_operations() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("authority");
    let owner = start(&root, SimulatorFault::None);
    let mut limited = grant("observer");
    limited.permissions = BTreeSet::from([Permission::Preview, Permission::Status]);
    let client = owner.enroll(limited).unwrap();
    let offer = client.preview_volume(40, 2000).unwrap();
    assert!(
        owner
            .approve(&client, &offer.request_id, &offer.plan_sha256)
            .is_err()
    );
    assert!(client.submit(&offer.request_id).is_err());
    for (name, action, endpoint) in [
        ("wrong-action", "audio.volume.get", "output"),
        ("wrong-target", "audio.volume.set", "other"),
    ] {
        let mut g = grant(name);
        g.actions = BTreeSet::from([action.into()]);
        g.endpoints = BTreeSet::from([endpoint.into()]);
        assert!(owner.enroll(g).unwrap().preview_volume(40, 2000).is_err());
    }
    assert_eq!(writes(&root), 0);
    assert!(
        owner
            .inspect("observer", &offer.request_id)
            .unwrap()
            .is_none()
    );
}

#[test]
fn concurrent_duplicate_submissions_have_one_ticket_and_one_effect() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("authority");
    let owner = start(&root, SimulatorFault::None);
    let client = owner.enroll(grant("alice")).unwrap();
    let id = approved(&owner, &client, 2000);
    let threads: Vec<_> = (0..12)
        .map(|_| {
            let c = client.clone();
            let id = id.clone();
            thread::spawn(move || c.submit(&id).unwrap())
        })
        .collect();
    for thread in threads {
        thread.join().unwrap();
    }
    assert!(
        matches!(wait(&client,&id), TicketStatus::Completed { operation } if operation.state == OperationState::Succeeded)
    );
    assert_eq!(writes(&root), 1);
}

#[test]
fn queue_is_bounded_and_queued_cancellation_prevents_dispatch() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("authority");
    let owner = start(&root, SimulatorFault::HangBeforeEffect);
    let client = owner.enroll(grant("alice")).unwrap();
    let ids: Vec<_> = (0..MAX_WAITING + 2)
        .map(|_| approved(&owner, &client, 2000))
        .collect();
    client.submit(&ids[0]).unwrap();
    await_running(&client, &ids[0]);
    for id in &ids[1..=MAX_WAITING] {
        client.submit(id).unwrap();
        assert_eq!(
            owner.inspect_admission("alice", id).unwrap().unwrap().state,
            AdmissionState::Accepted
        );
    }
    assert_eq!(
        client.submit(&ids[MAX_WAITING + 1]).unwrap_err(),
        "authority_overloaded"
    );
    assert!(client.status(&ids[MAX_WAITING + 1]).is_err());
    for id in &ids[1..=MAX_WAITING] {
        assert_eq!(
            client.cancel(id).unwrap(),
            CancelDisposition::PreventedDispatch
        );
    }
    client.cancel(&ids[0]).unwrap();
    wait(&client, &ids[0]);
    for id in &ids[1..=MAX_WAITING] {
        assert!(matches!(
            wait(&client, id),
            TicketStatus::CancelledBeforeDispatch
        ));
    }
    assert_eq!(writes(&root), 0);
}

#[test]
fn queue_wait_uses_the_original_execution_deadline() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("authority");
    let owner = start(&root, SimulatorFault::HangBeforeEffect);
    let client = owner.enroll(grant("alice")).unwrap();
    let first = approved(&owner, &client, 2000);
    let expiring = approved(&owner, &client, 150);
    client.submit(&first).unwrap();
    await_running(&client, &first);
    client.submit(&expiring).unwrap();
    assert!(matches!(
        wait(&client, &expiring),
        TicketStatus::ExpiredBeforeDispatch
    ));
    assert!(owner.inspect("alice", &expiring).unwrap().is_none());
    assert_eq!(writes(&root), 0);
}

#[test]
fn cancellation_interrupts_active_io_but_cannot_undo_a_completed_effect() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("authority");
    let owner = start(&root, SimulatorFault::HangAfterEffect);
    let client = owner.enroll(grant("alice")).unwrap();
    let id = approved(&owner, &client, 2000);
    client.submit(&id).unwrap();
    let limit = Instant::now() + Duration::from_secs(2);
    while writes(&root) != 1 {
        assert!(Instant::now() < limit);
        thread::sleep(Duration::from_millis(1));
    }
    let started = Instant::now();
    assert_eq!(
        client.cancel(&id).unwrap(),
        CancelDisposition::PossiblyDispatched
    );
    assert!(
        matches!(wait(&client,&id),TicketStatus::Completed { operation } if operation.state==OperationState::Unknown)
    );
    assert!(started.elapsed() < Duration::from_millis(750));
    assert_eq!(writes(&root), 1);
    owner.restart_adapter().unwrap();
    assert_eq!(
        client.reconcile(&id).unwrap().state,
        OperationState::Succeeded
    );
    assert_eq!(writes(&root), 1);
}

#[test]
fn revocation_fences_waiting_work_and_rejects_future_use() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("authority");
    let owner = start(&root, SimulatorFault::HangBeforeEffect);
    let alice = owner.enroll(grant("alice")).unwrap();
    let bob = owner.enroll(grant("bob")).unwrap();
    let active = approved(&owner, &alice, 2000);
    let queued = approved(&owner, &bob, 2000);
    alice.submit(&active).unwrap();
    await_running(&alice, &active);
    bob.submit(&queued).unwrap();
    let cancelled = owner.revoke(&bob).unwrap();
    assert_eq!(cancelled[0].1, CancelDisposition::PreventedDispatch);
    assert!(bob.submit(&queued).is_err());
    assert!(bob.preview_volume(40, 2000).is_err());
    alice.cancel(&active).unwrap();
    wait(&alice, &active);
    let limit = Instant::now() + Duration::from_secs(2);
    while !matches!(
        owner.ticket_status(&bob, &queued).unwrap(),
        TicketStatus::CancelledBeforeDispatch
    ) {
        assert!(Instant::now() < limit);
        thread::sleep(Duration::from_millis(2));
    }
    assert_eq!(writes(&root), 0);
}

#[test]
fn retention_is_bounded_without_evicting_request_identity() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("authority");
    let owner = start(&root, SimulatorFault::None);
    let client = owner.enroll(grant("alice")).unwrap();
    let first = client.preview_volume(40, 2000).unwrap();
    for _ in 1..MAX_OFFERS {
        client.preview_volume(40, 2000).unwrap();
    }
    assert_eq!(
        client.preview_volume(40, 2000).unwrap_err(),
        "offer_capacity_reached"
    );
    owner
        .approve(&client, &first.request_id, &first.plan_sha256)
        .unwrap();
    client.submit(&first.request_id).unwrap();
    wait(&client, &first.request_id);
    assert_eq!(writes(&root), 1);
}

#[test]
fn shutdown_never_resumes_volatile_queue_or_approvals_after_restart() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("authority");
    let owner = start(&root, SimulatorFault::HangAfterEffect);
    let client = owner.enroll(grant("alice")).unwrap();
    let first = approved(&owner, &client, 2000);
    let queued = approved(&owner, &client, 2000);
    client.submit(&first).unwrap();
    let limit = Instant::now() + Duration::from_secs(2);
    while writes(&root) != 1 {
        assert!(Instant::now() < limit);
        thread::sleep(Duration::from_millis(1));
    }
    client.submit(&queued).unwrap();
    drop(owner);
    assert!(client.submit(&queued).is_err());
    let owner = start(&root, SimulatorFault::None);
    let new_client = owner.enroll(grant("alice")).unwrap();
    assert!(new_client.submit(&queued).is_err());
    assert_eq!(
        owner.inspect("alice", &first).unwrap().unwrap().state,
        OperationState::Unknown
    );
    assert!(owner.inspect("alice", &queued).unwrap().is_none());
    assert_eq!(
        owner
            .inspect_admission("alice", &queued)
            .unwrap()
            .unwrap()
            .state,
        AdmissionState::CancelledBeforeDispatch
    );
    assert!(owner.reconcile_record("other", &first).is_err());
    assert_eq!(
        owner.reconcile_record("alice", &first).unwrap().state,
        OperationState::Succeeded
    );
    assert_eq!(
        owner.inspect("alice", &first).unwrap().unwrap().state,
        OperationState::Succeeded
    );
    assert_eq!(writes(&root), 1);
}

#[test]
fn failed_admission_never_enters_execution_queue() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("authority");
    let owner = start(&root, SimulatorFault::None);
    let client = owner.enroll(grant("alice")).unwrap();
    let id = approved(&owner, &client, 2000);
    let db = Connection::open(root.join("journal/journal-v2.sqlite")).unwrap();
    db.execute_batch("CREATE TRIGGER fail_admission BEFORE INSERT ON admissions BEGIN SELECT RAISE(ABORT, 'injected_failure'); END;").unwrap();
    assert!(client.submit(&id).is_err());
    assert!(matches!(
        client.status(&id).unwrap(),
        TicketStatus::NeedsInspection { .. }
    ));
    assert!(owner.inspect_admission("alice", &id).unwrap().is_none());
    assert!(owner.inspect("alice", &id).unwrap().is_none());
    assert_eq!(writes(&root), 0);
    // An uncertain submission error cannot turn a retry into an unannounced new attempt.
    db.execute_batch("DROP TRIGGER fail_admission;").unwrap();
    assert!(matches!(
        client.submit(&id).unwrap(),
        TicketStatus::NeedsInspection { .. }
    ));
    assert_eq!(writes(&root), 0);
}

#[test]
fn durable_authority_crash_child() {
    let Ok(directory) = std::env::var("EDGE_AUTHORITY_CRASH_PATH") else {
        return;
    };
    let root = Path::new(&directory);
    let owner = start(root, SimulatorFault::HangAfterEffect);
    let client = owner.enroll(grant("alice")).unwrap();
    let active = approved(&owner, &client, 5000);
    let queued = approved(&owner, &client, 5000);
    client.submit(&active).unwrap();
    let until = Instant::now() + Duration::from_secs(2);
    while writes(root) != 1 {
        assert!(Instant::now() < until);
        thread::sleep(Duration::from_millis(1));
    }
    client.submit(&queued).unwrap();
    assert_eq!(
        owner
            .inspect_admission("alice", &queued)
            .unwrap()
            .unwrap()
            .state,
        AdmissionState::Accepted
    );
    std::fs::write(
        root.join("fixture-ids.json"),
        serde_json::to_vec(&[active, queued]).unwrap(),
    )
    .unwrap();
    std::process::exit(0); // no queue draining, cancellation or normal authority destruction
}

#[test]
fn abrupt_owner_death_retains_queued_identity_and_does_not_resume() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("authority");
    let status = std::process::Command::new(std::env::current_exe().unwrap())
        .args(["--exact", "durable_authority_crash_child"])
        .env("EDGE_AUTHORITY_CRASH_PATH", &root)
        .status()
        .unwrap();
    assert!(status.success());
    let ids: Vec<String> =
        serde_json::from_slice(&std::fs::read(root.join("fixture-ids.json")).unwrap()).unwrap();
    let owner = start(&root, SimulatorFault::None);
    for id in &ids {
        assert_eq!(
            owner.inspect_admission("alice", id).unwrap().unwrap().state,
            AdmissionState::Interrupted
        );
    }
    assert!(owner.inspect("alice", &ids[1]).unwrap().is_none());
    assert_eq!(
        owner.inspect("alice", &ids[0]).unwrap().unwrap().state,
        OperationState::Unknown
    );
    assert_eq!(
        owner.reconcile_record("alice", &ids[0]).unwrap().state,
        OperationState::Succeeded
    );
    assert!(
        owner
            .enroll(grant("alice"))
            .unwrap()
            .submit(&ids[1])
            .is_err()
    );
    assert_eq!(writes(&root), 1);
}
