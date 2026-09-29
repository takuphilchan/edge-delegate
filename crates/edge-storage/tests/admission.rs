use edge_contracts::{ControlRequest, admission::AdmissionState, parse_json};
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

fn deadline() -> Instant {
    Instant::now() + Duration::from_secs(2)
}
fn fixture() -> (ControlRequest, Plan) {
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
    (request, plan)
}

#[test]
fn concurrent_status_reads_do_not_misclassify_commits_as_corruption() {
    use edge_contracts::{Evidence, Parameter, operation::Receipt};
    use std::{sync::mpsc, thread};

    let root = tempfile::tempdir().unwrap();
    let (_, mut plan) = fixture();
    let mut journal =
        SqliteJournal::open(&root.path().join("journal"), &plan.authority_id).unwrap();
    let reader = journal.admission_writer().unwrap();
    let (send, receive) = mpsc::sync_channel::<String>(0);
    let (done, completed) = mpsc::sync_channel(0);
    let poller = thread::spawn(move || {
        for id in receive {
            let until = Instant::now() + Duration::from_secs(5);
            loop {
                let op = reader
                    .inspect_operation("alice", &id, until)
                    .expect("a committed transition is not index corruption")
                    .unwrap();
                assert_eq!(op.request_id, id);
                if op.state == OperationState::Succeeded {
                    done.send(()).unwrap();
                    break;
                }
                assert!(Instant::now() < until);
                thread::yield_now();
            }
        }
    });
    for index in 0..128 {
        plan.request_id = format!("concurrent-{index}");
        let token = journal.approve("alice", &plan, deadline()).unwrap();
        let Claim::New(op) = journal
            .claim("alice", &plan, Some(&token), true, deadline())
            .unwrap()
        else {
            panic!("expected a fresh operation")
        };
        send.send(plan.request_id.clone()).unwrap();
        journal
            .dispatch_intent(&op.operation_id, deadline())
            .unwrap();
        journal
            .finish(
                &op.operation_id,
                Receipt::Succeeded {
                    value: Parameter::Integer { value: 40 },
                    evidence: Evidence::DurableReceipt,
                },
                deadline(),
            )
            .unwrap();
        completed.recv_timeout(Duration::from_secs(5)).unwrap();
    }
    drop(send);
    poller.join().unwrap();
}

#[test]
fn snapshot_reads_still_reject_inconsistent_indexes_and_malformed_records() {
    for (column, replacement) in [
        ("operation_id", "different-operation"),
        ("principal", "mallory"),
        ("request_id", "different-request"),
        ("endpoint", "different-endpoint"),
        ("state", "unknown"),
        ("record", "{}"),
    ] {
        let root = tempfile::tempdir().unwrap();
        let (_, plan) = fixture();
        let path = root.path().join("journal");
        let mut journal = SqliteJournal::open(&path, &plan.authority_id).unwrap();
        let reader = journal.admission_writer().unwrap();
        let token = journal.approve("alice", &plan, deadline()).unwrap();
        journal
            .claim("alice", &plan, Some(&token), true, deadline())
            .unwrap();
        assert!(
            reader
                .inspect_operation("bob", &plan.request_id, deadline())
                .unwrap()
                .is_none()
        );
        let db = rusqlite::Connection::open(path.join("journal-v2.sqlite")).unwrap();
        db.execute(&format!("UPDATE operations SET {column}=?1"), [replacement])
            .unwrap();
        let principal = if column == "principal" {
            replacement
        } else {
            "alice"
        };
        let id = if column == "request_id" {
            replacement
        } else {
            &plan.request_id
        };
        assert!(
            reader.inspect_operation(principal, id, deadline()).is_err(),
            "{column}"
        );
        assert!(
            journal.lookup(principal, id, deadline()).is_err(),
            "{column}"
        );
    }
}

#[test]
fn acceptance_requires_exact_owner_approval_and_binds_duplicates() {
    let root = tempfile::tempdir().unwrap();
    let (request, plan) = fixture();
    let mut journal =
        SqliteJournal::open(&root.path().join("journal"), &plan.authority_id).unwrap();
    let mut writer = journal.admission_writer().unwrap();
    assert!(
        writer
            .admit("alice", &request, &plan, "invented", deadline())
            .is_err()
    );
    let token = journal.approve("alice", &plan, deadline()).unwrap();
    assert!(
        writer
            .admit("bob", &request, &plan, &token, deadline())
            .is_err()
    );
    let row = writer
        .admit("alice", &request, &plan, &token, deadline())
        .unwrap();
    assert_eq!(row.state, AdmissionState::Accepted);
    let mut changed = request.clone();
    changed.budget_ms -= 1;
    assert!(
        writer
            .admit("alice", &changed, &plan, &token, deadline())
            .is_err()
    );
    assert_eq!(
        writer
            .admit("alice", &request, &plan, &token, deadline())
            .unwrap()
            .session,
        row.session
    );
    assert!(
        writer
            .inspect("bob", &request.request_id, deadline())
            .unwrap()
            .is_none()
    );
    let db = rusqlite::Connection::open(root.path().join("journal/journal-v2.sqlite")).unwrap();
    assert_eq!(
        db.query_row("SELECT count(*) FROM admissions", [], |r| r
            .get::<_, i64>(0))
            .unwrap(),
        1
    );
}

