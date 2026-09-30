#![cfg(target_os = "linux")]
use edge_contracts::actions::{
    Action, Endpoint, FieldRule, Output, OutputRule, Receipt, Record, Request, State,
};
use edge_contracts::preview::{Effect, ParameterRule};
use edge_contracts::{Evidence, Parameter, Result, TargetBinding, digest};
use edge_core::actions::{Adapter, Permission};
use edge_host::actions::{ActionAuthority, ActionClient};
use edge_workspace::Workspace;
use std::sync::{
    Arc,
    atomic::{AtomicUsize, Ordering},
    mpsc,
};
use std::time::{Duration, Instant};

fn text(s: &str) -> Parameter {
    Parameter::String { value: s.into() }
}
fn permissions() -> Vec<Permission> {
    ["notes.create", "notes.read", "notes.list"]
        .into_iter()
        .map(|action| Permission {
            endpoint: "notes".into(),
            action: action.into(),
        })
        .collect()
}
fn open(root: &std::path::Path, extra: Vec<Box<dyn Adapter + Send>>) -> ActionAuthority {
    let mut adapters: Vec<Box<dyn Adapter + Send>> = vec![Box::new(
        Workspace::open(&root.join("notes"), "host", "notes").unwrap(),
    )];
    adapters.extend(extra);
    ActionAuthority::open(&root.join("journal"), "host", adapters).unwrap()
}
fn request(
    client: &ActionClient,
    id: &str,
    action: &str,
    parameters: edge_contracts::actions::Fields,
) -> Request {
    Request {
        schema_version: "edge-action-request.v1".into(),
        request_id: id.into(),
        target: client
            .capabilities()
            .unwrap()
            .into_iter()
            .find(|c| c.definition.action == action)
            .unwrap()
            .target,
        action: action.into(),
        parameters,
        budget_ms: 2000,
    }
}
fn create(client: &ActionClient, id: &str) -> Request {
    request(
        client,
        id,
        "notes.create",
        [
            ("title".into(), text("Session")),
            ("body".into(), text("private-note-content")),
        ]
        .into(),
    )
}
fn approved(owner: &ActionAuthority, client: &ActionClient, req: &Request) -> String {
    let record = client.preview(req).unwrap();
    let hash = digest(&record.plan).unwrap();
    owner.approve(client, &req.request_id, &hash).unwrap();
    hash
}
fn note_id(record: &Record) -> String {
    match record.receipt.as_ref().unwrap() {
        Receipt::Succeeded {
            output:
                Output::Scalar {
                    value: Parameter::Resource { value },
                },
            ..
        } => value.clone(),
        other => panic!("unexpected {other:?}"),
    }
}

#[test]
fn notes_require_owner_approval_and_keep_private_durable_history() {
    let temp = tempfile::tempdir().unwrap();
    let owner = open(temp.path(), vec![]);
    let alice = owner.enroll("alice", permissions()).unwrap();
    let bob = owner.enroll("bob", permissions()).unwrap();
    let req = create(&alice, "create-1");
    let offered = alice.preview(&req).unwrap();
    let hash = digest(&offered.plan).unwrap();
    assert_eq!(
        alice.execute("create-1", &hash).unwrap_err(),
        "approval_required"
    );
    assert_eq!(
        alice.status("create-1").unwrap().unwrap().state,
        State::Offered
    );
    owner.approve(&alice, "create-1", &hash).unwrap();
    let done = alice.execute("create-1", &hash).unwrap();
    assert_eq!(done.state, State::Succeeded);
    assert_eq!(
        note_id(&done),
        note_id(&alice.execute("create-1", &hash).unwrap())
    );
    let mut changed = req.clone();
    changed.parameters.insert("title".into(), text("different"));
    assert_eq!(
        alice.preview(&changed).unwrap_err(),
        "request_identity_conflict"
    );
    assert!(bob.status("create-1").unwrap().is_none());
    for (client, expected, id) in [
        (&alice, State::Succeeded, "read-a"),
        (&bob, State::Failed, "read-b"),
    ] {
        let req = request(
            client,
            id,
            "notes.read",
            [(
                "note_id".into(),
                Parameter::Resource {
                    value: note_id(&done),
                },
            )]
            .into(),
        );
        let record = client.preview(&req).unwrap();
        assert_eq!(
            client
                .execute(id, &digest(&record.plan).unwrap())
                .unwrap()
                .state,
            expected
        );
    }
    let events = alice.events(0, 100).unwrap();
    assert!(events.iter().all(|e| e.principal == "alice"));
    assert!(
        !serde_json::to_string(&events)
            .unwrap()
            .contains("private-note-content")
    );
    assert_eq!(
        events
            .iter()
            .filter(|e| e.kind == "dispatch_intent" && e.request_id.as_deref() == Some("create-1"))
            .count(),
        1
    );
    let first = alice.events(0, 2).unwrap();
    let rest = alice.events(first.last().unwrap().sequence, 100).unwrap();
    assert_eq!(first.len() + rest.len(), events.len());
    drop(alice);
    drop(bob);
    drop(owner);
    let owner = open(temp.path(), vec![]);
    let alice = owner.client("alice").unwrap();
    assert_eq!(
        note_id(&alice.status("create-1").unwrap().unwrap()),
        note_id(&done)
    );
    assert_eq!(alice.events(0, 100).unwrap().len(), events.len());
}

