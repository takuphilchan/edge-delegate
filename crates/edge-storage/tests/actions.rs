#![cfg(target_os = "linux")]
use edge_contracts::actions::{Endpoint, Plan, Receipt, Request, State};
use edge_contracts::digest;
use edge_core::actions::{Permission, Policy, compile};
use edge_storage::actions::ActionJournal;
use std::time::{Duration, Instant};

fn deadline() -> Instant {
    Instant::now() + Duration::from_secs(2)
}
fn fixture(id: &str) -> (Policy, Plan) {
    let mut endpoint: Endpoint = serde_json::from_str(r#"{
        "binding":{"authority_id":"host","endpoint_id":"counter","registration_generation":1,"observation_generation":0,"catalog_sha256":"0000000000000000000000000000000000000000000000000000000000000000"},
        "actions":[{"action":"counter.set","effect":"write","parameters":{},"output":{"kind":"scalar","rule":{"kind":"resource_reference"}},"max_duration_ms":1000,"expected_evidence":"durable_receipt","allows_handoff":false}]
    }"#).unwrap();
    endpoint.binding.catalog_sha256 = digest(&endpoint.actions).unwrap();
    let policy = Policy {
        authority_id: "host".into(),
        principal: "alice".into(),
        revision: 1,
        permissions: vec![Permission {
            endpoint: "counter".into(),
            action: "counter.set".into(),
        }],
    };
    let req = Request {
        schema_version: "edge-action-request.v1".into(),
        request_id: id.into(),
        target: endpoint.binding.clone(),
        action: "counter.set".into(),
        parameters: Default::default(),
        budget_ms: 2000,
    };
    let plan = compile(&req, &[endpoint], &policy).unwrap();
    (policy, plan)
}
fn offer(j: &mut ActionJournal, id: &str) -> String {
    let (_, plan) = fixture(id);
    j.offer("alice", &plan, deadline()).unwrap();
    digest(&plan).unwrap()
}
fn admit(j: &mut ActionJournal, id: &str) {
    let hash = offer(j, id);
    j.approve("alice", id, &hash, deadline()).unwrap();
    assert!(j.admit("alice", id, &hash, deadline()).unwrap().1);
}

#[test]
fn restart_fences_each_nonterminal_stage_and_retains_events() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("journal");
    let mut j = ActionJournal::open(&path, "host").unwrap();
    j.set_policy(&fixture("a").0, deadline()).unwrap();
    offer(&mut j, "offered");
    admit(&mut j, "queued");
    admit(&mut j, "sent");
    j.dispatch("alice", "sent", deadline()).unwrap();
    drop(j);
    let mut j = ActionJournal::open(&path, "host").unwrap();
    for (id, state) in [
        ("offered", State::ExpiredBeforeDispatch),
        ("queued", State::CancelledBeforeDispatch),
        ("sent", State::Unknown),
    ] {
        assert_eq!(
            j.lookup("alice", id, deadline()).unwrap().unwrap().state,
            state
        );
    }
    let events = j.events("alice", 0, 100, deadline()).unwrap();
    assert_eq!(
        events.iter().filter(|e| e.kind == "restart_fenced").count(),
        3
    );
    admit(&mut j, "new");
    assert_eq!(
        j.dispatch("alice", "new", deadline()).unwrap_err(),
        "target_fenced_by_uncertainty"
    );
    j.finish(
        "alice",
        "sent",
        Receipt::Failed {
            reason: "confirmed_no_effect".into(),
        },
        deadline(),
    )
    .unwrap();
    j.dispatch("alice", "new", deadline()).unwrap();
}

#[test]
fn event_failure_rolls_back_state_and_approval_atomically() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("journal");
    let mut j = ActionJournal::open(&path, "host").unwrap();
    j.set_policy(&fixture("a").0, deadline()).unwrap();
    let hash = offer(&mut j, "a");
    let db = rusqlite::Connection::open(path.join("actions.sqlite")).unwrap();
    db.execute_batch("CREATE TRIGGER fail_events BEFORE INSERT ON action_events BEGIN SELECT RAISE(ABORT,'injected event failure'); END;").unwrap();
    assert!(j.approve("alice", "a", &hash, deadline()).is_err());
    db.execute_batch("DROP TRIGGER fail_events;").unwrap();
    assert_eq!(
        j.admit("alice", "a", &hash, deadline()).unwrap_err(),
        "approval_required"
    );
    j.approve("alice", "a", &hash, deadline()).unwrap();
    db.execute_batch("CREATE TRIGGER fail_events BEFORE INSERT ON action_events BEGIN SELECT RAISE(ABORT,'injected event failure'); END;").unwrap();
    assert!(j.admit("alice", "a", &hash, deadline()).is_err());
    assert_eq!(
        j.lookup("alice", "a", deadline()).unwrap().unwrap().state,
        State::Offered
    );
}

