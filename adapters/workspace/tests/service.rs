#![cfg(target_os = "linux")]
use edge_client::actions::{Command, Credential, GatewayClient, Permission, Reply};
use edge_contracts::{
    Parameter,
    actions::{Output, Receipt, Request, State},
    digest,
};
use edge_host::{action_process::ProcessAdapter, action_service::ActionServer};
use std::{
    path::{Path, PathBuf},
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    thread,
    time::{Duration, Instant},
};
struct Service {
    root: tempfile::TempDir,
    stop: Arc<AtomicBool>,
    thread: Option<thread::JoinHandle<()>>,
}
impl Service {
    fn new(fault: &str) -> Self {
        let mut s = Self {
            root: tempfile::tempdir().unwrap(),
            stop: Arc::new(AtomicBool::new(false)),
            thread: None,
        };
        s.start(fault);
        s
    }
    fn directory(&self) -> PathBuf {
        self.root.path().join("service")
    }
    fn start(&mut self, fault: &str) {
        self.stop = Arc::new(AtomicBool::new(false));
        let server = ActionServer::bind(&self.directory(), |directory, authority| {
            Ok(vec![Box::new(ProcessAdapter::spawn(
                Path::new(env!("CARGO_BIN_EXE_edge-delegate-workspace-worker")),
                vec![
                    "--directory".into(),
                    directory.join("notes").to_str().unwrap().into(),
                    "--authority".into(),
                    authority.into(),
                    "--endpoint".into(),
                    "notes".into(),
                    "--fault".into(),
                    fault.into(),
                ],
            )?)])
        })
        .unwrap();
        let stop = self.stop.clone();
        self.thread = Some(thread::spawn(move || server.serve_until(&stop).unwrap()));
    }
    fn stop(&mut self) {
        self.stop.store(true, Ordering::Release);
        if let Some(t) = self.thread.take() {
            t.join().unwrap();
        }
    }
    fn owner(&self) -> GatewayClient {
        GatewayClient::connect(&self.directory(), &self.directory().join("owner-v2.json")).unwrap()
    }
    fn enroll(&self, name: &str, actions: &[&str]) -> Credential {
        match self
            .owner()
            .call(Command::Enroll {
                principal: name.into(),
                permissions: actions
                    .iter()
                    .map(|a| Permission {
                        endpoint: "notes".into(),
                        action: (*a).into(),
                    })
                    .collect(),
            })
            .unwrap()
        {
            Reply::Enrolled { credential } => credential,
            _ => panic!(),
        }
    }
    fn client(&self, c: Credential) -> GatewayClient {
        GatewayClient::with_credential(&self.directory(), c).unwrap()
    }
    fn notes(&self) -> i64 {
        rusqlite::Connection::open(self.directory().join("notes/notes.sqlite"))
            .unwrap()
            .query_row("SELECT count(*) FROM notes", [], |r| r.get(0))
            .unwrap()
    }
}
impl Drop for Service {
    fn drop(&mut self) {
        self.stop();
    }
}
fn create(client: &GatewayClient, id: &str) -> Request {
    let Reply::Capabilities { items, .. } = client
        .call(Command::Capabilities {
            after: None,
            limit: 20,
        })
        .unwrap()
    else {
        panic!()
    };
    Request {
        schema_version: "edge-action-request.v1".into(),
        request_id: id.into(),
        target: items
            .iter()
            .find(|c| c.definition.action == "notes.create")
            .unwrap()
            .target
            .clone(),
        action: "notes.create".into(),
        parameters: [
            (
                "title".into(),
                Parameter::String {
                    value: "Session".into(),
                },
            ),
            (
                "body".into(),
                Parameter::String {
                    value: "inert secret note".into(),
                },
            ),
        ]
        .into(),
        budget_ms: 2000,
    }
}
fn approve(s: &Service, client: &GatewayClient, id: &str, principal: &str) -> String {
    let plan = client.preview(create(client, id)).unwrap().plan;
    let hash = digest(&plan).unwrap();
    s.owner()
        .call(Command::Approve {
            principal: principal.into(),
            request_id: id.into(),
            plan_sha256: hash.clone(),
        })
        .unwrap();
    hash
}
#[test]
fn authenticated_notes_approval_ownership_events_and_restart() {
    let mut s = Service::new("none");
    let cred = s.enroll("alice", &["notes.create", "notes.read", "notes.list"]);
    let client = s.client(cred.clone());
    let req = create(&client, "note-1");
    let preview = client.preview(req.clone()).unwrap();
    let hash = digest(&preview.plan).unwrap();
    assert!(
        client
            .execute("note-1", &hash)
            .unwrap_err()
            .to_string()
            .contains("approval_required")
    );
    assert!(
        client
            .call(Command::Approve {
                principal: "alice".into(),
                request_id: "note-1".into(),
                plan_sha256: hash.clone()
            })
            .is_err()
    );
    assert_eq!(s.notes(), 0);
    s.owner()
        .call(Command::Approve {
            principal: "alice".into(),
            request_id: "note-1".into(),
            plan_sha256: hash.clone(),
        })
        .unwrap();
    let done = client.execute("note-1", &hash).unwrap();
    assert_eq!(done.state, State::Succeeded);
    assert_eq!(
        client.execute("note-1", &hash).unwrap().operation_id,
        done.operation_id
    );
    assert_eq!(s.notes(), 1);
    let Receipt::Succeeded {
        output:
            Output::Scalar {
                value: Parameter::Resource { value: note_id },
            },
        ..
    } = done.receipt.unwrap()
    else {
        panic!()
    };
    let bob = s.client(s.enroll("bob", &["notes.read"]));
    assert!(bob.status("note-1").is_err());
    for (c, id, expected) in [
        (&client, "read-a", State::Succeeded),
        (&bob, "read-b", State::Failed),
    ] {
        let r = Request {
            request_id: id.into(),
            action: "notes.read".into(),
            parameters: [(
                "note_id".into(),
                Parameter::Resource {
                    value: note_id.clone(),
                },
            )]
            .into(),
            ..req.clone()
        };
        let p = c.preview(r).unwrap();
        assert_eq!(
            c.execute(id, &digest(&p.plan).unwrap()).unwrap().state,
            expected
        );
    }
    let Reply::Events { items } = client
        .call(Command::Events {
            after: 0,
            limit: 100,
        })
        .unwrap()
    else {
        panic!()
    };
    assert!(items.iter().all(|e| e.principal == "alice"));
    assert!(!serde_json::to_string(&items).unwrap().contains("secret"));
    let pending = approve(&s, &client, "pending", "alice");
    s.stop();
    s.start("none");
    let client = s.client(cred.clone());
    assert_eq!(client.status("note-1").unwrap().state, State::Succeeded);
    assert_eq!(
        client.execute("pending", &pending).unwrap().state,
        State::ExpiredBeforeDispatch
    );
    assert_eq!(s.notes(), 1);
    s.owner()
        .call(Command::Revoke {
            principal: "alice".into(),
        })
        .unwrap();
    assert!(client.status("note-1").is_err());
    s.stop();
    s.start("none");
    assert!(GatewayClient::with_credential(&s.directory(), cred).is_err());
    assert!(
        s.owner()
            .call(Command::Enroll {
                principal: "alice".into(),
                permissions: vec![]
            })
            .is_err()
    );
}
#[test]
fn worker_faults_remain_unknown_and_reconcile_without_replay() {
    for fault in ["lost-ack", "malformed", "crash", "hang"] {
        let mut s = Service::new(fault);
        let cred = s.enroll("alice", &["notes.create"]);
        let client = s.client(cred.clone());
        let mut req = create(&client, "fault");
        req.budget_ms = 150;
        let p = client.preview(req).unwrap();
        let hash = digest(&p.plan).unwrap();
        s.owner()
            .call(Command::Approve {
                principal: "alice".into(),
                request_id: "fault".into(),
                plan_sha256: hash.clone(),
            })
            .unwrap();
        let start = Instant::now();
        assert_eq!(
            client.execute("fault", &hash).unwrap().state,
            State::Unknown
        );
        assert!(start.elapsed() < Duration::from_secs(3));
        let effects = if matches!(fault, "lost-ack" | "malformed") {
            1
        } else {
            0
        };
        assert_eq!(s.notes(), effects);
        assert_eq!(
            client.execute("fault", &hash).unwrap().state,
            State::Unknown
        );
        assert_eq!(s.notes(), effects);
        s.stop();
        s.start("none");
        let client = s.client(cred);
        let status = client.reconcile("fault").unwrap().state;
        assert_eq!(
            status,
            if effects == 1 {
                State::Succeeded
            } else {
                State::Unknown
            }
        );
        assert_eq!(s.notes(), effects);
    }
}
#[test]
fn wrong_credentials_versions_and_token_switches_fail_closed() {
    use edge_protocol::{execution_v2 as wire, local::DeadlineStream, read_frame, write_frame};
    let s = Service::new("none");
    let cred = s.enroll("alice", &["notes.create"]);
    let mut wrong = cred.clone();
    wrong.token = "0".repeat(64);
    assert!(GatewayClient::with_credential(&s.directory(), wrong).is_err());
    let mut old = cred.clone();
    old.schema_version = "edge-execution-credential.v1".into();
    assert!(GatewayClient::with_credential(&s.directory(), old).is_err());
    let owner: Credential =
        edge_contracts::parse_json(&std::fs::read(s.directory().join("owner-v2.json")).unwrap())
            .unwrap();
    let mut stream = DeadlineStream {
        stream: std::os::unix::net::UnixStream::connect(s.directory().join("execution-v2.sock"))
            .unwrap(),
        deadline: Instant::now() + Duration::from_secs(2),
    };
    write_frame(
        &mut stream,
        &wire::Request {
            schema_version: wire::VERSION.into(),
            call_id: "hello".into(),
            credential: cred.token,
            command: Command::Hello {
                minimum_version: 2,
                maximum_version: 2,
            },
        },
    )
    .unwrap();
    assert!(matches!(
        read_frame::<wire::Response>(&mut stream)
            .unwrap()
            .unwrap()
            .reply,
        Reply::Hello { .. }
    ));
    write_frame(
        &mut stream,
        &wire::Request {
            schema_version: wire::VERSION.into(),
            call_id: "switch".into(),
            credential: owner.token,
            command: Command::Revoke {
                principal: "alice".into(),
            },
        },
    )
    .unwrap();
    assert!(matches!(
        read_frame::<wire::Response>(&mut stream)
            .unwrap()
            .unwrap()
            .reply,
        Reply::Error { .. }
    ));
    assert_eq!(s.notes(), 0);
}
#[test]
fn disconnected_execute_response_does_not_repeat_note() {
    use edge_protocol::{execution_v2 as wire, local::DeadlineStream, read_frame, write_frame};
    let s = Service::new("none");
    let cred = s.enroll("alice", &["notes.create"]);
    let c = s.client(cred.clone());
    let hash = approve(&s, &c, "dropped", "alice");
    let mut stream = DeadlineStream {
        stream: std::os::unix::net::UnixStream::connect(s.directory().join("execution-v2.sock"))
            .unwrap(),
        deadline: Instant::now() + Duration::from_secs(2),
    };
    write_frame(
        &mut stream,
        &wire::Request {
            schema_version: wire::VERSION.into(),
            call_id: "hello".into(),
            credential: cred.token.clone(),
            command: Command::Hello {
                minimum_version: 2,
                maximum_version: 2,
            },
        },
    )
    .unwrap();
    read_frame::<wire::Response>(&mut stream).unwrap();
    write_frame(
        &mut stream,
        &wire::Request {
            schema_version: wire::VERSION.into(),
            call_id: "execute".into(),
            credential: cred.token,
            command: Command::Execute {
                request_id: "dropped".into(),
                plan_sha256: hash.clone(),
            },
        },
    )
    .unwrap();
    drop(stream);
    let until = Instant::now() + Duration::from_secs(3);
    loop {
        if c.status("dropped").unwrap().state == State::Succeeded {
            break;
        }
        assert!(Instant::now() < until);
        thread::sleep(Duration::from_millis(5));
    }
    assert_eq!(c.execute("dropped", &hash).unwrap().state, State::Succeeded);
    assert_eq!(s.notes(), 1);
}