fn counter_endpoint() -> Endpoint {
    let actions = vec![Action {
        action: "counter.set".into(),
        effect: Effect::Write,
        parameters: [(
            "value".into(),
            FieldRule::Scalar {
                rule: ParameterRule::Integer {
                    minimum: 0,
                    maximum: 100,
                },
            },
        )]
        .into(),
        output: OutputRule::Scalar {
            rule: FieldRule::Scalar {
                rule: ParameterRule::Integer {
                    minimum: 0,
                    maximum: 100,
                },
            },
        },
        max_duration_ms: 5000,
        expected_evidence: Evidence::DurableReceipt,
        allows_handoff: false,
    }];
    Endpoint {
        binding: TargetBinding {
            authority_id: "host".into(),
            endpoint_id: "counter".into(),
            registration_generation: 1,
            observation_generation: 0,
            catalog_sha256: digest(&actions).unwrap(),
        },
        actions,
    }
}
struct Counter {
    calls: Arc<AtomicUsize>,
    entered: Option<mpsc::Sender<()>>,
    release: Option<mpsc::Receiver<()>>,
    lose_ack: bool,
    panic_reconcile: bool,
}
impl Adapter for Counter {
    fn describe(&self) -> Result<Endpoint> {
        Ok(counter_endpoint())
    }
    fn invoke(
        &mut self,
        _: &str,
        _: &str,
        request: &Request,
        deadline: Instant,
    ) -> Result<Receipt> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        if let Some(entered) = self.entered.take() {
            entered.send(()).unwrap();
        }
        if let Some(release) = self.release.take() {
            release
                .recv_timeout(deadline.saturating_duration_since(Instant::now()))
                .map_err(|_| "test_timeout")?;
        }
        if self.lose_ack {
            return Err("ack_lost".into());
        }
        Ok(Receipt::Succeeded {
            output: Output::Scalar {
                value: request.parameters["value"].clone(),
            },
            evidence: Evidence::DurableReceipt,
        })
    }
    fn reconcile(&mut self, _: &str, _: &str, request: &Request, _: Instant) -> Result<Receipt> {
        assert!(!self.panic_reconcile, "injected reconciliation panic");
        Ok(Receipt::Succeeded {
            output: Output::Scalar {
                value: request.parameters["value"].clone(),
            },
            evidence: Evidence::DurableReceipt,
        })
    }
}
fn counter_permission() -> Permission {
    Permission {
        endpoint: "counter".into(),
        action: "counter.set".into(),
    }
}
fn counter_request(id: &str) -> Request {
    Request {
        schema_version: "edge-action-request.v1".into(),
        request_id: id.into(),
        target: counter_endpoint().binding,
        action: "counter.set".into(),
        parameters: [("value".into(), Parameter::Integer { value: 40 })].into(),
        budget_ms: 2000,
    }
}
fn wait_prepared(client: &ActionClient, id: &str) {
    let end = Instant::now() + Duration::from_secs(1);
    loop {
        if client.status(id).unwrap().unwrap().state == State::Prepared {
            return;
        }
        assert!(Instant::now() < end, "request never accepted");
        std::thread::yield_now();
    }
}

