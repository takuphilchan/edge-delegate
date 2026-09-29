#![cfg(target_os = "linux")]
use edge_client::execution::{Command, Credential, ExecutionClient, Reply, Scope};
use edge_contracts::operation::OperationState;
use edge_host::execution_service::ExecutionServer;
use edge_protocol::{
    adapter::SimulatorFault, execution as wire, local::DeadlineStream, read_frame, write_frame,
};
use std::{
    os::unix::net::UnixStream,
    path::Path,
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
    fn new(fault: SimulatorFault) -> Self {
        let mut s = Self {
            root: tempfile::tempdir().unwrap(),
            stop: Arc::new(AtomicBool::new(false)),
            thread: None,
        };
        s.start(fault);
        s
    }
    fn directory(&self) -> std::path::PathBuf {
        self.root.path().join("service")
    }
    fn start(&mut self, fault: SimulatorFault) {
        self.stop = Arc::new(AtomicBool::new(false));
        let server = ExecutionServer::bind(
            &self.directory(),
            Path::new(env!("CARGO_BIN_EXE_edge-delegate-simulator-worker")),
            fault,
        )
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
    fn owner(&self) -> ExecutionClient {
        ExecutionClient::connect(&self.directory(), &self.directory().join("owner.json")).unwrap()
    }
    fn enroll(&self, name: &str, scope: Scope) -> Credential {
        let Reply::Enrolled { credential } = self
            .owner()
            .call(Command::Enroll {
                principal: name.into(),
                scope,
            })
            .unwrap()
        else {
            panic!()
        };
        credential
    }
    fn client(&self, credential: Credential) -> ExecutionClient {
        ExecutionClient::with_credential(&self.directory(), credential).unwrap()
    }
    fn writes(&self) -> i64 {
        rusqlite::Connection::open(self.directory().join("authority/device.sqlite"))
            .unwrap()
            .query_row("SELECT writes FROM state", [], |r| r.get(0))
            .unwrap()
    }
}
impl Drop for Service {
    fn drop(&mut self) {
        self.stop();
    }
}
fn preview(client: &ExecutionClient) -> (String, String) {
    let Reply::Preview {
        request_id,
        plan_sha256,
        ..
    } = client
        .call(Command::PreviewVolume {
            percent: 40,
            budget_ms: 2000,
        })
        .unwrap()
    else {
        panic!()
    };
    (request_id, plan_sha256)
}
fn wait(client: &ExecutionClient, id: &str) -> OperationState {
    let until = Instant::now() + Duration::from_secs(4);
    loop {
        let Reply::Status { operation, .. } = client
            .call(Command::Status {
                request_id: id.into(),
            })
            .unwrap()
        else {
            panic!()
        };
        if let Some(op) = operation
            && !matches!(
                op.state,
                OperationState::Prepared | OperationState::Dispatching
            )
        {
            return op.state;
        }
        assert!(Instant::now() < until);
        thread::sleep(Duration::from_millis(10));
    }
}

#[test]
fn owner_approval_and_authenticated_client_submission_are_separate() {
    let s = Service::new(SimulatorFault::None);
    let owner = s.owner();
    let c = s.client(s.enroll("alice", Scope::Control));
    let (id, hash) = preview(&c);
    assert_eq!(s.writes(), 0);
    assert!(
        c.call(Command::Submit {
            request_id: id.clone()
        })
        .is_err()
    );
    assert!(
        c.call(Command::Approve {
            principal: "alice".into(),
            request_id: id.clone(),
            plan_sha256: hash.clone()
        })
        .is_err()
    );
    assert!(
        owner
            .call(Command::Submit {
                request_id: id.clone()
            })
            .is_err()
    );
    assert!(
        owner
            .call(Command::Approve {
                principal: "alice".into(),
                request_id: id.clone(),
                plan_sha256: "0".repeat(64)
            })
            .is_err()
    );
    owner
        .call(Command::Approve {
            principal: "alice".into(),
            request_id: id.clone(),
            plan_sha256: hash,
        })
        .unwrap();
    assert!(matches!(
        c.call(Command::Submit {
            request_id: id.clone()
        })
        .unwrap(),
        Reply::Submission {
            admission_durable: true,
            ..
        }
    ));
    assert_eq!(wait(&c, &id), OperationState::Succeeded);
    c.call(Command::Submit {
        request_id: id.clone(),
    })
    .unwrap();
    assert_eq!(s.writes(), 1);
}

#[test]
fn clients_cannot_impersonate_enroll_or_access_another_clients_request() {
    let s = Service::new(SimulatorFault::None);
    let alice = s.client(s.enroll("alice", Scope::Control));
    let bob = s.client(s.enroll("bob", Scope::Control));
    let (id, hash) = preview(&alice);
    s.owner()
        .call(Command::Approve {
            principal: "alice".into(),
            request_id: id.clone(),
            plan_sha256: hash.clone(),
        })
        .unwrap();
    alice
        .call(Command::Submit {
            request_id: id.clone(),
        })
        .unwrap();
    assert_eq!(wait(&alice, &id), OperationState::Succeeded);
    assert!(
        bob.call(Command::Submit {
            request_id: id.clone()
        })
        .is_err()
    );
    assert!(
        bob.call(Command::Cancel {
            request_id: id.clone()
        })
        .is_err()
    );
    assert!(
        bob.call(Command::Reconcile {
            request_id: id.clone()
        })
        .is_err()
    );
    assert!(
        bob.call(Command::Inspect {
            principal: "alice".into(),
            request_id: id.clone()
        })
        .is_err()
    );
    assert!(
        bob.call(Command::Enroll {
            principal: "mallory".into(),
            scope: Scope::Control
        })
        .is_err()
    );
    assert!(
        bob.call(Command::Revoke {
            principal: "alice".into()
        })
        .is_err()
    );
    assert!(
        s.owner()
            .call(Command::Approve {
                principal: "bob".into(),
                request_id: id.clone(),
                plan_sha256: hash
            })
            .is_err()
    );
    assert!(matches!(
        bob.call(Command::Status { request_id: id }).unwrap(),
        Reply::Status {
            admission: None,
            operation: None,
            ..
        }
    ));
    assert_eq!(s.writes(), 1);
}

#[test]
fn inspect_scope_cannot_approve_or_submit_writes() {
    let s = Service::new(SimulatorFault::None);
    let c = s.client(s.enroll("observer", Scope::Inspect));
    let (id, hash) = preview(&c);
    assert!(
        s.owner()
            .call(Command::Approve {
                principal: "observer".into(),
                request_id: id.clone(),
                plan_sha256: hash
            })
            .is_err()
    );
    assert!(
        c.call(Command::Submit {
            request_id: id.clone()
        })
        .is_err()
    );
    assert!(c.call(Command::Cancel { request_id: id }).is_err());
    assert_eq!(s.writes(), 0);
}

#[test]
fn credentials_survive_restart_but_approvals_do_not() {
    let mut s = Service::new(SimulatorFault::None);
    let credential = s.enroll("alice", Scope::Control);
    let c = s.client(credential.clone());
    let (id, hash) = preview(&c);
    s.owner()
        .call(Command::Approve {
            principal: "alice".into(),
            request_id: id.clone(),
            plan_sha256: hash,
        })
        .unwrap();
    s.stop();
    s.start(SimulatorFault::None);
    let c = s.client(credential);
    assert!(c.call(Command::Submit { request_id: id }).is_err());
    assert!(matches!(
        c.call(Command::Capabilities {}).unwrap(),
        Reply::Capabilities {
            software_only: true,
            ..
        }
    ));
    assert_eq!(s.writes(), 0);
}

#[test]
fn revocation_is_persistent_and_cannot_be_undone_by_reenrollment() {
    let mut s = Service::new(SimulatorFault::None);
    let credential = s.enroll("alice", Scope::Control);
    let c = s.client(credential.clone());
    let (id, hash) = preview(&c);
    s.owner()
        .call(Command::Approve {
            principal: "alice".into(),
            request_id: id.clone(),
            plan_sha256: hash,
        })
        .unwrap();
    s.owner()
        .call(Command::Revoke {
            principal: "alice".into(),
        })
        .unwrap();
    assert!(c.call(Command::Submit { request_id: id }).is_err());
    assert!(
        s.owner()
            .call(Command::Enroll {
                principal: "alice".into(),
                scope: Scope::Control
            })
            .is_err()
    );
    s.stop();
    s.start(SimulatorFault::None);
    assert!(ExecutionClient::with_credential(&s.directory(), credential).is_err());
    assert!(
        matches!(s.owner().call(Command::Peers {}).unwrap(),Reply::Peers { peers } if peers.len()==1 && peers[0].revoked)
    );
    assert_eq!(s.writes(), 0);
}

#[test]
fn cancellation_after_effect_reconciles_over_ipc_without_replay() {
    let s = Service::new(SimulatorFault::HangAfterEffect);
    let credential = s.enroll("alice", Scope::Control);
    let c = s.client(credential);
    let (id, hash) = preview(&c);
    s.owner()
        .call(Command::Approve {
            principal: "alice".into(),
            request_id: id.clone(),
            plan_sha256: hash,
        })
        .unwrap();
    c.call(Command::Submit {
        request_id: id.clone(),
    })
    .unwrap();
    let until = Instant::now() + Duration::from_secs(2);
    while s.writes() != 1 {
        assert!(Instant::now() < until);
        thread::sleep(Duration::from_millis(1));
    }
    let started = Instant::now();
    assert!(matches!(
        c.call(Command::Cancel {
            request_id: id.clone()
        })
        .unwrap(),
        Reply::Cancelled {
            disposition: wire::Cancellation::PossiblyDispatched,
            ..
        }
    ));
    assert!(started.elapsed() < Duration::from_millis(750));
    assert_eq!(wait(&c, &id), OperationState::Unknown);
    s.owner().call(Command::RestartAdapter {}).unwrap();
    assert!(
        matches!(c.call(Command::Reconcile { request_id:id.clone() }).unwrap(),Reply::Reconciled { operation } if operation.state==OperationState::Succeeded)
    );
    assert_eq!(s.writes(), 1);
}

#[test]
fn restarted_client_can_inspect_and_reconcile_its_durable_operation() {
    let mut s = Service::new(SimulatorFault::LostAcknowledgement);
    let credential = s.enroll("alice", Scope::Control);
    let c = s.client(credential.clone());
    let (id, hash) = preview(&c);
    s.owner()
        .call(Command::Approve {
            principal: "alice".into(),
            request_id: id.clone(),
            plan_sha256: hash,
        })
        .unwrap();
    c.call(Command::Submit {
        request_id: id.clone(),
    })
    .unwrap();
    assert_eq!(wait(&c, &id), OperationState::Unknown);
    s.stop();
    s.start(SimulatorFault::None);
    let c = s.client(credential);
    assert_eq!(wait(&c, &id), OperationState::Unknown);
    assert!(
        matches!(c.call(Command::Reconcile { request_id:id.clone() }).unwrap(),Reply::Reconciled { operation } if operation.state==OperationState::Succeeded)
    );
    assert!(c.call(Command::Submit { request_id: id }).is_err());
    assert_eq!(s.writes(), 1);
}

fn raw(s: &Service) -> DeadlineStream {
    DeadlineStream {
        stream: UnixStream::connect(s.directory().join("execution.sock")).unwrap(),
        deadline: Instant::now() + Duration::from_secs(3),
    }
}
fn request(token: &str, command: Command) -> wire::Request {
    wire::Request {
        schema_version: wire::VERSION.into(),
        call_id: "test".into(),
        credential: token.into(),
        command,
    }
}
#[test]
fn wrong_credentials_negotiation_and_token_switching_fail_closed() {
    let s = Service::new(SimulatorFault::None);
    let alice = s.enroll("alice", Scope::Control);
    let owner: Credential =
        edge_contracts::parse_json(&std::fs::read(s.directory().join("owner.json")).unwrap())
            .unwrap();
    for (token, command, expected) in [
        (
            "0".repeat(64),
            Command::Hello {
                minimum_version: 1,
                maximum_version: 1,
            },
            wire::ErrorCode::Unauthenticated,
        ),
        (
            alice.token.clone(),
            Command::Hello {
                minimum_version: 2,
                maximum_version: 2,
            },
            wire::ErrorCode::IncompatibleVersion,
        ),
        (
            alice.token.clone(),
            Command::Capabilities {},
            wire::ErrorCode::NegotiationRequired,
        ),
    ] {
        let mut stream = raw(&s);
        write_frame(&mut stream, &request(&token, command)).unwrap();
        assert!(
            matches!(read_frame::<wire::Response>(&mut stream).unwrap().unwrap().reply,Reply::Error { code } if code==expected)
        );
    }
    let mut stream = raw(&s);
    write_frame(
        &mut stream,
        &request(
            &alice.token,
            Command::Hello {
                minimum_version: 1,
                maximum_version: 1,
            },
        ),
    )
    .unwrap();
    assert!(matches!(
        read_frame::<wire::Response>(&mut stream)
            .unwrap()
            .unwrap()
            .reply,
        Reply::Hello { .. }
    ));
    write_frame(&mut stream, &request(&owner.token, Command::Peers {})).unwrap();
    assert!(matches!(
        read_frame::<wire::Response>(&mut stream)
            .unwrap()
            .unwrap()
            .reply,
        Reply::Error {
            code: wire::ErrorCode::Unauthenticated
        }
    ));
    assert_eq!(s.writes(), 0);
}

#[test]
fn unsafe_paths_and_changed_authority_cannot_rebind_credentials() {
    let mut s = Service::new(SimulatorFault::None);
    s.stop();
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(
        s.directory().join("owner.json"),
        std::fs::Permissions::from_mode(0o644),
    )
    .unwrap();
    assert!(
        ExecutionServer::bind(
            &s.directory(),
            Path::new(env!("CARGO_BIN_EXE_edge-delegate-simulator-worker")),
            SimulatorFault::None
        )
        .is_err()
    );
    std::fs::set_permissions(
        s.directory().join("owner.json"),
        std::fs::Permissions::from_mode(0o600),
    )
    .unwrap();
    let path = s.directory().join("enrollment.json");
    let mut json: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    json["owner"]["authority_id"] = serde_json::json!("replaced-device");
    std::fs::write(path, serde_json::to_vec(&json).unwrap()).unwrap();
    assert!(
        ExecutionServer::bind(
            &s.directory(),
            Path::new(env!("CARGO_BIN_EXE_edge-delegate-simulator-worker")),
            SimulatorFault::None
        )
        .is_err()
    );
}

#[test]
fn dropped_submission_response_does_not_repeat_an_effect() {
    let s = Service::new(SimulatorFault::None);
    let credential = s.enroll("alice", Scope::Control);
    let c = s.client(credential.clone());
    let (id, hash) = preview(&c);
    s.owner()
        .call(Command::Approve {
            principal: "alice".into(),
            request_id: id.clone(),
            plan_sha256: hash,
        })
        .unwrap();
    let mut stream = raw(&s);
    write_frame(
        &mut stream,
        &request(
            &credential.token,
            Command::Hello {
                minimum_version: 1,
                maximum_version: 1,
            },
        ),
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
        &request(
            &credential.token,
            Command::Submit {
                request_id: id.clone(),
            },
        ),
    )
    .unwrap();
    drop(stream); // simulate the client losing the acceptance response, not cancelling
    assert_eq!(wait(&c, &id), OperationState::Succeeded);
    c.call(Command::Submit { request_id: id }).unwrap();
    assert_eq!(s.writes(), 1);
}

#[test]
fn failed_revocation_persistence_is_not_acknowledged_and_live_access_is_fenced() {
    let s = Service::new(SimulatorFault::None);
    let c = s.client(s.enroll("alice", Scope::Control));
    let owner = s.owner();
    std::fs::rename(
        s.directory().join("enrollment.json"),
        s.directory().join("saved-enrollment.json"),
    )
    .unwrap();
    std::os::unix::fs::symlink(
        s.directory().join("saved-enrollment.json"),
        s.directory().join("enrollment.json"),
    )
    .unwrap();
    assert!(
        owner
            .call(Command::Revoke {
                principal: "alice".into()
            })
            .is_err()
    );
    assert!(c.call(Command::Capabilities {}).is_err());
    assert!(
        matches!(owner.call(Command::Peers {}).unwrap(),Reply::Peers { peers } if peers[0].revoked)
    );
    assert_eq!(s.writes(), 0);
}

#[test]
fn connection_overload_and_partial_frames_are_bounded() {
    use std::io::Write;
    let s = Service::new(SimulatorFault::None);
    let mut held = Vec::new();
    for _ in 0..edge_host::execution_service::MAX_CONNECTIONS {
        let mut stream = raw(&s);
        stream.write_all(&[0]).unwrap();
        held.push(stream);
    }
    thread::sleep(Duration::from_millis(60));
    let mut extra = raw(&s);
    assert!(matches!(
        read_frame::<wire::Response>(&mut extra)
            .unwrap()
            .unwrap()
            .reply,
        Reply::Error {
            code: wire::ErrorCode::Overloaded
        }
    ));
    // Each partial frame shares a two-second absolute deadline, not a fresh per-byte budget.
    for stream in &mut held {
        assert!(!matches!(read_frame::<wire::Response>(stream), Ok(Some(_))));
    }
    drop(held);
    assert!(matches!(
        s.owner().call(Command::Peers {}).unwrap(),
        Reply::Peers { .. }
    ));
    assert_eq!(s.writes(), 0);
}

#[test]
fn revocation_is_rechecked_after_an_authenticated_hello() {
    let s = Service::new(SimulatorFault::None);
    let credential = s.enroll("alice", Scope::Control);
    let client = s.client(credential.clone());
    let (id, hash) = preview(&client);
    s.owner()
        .call(Command::Approve {
            principal: "alice".into(),
            request_id: id.clone(),
            plan_sha256: hash,
        })
        .unwrap();
    let mut stream = raw(&s);
    write_frame(
        &mut stream,
        &request(
            &credential.token,
            Command::Hello {
                minimum_version: 1,
                maximum_version: 1,
            },
        ),
    )
    .unwrap();
    assert!(matches!(
        read_frame::<wire::Response>(&mut stream)
            .unwrap()
            .unwrap()
            .reply,
        Reply::Hello { .. }
    ));
    s.owner()
        .call(Command::Revoke {
            principal: "alice".into(),
        })
        .unwrap();
    write_frame(
        &mut stream,
        &request(&credential.token, Command::Submit { request_id: id }),
    )
    .unwrap();
    assert!(matches!(
        read_frame::<wire::Response>(&mut stream)
            .unwrap()
            .unwrap()
            .reply,
        Reply::Error {
            code: wire::ErrorCode::Unauthenticated
        }
    ));
    assert_eq!(s.writes(), 0);
}
