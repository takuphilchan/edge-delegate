#![cfg(target_os = "linux")]
use edge_client::local::LocalClient;
use edge_contracts::{
    ControlRequest, RequestInput, parse_json,
    preview::{PreviewContext, PreviewDecision},
};
use edge_host::local::PreviewServer;
use edge_protocol::{
    local::{DeadlineStream, LocalCredential},
    read_frame,
    service::{Command, ErrorCode, Reply, SERVICE_VERSION, ServiceRequest, ServiceResponse},
    write_frame,
};
use std::{
    fs,
    io::{Read, Write},
    os::unix::{
        fs::{PermissionsExt, symlink},
        net::UnixStream,
    },
    path::PathBuf,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};

fn context() -> PreviewContext {
    parse_json(include_bytes!(
        "../../../conformance/contracts/preview-v2/context.json"
    ))
    .unwrap()
}
fn request() -> ControlRequest {
    ControlRequest::parse(include_bytes!(
        "../../../conformance/contracts/preview-v2/request.json"
    ))
    .unwrap()
}
struct Running {
    _temp: tempfile::TempDir,
    directory: PathBuf,
    stop: Arc<AtomicBool>,
    thread: Option<JoinHandle<()>>,
}
impl Running {
    fn new() -> Self {
        let temp = tempfile::tempdir().unwrap();
        let directory = temp.path().join("preview");
        let server = PreviewServer::bind(&directory, context()).unwrap();
        let stop = Arc::new(AtomicBool::new(false));
        let flag = stop.clone();
        let thread = thread::spawn(move || server.serve_until(&flag).unwrap());
        Self {
            _temp: temp,
            directory,
            stop,
            thread: Some(thread),
        }
    }
    fn wire(&self) -> DeadlineStream {
        DeadlineStream {
            stream: UnixStream::connect(self.directory.join("preview.sock")).unwrap(),
            deadline: Instant::now() + Duration::from_secs(4),
        }
    }
    fn envelope(&self, command: Command) -> ServiceRequest {
        ServiceRequest {
            schema_version: SERVICE_VERSION.into(),
            call_id: "test-call".into(),
            credential: LocalCredential::load(&self.directory).unwrap().token,
            command,
        }
    }
}
impl Drop for Running {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Release);
        self.thread.take().unwrap().join().unwrap();
    }
}
fn hello() -> Command {
    Command::Hello {
        minimum_version: 1,
        maximum_version: 1,
    }
}
fn roundtrip(stream: &mut DeadlineStream, request: &ServiceRequest) -> Reply {
    write_frame(stream, request).unwrap();
    let response: ServiceResponse = read_frame(stream).unwrap().unwrap();
    assert_eq!(response.call_id, request.call_id);
    response.reply
}

#[test]
fn public_client_matches_offline_preview_without_execution_dependencies() {
    let host = Running::new();
    let mut client = LocalClient::connect(&host.directory).unwrap();
    let catalog = client.capabilities().unwrap();
    assert_eq!(catalog.authority_id, context().authority_id);
    let result = client.preview(&request()).unwrap();
    assert_eq!(
        serde_json::to_value(&result).unwrap(),
        serde_json::to_value(edge_core::preview(&request(), &context()).unwrap()).unwrap()
    );
    assert!(!result.execution_attempted);
    assert!(matches!(
        result.decision,
        PreviewDecision::Proposed {
            requires_approval: true,
            ..
        }
    ));
    let files: Vec<_> = fs::read_dir(&host.directory).unwrap().collect();
    assert_eq!(files.len(), 3); // socket, owner lock, credential; no execution journal.
    client.close();
    assert!(client.capabilities().is_err());
}

#[test]
fn unknown_text_and_stale_bindings_do_not_turn_into_actions() {
    let host = Running::new();
    let client = LocalClient::connect(&host.directory).unwrap();
    let mut input = request();
    if let RequestInput::Action { target, .. } = &mut input.input {
        target.observation_generation += 1;
    }
    assert!(
        matches!(client.preview(&input).unwrap().decision, PreviewDecision::Rejected { reason } if reason == "repreview_required")
    );
    input.input = RequestInput::Text {
        text: "open all applications".into(),
    };
    assert!(matches!(
        client.preview(&input).unwrap().decision,
        PreviewDecision::ClarificationRequired { .. }
    ));
    input.authority_id = "other-host".into();
    assert!(client.preview(&input).is_err());
}

#[test]
fn invalid_credentials_rejected_before_catalog_disclosure() {
    let host = Running::new();
    let mut envelope = host.envelope(hello());
    envelope.credential = "0".repeat(64);
    let mut wire = host.wire();
    assert!(matches!(
        roundtrip(&mut wire, &envelope),
        Reply::Error {
            code: ErrorCode::Unauthenticated
        }
    ));
    assert!(read_frame::<ServiceResponse>(&mut wire).unwrap().is_none());
}