#[test]
fn independent_adapter_routes_through_same_approval_and_lost_ack_recovery() {
    let temp = tempfile::tempdir().unwrap();
    let calls = Arc::new(AtomicUsize::new(0));
    let owner = open(
        temp.path(),
        vec![Box::new(Counter {
            calls: calls.clone(),
            entered: None,
            release: None,
            lose_ack: true,
            panic_reconcile: false,
        })],
    );
    let mut allowed = permissions();
    allowed.push(counter_permission());
    let client = owner.enroll("alice", allowed).unwrap();
    assert_eq!(client.capabilities().unwrap().len(), 4);
    let hash = approved(&owner, &client, &counter_request("counter-1"));
    assert_eq!(
        client.execute("counter-1", &hash).unwrap().state,
        State::Unknown
    );
    assert_eq!(
        client.execute("counter-1", &hash).unwrap().state,
        State::Unknown
    );
    let second = approved(&owner, &client, &counter_request("counter-2"));
    assert_eq!(
        client.execute("counter-2", &second).unwrap().state,
        State::CancelledBeforeDispatch
    );
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        client.reconcile("counter-1").unwrap().state,
        State::Succeeded
    );
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    let note = create(&client, "note-after-counter");
    let hash = approved(&owner, &client, &note);
    assert_eq!(
        client.execute(&note.request_id, &hash).unwrap().state,
        State::Succeeded
    );
}

#[test]
fn queued_cancel_revoke_expiry_and_close_never_dispatch() {
    for mode in ["cancel", "revoke", "expiry", "close"] {
        let temp = tempfile::tempdir().unwrap();
        let calls = Arc::new(AtomicUsize::new(0));
        let (entered_tx, entered_rx) = mpsc::channel();
        let (release_tx, release_rx) = mpsc::channel();
        let owner = open(
            temp.path(),
            vec![Box::new(Counter {
                calls: calls.clone(),
                entered: Some(entered_tx),
                release: Some(release_rx),
                lose_ack: false,
                panic_reconcile: false,
            })],
        );
        let client = owner.enroll("alice", vec![counter_permission()]).unwrap();
        let first = approved(&owner, &client, &counter_request("first"));
        let mut req = counter_request("queued");
        if mode == "expiry" {
            req.budget_ms = 100;
        }
        let second = approved(&owner, &client, &req);
        let c = client.clone();
        let active = std::thread::spawn(move || c.execute("first", &first).unwrap());
        entered_rx.recv_timeout(Duration::from_secs(1)).unwrap();
        // Status and cancellation do not wait behind the blocked adapter.
        assert_eq!(
            client.status("first").unwrap().unwrap().state,
            State::Dispatching
        );
        let c = client.clone();
        let queued = std::thread::spawn(move || c.execute("queued", &second).unwrap());
        wait_prepared(&client, "queued");
        match mode {
            "cancel" => {
                client.cancel("queued").unwrap();
            }
            "revoke" => {
                owner.revoke(&client).unwrap();
            }
            "close" => owner.close(),
            "expiry" => {
                // Join proves the budget expires while the active adapter remains blocked.
                assert_eq!(queued.join().unwrap().state, State::ExpiredBeforeDispatch);
                release_tx.send(()).unwrap();
                active.join().unwrap();
                assert_eq!(calls.load(Ordering::SeqCst), 1);
                continue;
            }
            _ => unreachable!(),
        }
        release_tx.send(()).unwrap();
        active.join().unwrap();
        assert_eq!(queued.join().unwrap().state, State::CancelledBeforeDispatch);
        assert_eq!(calls.load(Ordering::SeqCst), 1);
    }
}