#[test]
fn changed_policy_expired_preview_and_identity_reuse_cannot_dispatch() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("journal");
    let mut j = ActionJournal::open(&path, "host").unwrap();
    let (mut policy, mut plan) = fixture("a");
    j.set_policy(&policy, deadline()).unwrap();
    let hash = offer(&mut j, "a");
    assert!(
        j.approve("alice", "a", &"f".repeat(64), deadline())
            .is_err()
    );
    plan.request.budget_ms = 1000;
    plan.request_sha256 = digest(&plan.request).unwrap();
    assert_eq!(
        j.offer("alice", &plan, deadline()).unwrap_err(),
        "request_identity_conflict"
    );
    j.approve("alice", "a", &hash, deadline()).unwrap();
    policy.revision = 2;
    policy.permissions.clear();
    j.set_policy(&policy, deadline()).unwrap();
    assert_eq!(
        j.admit("alice", "a", &hash, deadline()).unwrap_err(),
        "policy_changed_or_revoked"
    );
    policy.revision = 3;
    policy.permissions = fixture("a").0.permissions;
    j.set_policy(&policy, deadline()).unwrap();
    let (_, base) = fixture("expired");
    let plan = compile(
        &base.request,
        &[Endpoint {
            binding: base.request.target.clone(),
            actions: vec![base.definition.clone()],
        }],
        &policy,
    )
    .unwrap();
    let hash = digest(&plan).unwrap();
    j.offer("alice", &plan, deadline()).unwrap();
    let db = rusqlite::Connection::open(path.join("actions.sqlite")).unwrap();
    db.execute(
        "UPDATE action_records SET offered_ms=-60001 WHERE request_id='expired'",
        [],
    )
    .unwrap();
    assert_eq!(
        j.admit("alice", "expired", &hash, deadline()).unwrap_err(),
        "preview_expired"
    );
}

#[test]
fn ownership_corruption_and_database_lock_fail_closed() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("journal");
    let mut j = ActionJournal::open(&path, "host").unwrap();
    j.set_policy(&fixture("a").0, deadline()).unwrap();
    assert!(ActionJournal::open(&path, "host").is_err());
    let db = rusqlite::Connection::open(path.join("actions.sqlite")).unwrap();
    db.execute_batch("BEGIN IMMEDIATE;").unwrap();
    let end = Instant::now() + Duration::from_millis(30);
    assert!(j.offer("alice", &fixture("locked").1, end).is_err());
    db.execute_batch("ROLLBACK;").unwrap();
    assert!(j.lookup("alice", "locked", deadline()).unwrap().is_none());
    offer(&mut j, "a");
    db.execute("UPDATE action_records SET endpoint='wrong'", [])
        .unwrap();
    assert_eq!(
        j.lookup("alice", "a", deadline()).unwrap_err(),
        "corrupt_action_index"
    );
    drop(j);
    assert!(ActionJournal::open(&path, "host").is_err());
}

#[test]
fn live_preview_limit_and_cancelled_identity_are_retained() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("journal");
    let mut j = ActionJournal::open(&path, "host").unwrap();
    j.set_policy(&fixture("a").0, deadline()).unwrap();
    for n in 0..128 {
        offer(&mut j, &format!("case-{n}"));
    }
    assert_eq!(
        j.offer("alice", &fixture("overflow").1, deadline())
            .unwrap_err(),
        "action_capacity"
    );
    j.cancel("alice", "case-0", deadline()).unwrap();
    offer(&mut j, "overflow");
    let hash = offer(&mut j, "case-0");
    let (record, new) = j.admit("alice", "case-0", &hash, deadline()).unwrap();
    assert!(!new);
    assert_eq!(record.state, State::CancelledBeforeDispatch);
}
