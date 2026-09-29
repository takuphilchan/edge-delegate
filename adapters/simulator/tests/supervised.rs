#![cfg(target_os = "linux")]
use edge_contracts::operation::OperationState;
use edge_host::session::SoftwareSession;
use edge_protocol::adapter::SimulatorFault;
use rusqlite::Connection;
use std::{
    fs,
    path::Path,
    process::Command,
    thread,
    time::{Duration, Instant},
};

fn worker() -> &'static Path {
    Path::new(env!("CARGO_BIN_EXE_edge-delegate-simulator-worker"))
}
fn open(path: &Path, fault: SimulatorFault) -> SoftwareSession {
    SoftwareSession::open(path, worker(), fault).unwrap()
}
fn state(path: &Path) -> (i64, i64) {
    Connection::open(path.join("device.sqlite"))
        .unwrap()
        .query_row("SELECT volume,writes FROM state", [], |row| {
            Ok((row.get(0)?, row.get(1)?))
        })
        .unwrap()
}
fn approved(session: &mut SoftwareSession) -> String {
    let preview = session.preview_volume(40).unwrap();
    session.approve(&preview.plan_sha256).unwrap();
    preview.plan.request_id
}

#[test]
fn explicit_preview_approval_execute_and_duplicate_use_one_software_effect() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("session");
    let mut session = open(&root, SimulatorFault::None);
    assert!(session.execute().is_err());
    let preview = session.preview_volume(40).unwrap();
    assert!(!preview.execution_attempted);
    assert_eq!(state(&root), (20, 0));
    assert!(session.approve(&"0".repeat(64)).is_err());
    assert!(session.execute().is_err());
    session.approve(&preview.plan_sha256).unwrap();
    assert_eq!(state(&root), (20, 0));
    let first = session.execute().unwrap();
    assert_eq!(first.state, OperationState::Succeeded);
    let replay = session.execute().unwrap();
    assert_eq!(first.operation_id, replay.operation_id);
    assert_eq!(state(&root), (40, 1));
    assert_eq!(
        session
            .status(&preview.plan.request_id)
            .unwrap()
            .unwrap()
            .state,
        OperationState::Succeeded
    );
    assert_eq!(
        session
            .cancel(&preview.plan.request_id)
            .unwrap()
            .unwrap()
            .state,
        OperationState::Succeeded
    );
}

#[test]
fn cancelling_preview_and_superseding_approval_never_dispatch() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("session");
    let mut session = open(&root, SimulatorFault::None);
    let first = session.preview_volume(40).unwrap();
    session.approve(&first.plan_sha256).unwrap();
    let next = session.preview_volume(50).unwrap();
    assert!(session.approve(&first.plan_sha256).is_err());
    assert!(session.execute().is_err());
    session.approve(&next.plan_sha256).unwrap();
    assert!(session.cancel(&next.plan.request_id).unwrap().is_none());
    assert!(session.execute().is_err());
    assert!(session.status(&next.plan.request_id).unwrap().is_none());
    assert_eq!(state(&root), (20, 0));
    assert!(session.cancel("unknown").is_err());
}

#[test]
fn state_change_invalidates_confirmation_and_execution() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("session");
    let mut session = open(&root, SimulatorFault::None);
    let p = session.preview_volume(40).unwrap();
    let db = Connection::open(root.join("device.sqlite")).unwrap();
    db.execute("UPDATE state SET generation=generation+1", [])
        .unwrap();
    assert!(session.approve(&p.plan_sha256).is_err());
    let p = session.preview_volume(40).unwrap();
    session.approve(&p.plan_sha256).unwrap();
    db.execute("UPDATE state SET generation=generation+1", [])
        .unwrap();
    assert!(session.execute().is_err());
    assert_eq!(state(&root), (20, 0));
}

#[test]
fn lost_ack_is_unknown_then_reconciled_without_reinvocation() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("session");
    let mut session = open(&root, SimulatorFault::LostAcknowledgement);
    let id = approved(&mut session);
    assert_eq!(session.execute().unwrap().state, OperationState::Unknown);
    assert_eq!(session.execute().unwrap().state, OperationState::Unknown);
    assert_eq!(state(&root), (40, 1));
    assert_eq!(
        session.reconcile(&id).unwrap().state,
        OperationState::Succeeded
    );
    assert_eq!(state(&root), (40, 1));
}