#[test]
fn cancellation_and_status_do_not_wait_for_a_hung_worker() {
    let s = Service::new("hang");
    let cred = s.enroll("alice", &["notes.create"]);
    let client = s.client(cred.clone());
    let mut req = create(&client, "hung");
    req.budget_ms = 400;
    let plan = client.preview(req).unwrap().plan;
    let hash = digest(&plan).unwrap();
    s.owner().approve("alice", "hung", &hash).unwrap();
    let runner = s.client(cred);
    let task = thread::spawn(move || runner.execute("hung", &hash).unwrap());
    let until = Instant::now() + Duration::from_secs(1);
    loop {
        if client.status("hung").unwrap().state == State::Dispatching {
            break;
        }
        assert!(Instant::now() < until);
        thread::yield_now();
    }
    assert_eq!(client.cancel("hung").unwrap().state, State::Unknown);
    assert_eq!(client.status("hung").unwrap().state, State::Unknown);
    assert_eq!(task.join().unwrap().state, State::Unknown);
    assert_eq!(s.notes(), 0);
}

#[test]
fn filtered_discovery_changed_request_and_revoked_live_connection() {
    use edge_protocol::{execution_v2 as wire, local::DeadlineStream, read_frame, write_frame};
    let s = Service::new("none");
    let cred = s.enroll("alice", &["notes.create"]);
    let client = s.client(cred.clone());
    let (items, next) = client.capabilities(None, 1).unwrap();
    assert_eq!(items.len(), 1);
    assert!(next.is_none());
    let mut request = create(&client, "bound");
    client.preview(request.clone()).unwrap();
    request.parameters.insert(
        "body".into(),
        Parameter::String {
            value: "changed".into(),
        },
    );
    assert!(client.preview(request).is_err());
    let none = s.client(s.enroll("no-actions", &[]));
    assert!(none.capabilities(None, 20).unwrap().0.is_empty());
    assert!(none.preview(create(&client, "forbidden")).is_err());
    let mut stream = DeadlineStream {
        stream: std::os::unix::net::UnixStream::connect(s.directory().join("execution-v2.sock"))
            .unwrap(),
        deadline: Instant::now() + Duration::from_secs(2),
    };
    write_frame(
        &mut stream,
        &wire::Request {
            schema_version: wire::VERSION.into(),
            call_id: "hello".into(),
            credential: cred.token.clone(),
            command: Command::Hello {
                minimum_version: 2,
                maximum_version: 2,
            },
        },
    )
    .unwrap();
    read_frame::<wire::Response>(&mut stream).unwrap();
    s.owner()
        .call(Command::Revoke {
            principal: "alice".into(),
        })
        .unwrap();
    write_frame(
        &mut stream,
        &wire::Request {
            schema_version: wire::VERSION.into(),
            call_id: "after-revoke".into(),
            credential: cred.token,
            command: Command::Status {
                request_id: "bound".into(),
            },
        },
    )
    .unwrap();
    assert!(matches!(
        read_frame::<wire::Response>(&mut stream)
            .unwrap()
            .unwrap()
            .reply,
        Reply::Error { .. }
    ));
    assert_eq!(s.notes(), 0);
}

#[test]
fn failed_revocation_persistence_fences_live_execution() {
    let s = Service::new("none");
    let cred = s.enroll("alice", &["notes.create"]);
    let client = s.client(cred);
    let hash = approve(&s, &client, "pending", "alice");
    let path = s.directory().join("enrollment-v2.json");
    let backup = s.directory().join("enrollment-saved.json");
    std::fs::rename(&path, &backup).unwrap();
    std::fs::create_dir(&path).unwrap();
    assert!(
        s.owner()
            .call(Command::Revoke {
                principal: "alice".into()
            })
            .is_err()
    );
    assert!(client.execute("pending", &hash).is_err());
    assert_eq!(s.notes(), 0);
    // Restore test enrollment without clearing the journal or manufacturing success.
    std::fs::remove_dir(&path).unwrap();
    std::fs::rename(&backup, &path).unwrap();
}
