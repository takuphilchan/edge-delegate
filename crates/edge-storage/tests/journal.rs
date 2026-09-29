use edge_contracts::{ControlRequest, parse_json};
use edge_core::{
    Plan, PreviewDecision,
    execution::{Claim, Journal, OperationState},
    preview,
};
use edge_storage::SqliteJournal;
use std::{
    path::Path,
    time::{Duration, Instant},
};
use tempfile::tempdir;

fn deadline() -> Instant {
    Instant::now() + Duration::from_secs(5)
}
fn fixture() -> Plan {
    let request = ControlRequest::parse(include_bytes!(
        "../../../conformance/contracts/preview-v2/request.json"
    ))
    .unwrap();
    let context = parse_json(include_bytes!(
        "../../../conformance/contracts/preview-v2/context.json"
    ))
    .unwrap();
    let PreviewDecision::Proposed { plan, .. } = preview(&request, &context).unwrap().decision
    else {
        panic!()
    };
    plan
}

// A child test process exits without dropping the journal: exercise OS lock release
// and actual committed crash boundaries, rather than only graceful close/reopen.
#[test]
fn crash_child() {
    let Ok(path) = std::env::var("EDGE_TEST_CRASH_JOURNAL") else {
        return;
    };
    let stage = std::env::var("EDGE_TEST_CRASH_STAGE").unwrap();
    let plan = fixture();
    if stage == "locked" {
        assert!(SqliteJournal::open(Path::new(&path), &plan.authority_id).is_err());
        std::process::exit(0);
    }
    let mut journal = SqliteJournal::open(Path::new(&path), &plan.authority_id).unwrap();
    if stage == "before_claim" {
        std::process::exit(0);
    }
    let token = journal.approve("owner", &plan, deadline()).unwrap();
    let Claim::New(operation) = journal
        .claim("owner", &plan, Some(&token), true, deadline())
        .unwrap()
    else {
        panic!()
    };
    if stage == "dispatch_intent" {
        journal
            .dispatch_intent(&operation.operation_id, deadline())
            .unwrap();
    }
    std::process::exit(0);
}

#[test]
fn process_death_never_resumes_an_operation() {
    for (stage, expected) in [
        ("before_claim", None),
        ("after_claim", Some(OperationState::CancelledBeforeDispatch)),
        ("dispatch_intent", Some(OperationState::Unknown)),
    ] {
        let root = tempdir().unwrap();
        let directory = root.path().join("journal");
        let status = std::process::Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "crash_child", "--nocapture"])
            .env("EDGE_TEST_CRASH_JOURNAL", &directory)
            .env("EDGE_TEST_CRASH_STAGE", stage)
            .status()
            .unwrap();
        assert!(status.success());
        let plan = fixture();
        let mut journal = SqliteJournal::open(&directory, &plan.authority_id).unwrap();
        let record = journal
            .lookup("owner", &plan.request_id, deadline())
            .unwrap();
        assert_eq!(record.map(|r| r.state), expected, "{stage}");
    }
}

#[test]
fn a_second_process_cannot_take_journal_ownership() {
    let root = tempdir().unwrap();
    let directory = root.path().join("journal");
    let plan = fixture();
    let _owner = SqliteJournal::open(&directory, &plan.authority_id).unwrap();
    let status = std::process::Command::new(std::env::current_exe().unwrap())
        .args(["--exact", "crash_child", "--nocapture"])
        .env("EDGE_TEST_CRASH_JOURNAL", directory)
        .env("EDGE_TEST_CRASH_STAGE", "locked")
        .status()
        .unwrap();
    assert!(status.success());
}