#[test]
fn incompatible_schema_version_and_missing_negotiation_fail() {
    let host = Running::new();
    for (command, schema, expected) in [
        (hello(), "unknown", ErrorCode::IncompatibleVersion),
        (
            Command::Hello {
                minimum_version: 2,
                maximum_version: 3,
            },
            SERVICE_VERSION,
            ErrorCode::IncompatibleVersion,
        ),
        (
            Command::Hello {
                minimum_version: 3,
                maximum_version: 1,
            },
            SERVICE_VERSION,
            ErrorCode::IncompatibleVersion,
        ),
        (
            Command::Capabilities {},
            SERVICE_VERSION,
            ErrorCode::NegotiationRequired,
        ),
    ] {
        let mut envelope = host.envelope(command);
        envelope.schema_version = schema.into();
        assert!(
            matches!(roundtrip(&mut host.wire(), &envelope), Reply::Error { code } if code == expected)
        );
    }
}

#[test]
fn changing_credentials_after_handshake_is_rejected() {
    let host = Running::new();
    let mut wire = host.wire();
    assert!(matches!(
        roundtrip(&mut wire, &host.envelope(hello())),
        Reply::Hello { .. }
    ));
    let mut envelope = host.envelope(Command::Capabilities {});
    envelope.credential = "a".repeat(64);
    assert!(matches!(
        roundtrip(&mut wire, &envelope),
        Reply::Error {
            code: ErrorCode::Unauthenticated
        }
    ));
}

#[test]
fn request_validation_occurs_even_after_authentication() {
    let host = Running::new();
    let mut wire = host.wire();
    roundtrip(&mut wire, &host.envelope(hello()));
    let mut input = request();
    input.budget_ms = 0;
    assert!(matches!(
        roundtrip(
            &mut wire,
            &host.envelope(Command::Preview { request: input })
        ),
        Reply::Error {
            code: ErrorCode::InvalidRequest
        }
    ));
}

#[test]
fn execution_approval_unknown_fields_duplicate_keys_and_oversize_frames_rejected() {
    let host = Running::new();
    for method in ["approve", "execute", "cancel", "reconcile"] {
        let mut message = serde_json::to_value(host.envelope(Command::Capabilities {})).unwrap();
        message["command"]["method"] = method.into();
        let mut wire = host.wire();
        roundtrip(&mut wire, &host.envelope(hello()));
        write_frame(&mut wire, &message).unwrap();
        assert!(!matches!(
            read_frame::<ServiceResponse>(&mut wire),
            Ok(Some(_))
        ));
    }
    for nested in [false, true] {
        let mut message = serde_json::to_value(host.envelope(Command::Capabilities {})).unwrap();
        if nested {
            message["command"]["execute"] = true.into();
        } else {
            message["principal"] = "admin".into();
        }
        let mut wire = host.wire();
        roundtrip(&mut wire, &host.envelope(hello()));
        write_frame(&mut wire, &message).unwrap();
        assert!(!matches!(
            read_frame::<ServiceResponse>(&mut wire),
            Ok(Some(_))
        ));
    }
    for raw in [
        br#"{"command":{"method":"execute"}}"#.as_slice(),
        br#"{"command":{"method":"approve"}}"#,
        br#"{"credential":"a","credential":"b"}"#,
        br#"{"principal":"admin"}"#,
    ] {
        let mut wire = host.wire();
        wire.write_all(&(raw.len() as u32).to_be_bytes()).unwrap();
        wire.write_all(raw).unwrap();
        assert!(!matches!(
            read_frame::<ServiceResponse>(&mut wire),
            Ok(Some(_))
        ));
    }
    let mut wire = host.wire();
    wire.write_all(&65537_u32.to_be_bytes()).unwrap();
    assert!(!matches!(
        read_frame::<ServiceResponse>(&mut wire),
        Ok(Some(_))
    ));
    assert!(
        LocalClient::connect(&host.directory)
            .unwrap()
            .capabilities()
            .is_ok()
    );
}