#[test]
fn cancellation_fences_claim_and_dispatch_intent() {
    for claimed in [false, true] {
        let root = tempfile::tempdir().unwrap();
        let (request, plan) = fixture();
        let mut journal =
            SqliteJournal::open(&root.path().join("journal"), &plan.authority_id).unwrap();
        let mut writer = journal.admission_writer().unwrap();
        let token = journal.approve("alice", &plan, deadline()).unwrap();
        writer
            .admit("alice", &request, &plan, &token, deadline())
            .unwrap();
        let operation = if claimed {
            let Claim::New(op) = journal
                .claim("alice", &plan, Some(&token), true, deadline())
                .unwrap()
            else {
                panic!()
            };
            Some(op)
        } else {
            None
        };
        assert!(
            writer
                .request_cancel("alice", &request.request_id, deadline())
                .unwrap()
        );
        if let Some(op) = operation {
            assert_eq!(
                journal
                    .dispatch_intent(&op.operation_id, deadline())
                    .unwrap()
                    .state,
                OperationState::CancelledBeforeDispatch
            );
        } else {
            assert!(
                journal
                    .claim("alice", &plan, Some(&token), true, deadline())
                    .is_err()
            );
        }
    }
}

#[test]
fn restart_retains_acceptance_without_resuming_or_reauthorizing() {
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("journal");
    let (request, plan) = fixture();
    {
        let mut journal = SqliteJournal::open(&path, &plan.authority_id).unwrap();
        let token = journal.approve("alice", &plan, deadline()).unwrap();
        let mut writer = journal.admission_writer().unwrap();
        writer
            .admit("alice", &request, &plan, &token, deadline())
            .unwrap();
        drop(journal);
        assert!(
            SqliteJournal::open(&path, &plan.authority_id).is_err(),
            "writer must hold journal lease"
        );
    }
    let mut journal = SqliteJournal::open(&path, &plan.authority_id).unwrap();
    let mut writer = journal.admission_writer().unwrap();
    let row = writer
        .inspect("alice", &request.request_id, deadline())
        .unwrap()
        .unwrap();
    assert_eq!(row.state, AdmissionState::Interrupted);
    assert!(
        journal
            .lookup("alice", &request.request_id, deadline())
            .unwrap()
            .is_none()
    );
    let token = journal.approve("alice", &plan, deadline()).unwrap();
    assert_eq!(
        writer
            .admit("alice", &request, &plan, &token, deadline())
            .unwrap()
            .state,
        AdmissionState::Interrupted
    );
    assert!(
        journal
            .claim("alice", &plan, Some(&token), true, deadline())
            .is_err()
    );
}

#[test]
fn failed_or_expired_admission_is_not_acknowledged() {
    let root = tempfile::tempdir().unwrap();
    let (request, plan) = fixture();
    let mut journal =
        SqliteJournal::open(&root.path().join("journal"), &plan.authority_id).unwrap();
    let token = journal.approve("alice", &plan, deadline()).unwrap();
    let mut writer = journal.admission_writer().unwrap();
    assert!(
        writer
            .admit("alice", &request, &plan, &token, Instant::now())
            .is_err()
    );
    let db = rusqlite::Connection::open(root.path().join("journal/journal-v2.sqlite")).unwrap();
    db.execute_batch("CREATE TRIGGER fail_admission BEFORE INSERT ON admissions BEGIN SELECT RAISE(ABORT, 'injected_storage_failure'); END;").unwrap();
    assert!(
        writer
            .admit("alice", &request, &plan, &token, deadline())
            .is_err()
    );
    assert!(
        writer
            .inspect("alice", &request.request_id, deadline())
            .unwrap()
            .is_none()
    );
    db.execute_batch("DROP TRIGGER fail_admission; BEGIN EXCLUSIVE;")
        .unwrap();
    let started = Instant::now();
    assert!(
        writer
            .admit(
                "alice",
                &request,
                &plan,
                &token,
                started + Duration::from_millis(40)
            )
            .is_err()
    );
    assert!(started.elapsed() < Duration::from_millis(300));
    db.execute_batch("ROLLBACK;").unwrap();
    assert!(
        writer
            .inspect("alice", &request.request_id, deadline())
            .unwrap()
            .is_none()
    );
}

#[test]
fn corruption_fails_closed_without_restart_mutations() {
    for corruption in [
        "UPDATE admissions SET request_id='other'",
        "UPDATE admissions SET record='{}'",
    ] {
        let root = tempfile::tempdir().unwrap();
        let (request, plan) = fixture();
        let path = root.path().join("journal");
        {
            let mut journal = SqliteJournal::open(&path, &plan.authority_id).unwrap();
            let token = journal.approve("alice", &plan, deadline()).unwrap();
            journal
                .admission_writer()
                .unwrap()
                .admit("alice", &request, &plan, &token, deadline())
                .unwrap();
        }
        let db = rusqlite::Connection::open(path.join("journal-v2.sqlite")).unwrap();
        db.execute_batch(corruption).unwrap();
        assert!(SqliteJournal::open(&path, &plan.authority_id).is_err());
    }
}