#[test]
fn unknown_database_version_is_rejected_without_migration() {
    let root = tempdir().unwrap();
    let plan = fixture();
    drop(SqliteJournal::open(&root.path().join("journal"), &plan.authority_id).unwrap());
    let db = rusqlite::Connection::open(root.path().join("journal/journal-v2.sqlite")).unwrap();
    db.pragma_update(None, "user_version", 999).unwrap();
    assert!(SqliteJournal::open(&root.path().join("journal"), &plan.authority_id).is_err());
    assert_eq!(
        db.query_row("PRAGMA user_version", [], |r| r.get::<_, i32>(0))
            .unwrap(),
        999
    );
}

#[test]
fn malformed_records_and_divergent_indexes_fail_closed_on_reopen() {
    for corrupt in [
        "UPDATE operations SET record='{}'",
        "UPDATE operations SET state='succeeded'",
    ] {
        let root = tempdir().unwrap();
        let plan = fixture();
        let mut journal =
            SqliteJournal::open(&root.path().join("journal"), &plan.authority_id).unwrap();
        let token = journal.approve("owner", &plan, deadline()).unwrap();
        journal
            .claim("owner", &plan, Some(&token), true, deadline())
            .unwrap();
        drop(journal);
        let db = rusqlite::Connection::open(root.path().join("journal/journal-v2.sqlite")).unwrap();
        db.execute_batch(corrupt).unwrap();
        assert!(SqliteJournal::open(&root.path().join("journal"), &plan.authority_id).is_err());
    }
}

#[test]
fn sqlite_lock_wait_respects_remaining_budget() {
    let root = tempdir().unwrap();
    let plan = fixture();
    let mut journal =
        SqliteJournal::open(&root.path().join("journal"), &plan.authority_id).unwrap();
    let db = rusqlite::Connection::open(root.path().join("journal/journal-v2.sqlite")).unwrap();
    db.execute_batch("BEGIN EXCLUSIVE").unwrap();
    let started = Instant::now();
    assert!(
        journal
            .approve("owner", &plan, started + Duration::from_millis(30))
            .is_err()
    );
    assert!(started.elapsed() < Duration::from_secs(1));
    db.execute_batch("ROLLBACK").unwrap();
}

#[test]
fn cancellation_and_expiry_leave_immutable_no_dispatch_records() {
    for expired in [false, true] {
        let root = tempdir().unwrap();
        let plan = fixture();
        let mut journal =
            SqliteJournal::open(&root.path().join("journal"), &plan.authority_id).unwrap();
        let token = journal.approve("owner", &plan, deadline()).unwrap();
        let Claim::New(operation) = journal
            .claim("owner", &plan, Some(&token), true, deadline())
            .unwrap()
        else {
            panic!()
        };
        let stopped = journal
            .stop_before_dispatch(&operation.operation_id, expired, deadline())
            .unwrap();
        assert_eq!(
            stopped.state,
            if expired {
                OperationState::ExpiredBeforeDispatch
            } else {
                OperationState::CancelledBeforeDispatch
            }
        );
        assert_eq!(
            journal
                .dispatch_intent(&operation.operation_id, deadline())
                .unwrap()
                .state,
            stopped.state
        );
    }
}

#[cfg(unix)]
#[test]
fn private_permissions_and_symlink_rejection() {
    use std::os::unix::fs::{PermissionsExt, symlink};
    let root = tempdir().unwrap();
    let path = root.path().join("journal");
    let plan = fixture();
    drop(SqliteJournal::open(&path, &plan.authority_id).unwrap());
    assert_eq!(path.metadata().unwrap().permissions().mode() & 0o777, 0o700);
    assert_eq!(
        path.join("journal-v2.sqlite")
            .metadata()
            .unwrap()
            .permissions()
            .mode()
            & 0o777,
        0o600
    );
    symlink(&path, root.path().join("alias")).unwrap();
    assert!(SqliteJournal::open(&root.path().join("alias"), &plan.authority_id).is_err());
    std::fs::set_permissions(
        path.join("journal-v2.sqlite"),
        std::fs::Permissions::from_mode(0o644),
    )
    .unwrap();
    assert!(SqliteJournal::open(&path, &plan.authority_id).is_err());
}