#[test]
fn client_rejects_mismatched_host_identity_schema_version_and_call_id() {
    for change in 0..4 {
        let temp = tempfile::tempdir().unwrap();
        let directory = temp.path().join("host");
        drop(PreviewServer::bind(&directory, context()).unwrap());
        let listener =
            std::os::unix::net::UnixListener::bind(directory.join("preview.sock")).unwrap();
        fs::set_permissions(
            directory.join("preview.sock"),
            fs::Permissions::from_mode(0o600),
        )
        .unwrap();
        let worker = thread::spawn(move || {
            let (stream, _) = listener.accept().unwrap();
            let mut wire = DeadlineStream {
                stream,
                deadline: Instant::now() + Duration::from_secs(2),
            };
            let hello: ServiceRequest = read_frame(&mut wire).unwrap().unwrap();
            let mut response = ServiceResponse::new(
                hello.call_id,
                Reply::Hello {
                    protocol_version: if change == 0 { 2 } else { 1 },
                    authority_id: if change == 1 {
                        "other".into()
                    } else {
                        context().authority_id
                    },
                    principal: "local-owner".into(),
                    mode: edge_protocol::service::ServiceMode::SavedContextPreviewOnly,
                },
            );
            if change == 2 {
                response.call_id = "another-call".into();
            }
            if change == 3 {
                response.schema_version = "unknown".into();
            }
            write_frame(&mut wire, &response).unwrap();
        });
        assert!(LocalClient::connect(&directory).is_err());
        worker.join().unwrap();
    }
}

#[test]
fn continuous_partial_input_does_not_extend_deadline() {
    let host = Running::new();
    let mut wire = host.wire();
    let start = Instant::now();
    wire.write_all(&500_u32.to_be_bytes()).unwrap();
    let mut sender = wire.stream.try_clone().unwrap();
    let feed = thread::spawn(move || {
        for _ in 0..12 {
            if sender.write_all(b" ").is_err() {
                break;
            }
            thread::sleep(Duration::from_millis(250));
        }
    });
    assert!(!matches!(
        read_frame::<ServiceResponse>(&mut wire),
        Ok(Some(_))
    ));
    assert!(start.elapsed() < Duration::from_secs(3));
    feed.join().unwrap();
}

#[test]
fn private_paths_lock_and_restart_credentials_are_enforced() {
    let temp = tempfile::tempdir().unwrap();
    let directory = temp.path().join("host");
    let server = PreviewServer::bind(&directory, context()).unwrap();
    let first = LocalCredential::load(&directory).unwrap().token;
    assert!(PreviewServer::bind(&directory, context()).is_err());
    drop(server);
    let restarted = PreviewServer::bind(&directory, context()).unwrap();
    assert_ne!(first, LocalCredential::load(&directory).unwrap().token);
    drop(restarted);
    fs::set_permissions(
        directory.join("client.json"),
        fs::Permissions::from_mode(0o644),
    )
    .unwrap();
    assert!(LocalCredential::load(&directory).is_err());
    assert!(PreviewServer::bind(&directory, context()).is_err());
    fs::set_permissions(&directory, fs::Permissions::from_mode(0o755)).unwrap();
    assert!(PreviewServer::bind(&directory, context()).is_err());
    let link = temp.path().join("link");
    symlink(&directory, &link).unwrap();
    assert!(PreviewServer::bind(&link, context()).is_err());
}

#[test]
fn stale_socket_recovered_but_regular_files_and_links_never_replaced() {
    let temp = tempfile::tempdir().unwrap();
    let directory = temp.path().join("host");
    fs::create_dir(&directory).unwrap();
    fs::set_permissions(&directory, fs::Permissions::from_mode(0o700)).unwrap();
    let socket = directory.join("preview.sock");
    let stale = std::os::unix::net::UnixListener::bind(&socket).unwrap();
    fs::set_permissions(&socket, fs::Permissions::from_mode(0o600)).unwrap();
    drop(stale);
    drop(PreviewServer::bind(&directory, context()).unwrap());
    fs::write(&socket, "preserve").unwrap();
    assert!(PreviewServer::bind(&directory, context()).is_err());
    assert_eq!(fs::read_to_string(&socket).unwrap(), "preserve");
    fs::remove_file(&socket).unwrap();
    symlink(directory.join("client.json"), &socket).unwrap();
    assert!(PreviewServer::bind(&directory, context()).is_err());
}

#[test]
fn partial_frames_expire_and_service_recovers() {
    let host = Running::new();
    let mut wire = host.wire();
    let start = Instant::now();
    wire.write_all(&[0]).unwrap();
    let mut byte = [0];
    assert!(!matches!(wire.read(&mut byte), Ok(n) if n > 0));
    assert!(start.elapsed() < Duration::from_secs(4));
    assert!(
        LocalClient::connect(&host.directory)
            .unwrap()
            .capabilities()
            .is_ok()
    );
}

#[test]
fn connection_limit_rejects_overload_without_growing_a_queue() {
    let host = Running::new();
    let mut held = Vec::new();
    for _ in 0..edge_host::local::MAX_CONNECTIONS {
        let mut wire = host.wire();
        assert!(matches!(
            roundtrip(&mut wire, &host.envelope(hello())),
            Reply::Hello { .. }
        ));
        held.push(wire);
    }
    let response: ServiceResponse = read_frame(&mut host.wire()).unwrap().unwrap();
    assert!(matches!(
        response.reply,
        Reply::Error {
            code: ErrorCode::Overloaded
        }
    ));
    drop(held);
}