#[test]
fn admission_crash_child() {
    let Ok(path) = std::env::var("EDGE_ADMISSION_CRASH_PATH") else {
        return;
    };
    let (request, plan) = fixture();
    let mut journal = SqliteJournal::open(Path::new(&path), &plan.authority_id).unwrap();
    let token = journal.approve("alice", &plan, deadline()).unwrap();
    journal
        .admission_writer()
        .unwrap()
        .admit("alice", &request, &plan, &token, deadline())
        .unwrap();
    std::process::exit(0); // no authority cleanup / journal destructor
}

#[test]
fn committed_acceptance_survives_actual_process_death() {
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("journal");
    let status = std::process::Command::new(std::env::current_exe().unwrap())
        .args(["--exact", "admission_crash_child"])
        .env("EDGE_ADMISSION_CRASH_PATH", &path)
        .status()
        .unwrap();
    assert!(status.success());
    let (request, plan) = fixture();
    let journal = SqliteJournal::open(&path, &plan.authority_id).unwrap();
    assert_eq!(
        journal
            .admission_writer()
            .unwrap()
            .inspect("alice", &request.request_id, deadline())
            .unwrap()
            .unwrap()
            .state,
        AdmissionState::Interrupted
    );
}

#[test]
fn schema_one_upgrade_retains_a_consistent_private_backup() {
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("journal");
    let (_, plan) = fixture();
    {
        let mut journal = SqliteJournal::open(&path, &plan.authority_id).unwrap();
        let token = journal.approve("alice", &plan, deadline()).unwrap();
        journal
            .claim("alice", &plan, Some(&token), true, deadline())
            .unwrap();
    }
    let db = rusqlite::Connection::open(path.join("journal-v2.sqlite")).unwrap();
    db.execute_batch("DROP TABLE admissions; PRAGMA user_version=1;")
        .unwrap();
    drop(db);
    let mut upgraded = SqliteJournal::open(&path, &plan.authority_id).unwrap();
    assert_eq!(
        upgraded
            .lookup("alice", &plan.request_id, deadline())
            .unwrap()
            .unwrap()
            .state,
        OperationState::CancelledBeforeDispatch
    );
    let backups: Vec<_> = std::fs::read_dir(&path)
        .unwrap()
        .map(|e| e.unwrap().path())
        .filter(|p| {
            p.file_name()
                .unwrap()
                .to_string_lossy()
                .starts_with("before-schema-2-")
        })
        .collect();
    assert_eq!(backups.len(), 1);
    let backup = rusqlite::Connection::open(&backups[0]).unwrap();
    assert_eq!(
        backup
            .query_row("PRAGMA user_version", [], |r| r.get::<_, i32>(0))
            .unwrap(),
        1
    );
    assert_eq!(
        backup
            .query_row("SELECT state FROM operations", [], |r| r
                .get::<_, String>(0))
            .unwrap(),
        "prepared"
    );
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        assert_eq!(
            backups[0].metadata().unwrap().permissions().mode() & 0o777,
            0o600
        );
    }
    drop(upgraded);
    drop(SqliteJournal::open(&path, &plan.authority_id).unwrap());
    assert_eq!(
        std::fs::read_dir(&path)
            .unwrap()
            .filter(|e| e
                .as_ref()
                .unwrap()
                .file_name()
                .to_string_lossy()
                .starts_with("before-schema-2-"))
            .count(),
        1
    );
}

#[test]
fn failed_migration_rolls_back_schema_and_preserves_backup() {
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("journal");
    let (_, plan) = fixture();
    {
        let mut journal = SqliteJournal::open(&path, &plan.authority_id).unwrap();
        let token = journal.approve("alice", &plan, deadline()).unwrap();
        journal
            .claim("alice", &plan, Some(&token), true, deadline())
            .unwrap();
    }
    let db = rusqlite::Connection::open(path.join("journal-v2.sqlite")).unwrap();
    db.execute_batch(
        "DROP TABLE admissions; PRAGMA user_version=1; UPDATE operations SET record='{}';",
    )
    .unwrap();
    assert!(SqliteJournal::open(&path, &plan.authority_id).is_err());
    assert_eq!(
        db.query_row("PRAGMA user_version", [], |r| r.get::<_, i32>(0))
            .unwrap(),
        1
    );
    assert_eq!(
        db.query_row(
            "SELECT count(*) FROM sqlite_master WHERE name='admissions'",
            [],
            |r| r.get::<_, i64>(0)
        )
        .unwrap(),
        0
    );
    assert_eq!(
        std::fs::read_dir(&path)
            .unwrap()
            .filter(|e| e
                .as_ref()
                .unwrap()
                .file_name()
                .to_string_lossy()
                .starts_with("before-schema-2-"))
            .count(),
        1
    );
}