#[test]
fn hung_adapter_is_terminated_and_missing_receipt_stays_unknown() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("session");
    let mut session = open(&root, SimulatorFault::HangBeforeEffect);
    let id = approved(&mut session);
    let start = Instant::now();
    assert_eq!(session.execute().unwrap().state, OperationState::Unknown);
    assert!(start.elapsed() < Duration::from_millis(2500));
    assert!(!session.worker_healthy());
    assert_eq!(state(&root), (20, 0));
    assert_eq!(session.execute().unwrap().state, OperationState::Unknown);
    assert!(session.reconcile(&id).is_err());
    session.restart_adapter().unwrap();
    assert_eq!(
        session.reconcile(&id).unwrap().state,
        OperationState::Unknown
    );
    approved(&mut session);
    assert!(session.execute().is_err()); // endpoint remains fenced
    assert_eq!(state(&root), (20, 0));
}

#[test]
fn late_crashed_and_malformed_acknowledgements_keep_durable_effect() {
    for fault in [
        SimulatorFault::HangAfterEffect,
        SimulatorFault::CrashAfterEffect,
        SimulatorFault::MalformedResponse,
    ] {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path().join("session");
        let mut session = open(&root, fault);
        let id = approved(&mut session);
        assert_eq!(session.execute().unwrap().state, OperationState::Unknown);
        assert!(!session.worker_healthy());
        assert_eq!(state(&root), (40, 1));
        session.restart_adapter().unwrap();
        assert_eq!(
            session.reconcile(&id).unwrap().state,
            OperationState::Succeeded
        );
        assert_eq!(state(&root), (40, 1));
    }
}

#[test]
fn reopening_session_preserves_receipts_but_never_restores_an_approval() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("session");
    let mut session = open(&root, SimulatorFault::LostAcknowledgement);
    let id = approved(&mut session);
    session.execute().unwrap();
    drop(session);
    let mut session = open(&root, SimulatorFault::None);
    assert!(session.execute().is_err());
    assert_eq!(state(&root), (40, 1));
    assert_eq!(
        session.status(&id).unwrap().unwrap().state,
        OperationState::Unknown
    );
    assert_eq!(
        session.reconcile(&id).unwrap().state,
        OperationState::Succeeded
    );
    assert_eq!(state(&root), (40, 1));
}

#[test]
fn second_owner_and_invalid_values_fail_without_effects() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("session");
    let mut session = open(&root, SimulatorFault::None);
    assert!(SoftwareSession::open(&root, worker(), SimulatorFault::None).is_err());
    assert!(session.preview_volume(-1).is_err());
    assert!(session.preview_volume(101).is_err());
    assert_eq!(state(&root), (20, 0));
}

#[test]
fn owner_crash_helper() {
    let Some(directory) = std::env::var_os("EDGE_SUPERVISION_CRASH_DIRECTORY") else {
        return;
    };
    let root = Path::new(&directory);
    let mut session = open(root, SimulatorFault::HangAfterEffect);
    let id = approved(&mut session);
    fs::write(root.join("request-id"), id).unwrap();
    let _ = session.execute();
    panic!("parent should have killed this test process during dispatch");
}

#[test]
fn actual_owner_death_fences_dispatch_and_terminates_adapter() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("session");
    let mut owner = Command::new(std::env::current_exe().unwrap())
        .arg("--exact")
        .arg("owner_crash_helper")
        .env("EDGE_SUPERVISION_CRASH_DIRECTORY", &root)
        .spawn()
        .unwrap();
    let limit = Instant::now() + Duration::from_secs(5);
    let mut effected = false;
    while Instant::now() < limit {
        if root.join("request-id").exists() && state(&root).1 == 1 {
            effected = true;
            break;
        }
        thread::sleep(Duration::from_millis(5));
    }
    let _ = owner.kill();
    let _ = owner.wait();
    assert!(effected, "helper never reached software effect");
    let id = fs::read_to_string(root.join("request-id")).unwrap();
    // Parent-death signal may still be in flight; retry startup, never an operation.
    let limit = Instant::now() + Duration::from_secs(2);
    let mut session = loop {
        match SoftwareSession::open(&root, worker(), SimulatorFault::None) {
            Ok(session) => break session,
            Err(error) => {
                assert!(
                    Instant::now() < limit,
                    "adapter ownership not released: {error}"
                );
                thread::sleep(Duration::from_millis(10));
            }
        }
    };
    assert_eq!(
        session.status(&id).unwrap().unwrap().state,
        OperationState::Unknown
    );
    assert_eq!(
        session.reconcile(&id).unwrap().state,
        OperationState::Succeeded
    );
    assert_eq!(state(&root), (40, 1));
}