#[test]
fn concurrent_duplicate_invokes_once_and_dispatch_cancellation_is_uncertain() {
    let temp = tempfile::tempdir().unwrap();
    let calls = Arc::new(AtomicUsize::new(0));
    let (entered_tx, entered_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let owner = open(
        temp.path(),
        vec![Box::new(Counter {
            calls: calls.clone(),
            entered: Some(entered_tx),
            release: Some(release_rx),
            lose_ack: false,
            panic_reconcile: false,
        })],
    );
    let client = owner.enroll("alice", vec![counter_permission()]).unwrap();
    let hash = approved(&owner, &client, &counter_request("same"));
    let c = client.clone();
    let h = hash.clone();
    let active = std::thread::spawn(move || c.execute("same", &h).unwrap());
    entered_rx.recv_timeout(Duration::from_secs(1)).unwrap();
    assert_eq!(
        client.execute("same", &hash).unwrap().state,
        State::Dispatching
    );
    assert_eq!(client.cancel("same").unwrap().state, State::Unknown);
    assert_eq!(
        client.reconcile("same").unwrap_err(),
        "operation_still_active"
    );
    release_tx.send(()).unwrap();
    assert_eq!(active.join().unwrap().state, State::Unknown);
    assert_eq!(client.reconcile("same").unwrap().state, State::Succeeded);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

#[test]
fn stale_policy_foreign_owner_and_reconciliation_panic_fail_closed() {
    let temp = tempfile::tempdir().unwrap();
    let owner = open(
        temp.path(),
        vec![Box::new(Counter {
            calls: Arc::new(AtomicUsize::new(0)),
            entered: None,
            release: None,
            lose_ack: true,
            panic_reconcile: true,
        })],
    );
    let client = owner.enroll("alice", vec![counter_permission()]).unwrap();
    let hash = approved(&owner, &client, &counter_request("lost"));
    assert_eq!(client.execute("lost", &hash).unwrap().state, State::Unknown);
    assert_eq!(client.reconcile("lost").unwrap().state, State::Unknown);
    assert_eq!(client.reconcile("lost").unwrap_err(), "adapter_unavailable");
    let alice = owner.enroll("notes-client", permissions()).unwrap();
    let req = create(&alice, "stale");
    let hash = approved(&owner, &alice, &req);
    let other_temp = tempfile::tempdir().unwrap();
    let other = open(other_temp.path(), vec![]);
    assert_eq!(
        other.approve(&alice, "stale", &hash).unwrap_err(),
        "foreign_client_handle"
    );
    owner.revoke(&alice).unwrap();
    assert_eq!(
        alice.execute("stale", &hash).unwrap_err(),
        "policy_changed_or_revoked"
    );
    // Own historical records remain inspectable after revocation; no dispatch privilege remains.
    assert!(alice.status("stale").unwrap().is_some());
}

#[test]
fn ninth_waiter_is_rejected_without_acceptance_or_invocation() {
    let temp = tempfile::tempdir().unwrap();
    let calls = Arc::new(AtomicUsize::new(0));
    let (entered_tx, entered_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let owner = open(
        temp.path(),
        vec![Box::new(Counter {
            calls: calls.clone(),
            entered: Some(entered_tx),
            release: Some(release_rx),
            lose_ack: false,
            panic_reconcile: false,
        })],
    );
    let client = owner.enroll("alice", vec![counter_permission()]).unwrap();
    let jobs: Vec<_> = (0..10)
        .map(|n| {
            let mut req = counter_request(&format!("queued-{n}"));
            req.budget_ms = 5000;
            let hash = approved(&owner, &client, &req);
            (req.request_id, hash)
        })
        .collect();
    let mut threads = vec![];
    for (n, (id, hash)) in jobs.iter().take(9).enumerate() {
        let (c, id_copy, hash) = (client.clone(), id.clone(), hash.clone());
        threads.push(std::thread::spawn(move || {
            c.execute(&id_copy, &hash).unwrap()
        }));
        if n == 0 {
            entered_rx.recv_timeout(Duration::from_secs(1)).unwrap();
        } else {
            wait_prepared(&client, id);
        }
    }
    let (id, hash) = &jobs[9];
    assert_eq!(
        client.execute(id, hash).unwrap_err(),
        "authority_overloaded"
    );
    assert_eq!(client.status(id).unwrap().unwrap().state, State::Offered);
    for (id, _) in jobs.iter().skip(1) {
        client.cancel(id).unwrap();
    }
    release_tx.send(()).unwrap();
    for thread in threads {
        thread.join().unwrap();
    }
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}
