//! Authenticated Linux v2 endpoint. Same-user installed software remains trusted.
use crate::actions::{ActionAuthority, ActionClient};
use edge_core::actions::{Adapter, Permission};
use edge_protocol::{
    execution_v2 as wire,
    local::{DeadlineStream, private_directory, private_file, private_metadata, same_user},
    read_frame, write_frame,
};
use fs2::FileExt;
use serde::{Deserialize, Serialize};
use std::{
    fs::{self, File, OpenOptions},
    io::{self, Read},
    os::unix::{
        fs::{DirBuilderExt, FileTypeExt, OpenOptionsExt, PermissionsExt},
        net::{UnixListener, UnixStream},
    },
    path::{Path, PathBuf},
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, Ordering},
    },
    thread,
    time::{Duration, Instant},
};
use subtle::ConstantTimeEq;
use uuid::Uuid;
fn io_error(e: impl ToString) -> io::Error {
    io::Error::other(e.to_string())
}
fn credential(authority: &str, principal: &str) -> wire::Credential {
    wire::Credential {
        schema_version: "edge-action-credential.v2".into(),
        authority_id: authority.into(),
        principal: principal.into(),
        token: format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple()),
    }
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Peer {
    credential: wire::Credential,
    permissions: Vec<wire::Permission>,
    revoked: bool,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Enrollment {
    schema_version: String,
    owner: wire::Credential,
    peers: Vec<Peer>,
}
impl Enrollment {
    fn validate(&self) -> io::Result<()> {
        self.owner.validate().map_err(io_error)?;
        if self.schema_version != "edge-action-enrollment.v2"
            || self.owner.principal != "owner"
            || self.peers.len() > 64
        {
            return Err(io_error("invalid_enrollment"));
        }
        let mut names = std::collections::BTreeSet::from(["owner"]);
        let mut tokens = std::collections::BTreeSet::from([self.owner.token.as_str()]);
        for p in &self.peers {
            p.credential.validate().map_err(io_error)?;
            if p.credential.authority_id != self.owner.authority_id
                || !names.insert(&p.credential.principal)
                || !tokens.insert(&p.credential.token)
            {
                return Err(io_error("invalid_enrollment_binding"));
            }
            wire::Request {
                schema_version: wire::VERSION.into(),
                call_id: "check".into(),
                credential: p.credential.token.clone(),
                command: wire::Command::Enroll {
                    principal: p.credential.principal.clone(),
                    permissions: p.permissions.clone(),
                },
            }
            .validate()
            .map_err(io_error)?;
        }
        Ok(())
    }
}
struct Runtime {
    owner: ActionAuthority,
    enrollment: Mutex<Enrollment>,
    directory: PathBuf,
}
pub struct ActionServer {
    listener: UnixListener,
    socket: PathBuf,
    _lease: File,
    runtime: Arc<Runtime>,
}
impl ActionServer {
    /// Builder is trusted installation configuration, never a client-selected executable.
    pub fn bind<F>(directory: &Path, build: F) -> io::Result<Self>
    where
        F: FnOnce(&Path, &str) -> edge_contracts::Result<Vec<Box<dyn Adapter + Send>>>,
    {
        match fs::DirBuilder::new().mode(0o700).create(directory) {
            Ok(()) => (),
            Err(e) if e.kind() == io::ErrorKind::AlreadyExists => (),
            Err(e) => return Err(e),
        }
        private_directory(directory)?;
        let path = directory.join("enrollment-v2.json");
        if !path.try_exists()? && fs::read_dir(directory)?.next().is_some() {
            return Err(io_error("v2_requires_dedicated_directory"));
        }
        let lock = directory.join("service-v2.lock");
        let lease = match OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&lock)
        {
            Ok(f) => f,
            Err(e) if e.kind() == io::ErrorKind::AlreadyExists => {
                private_file(&lock)?;
                OpenOptions::new().read(true).write(true).open(&lock)?
            }
            Err(e) => return Err(e),
        };
        lease
            .try_lock_exclusive()
            .map_err(|_| io_error("service_already_owned"))?;
        let enrollment: Enrollment = if path.symlink_metadata().is_ok() {
            let meta = private_metadata(&path)?;
            use std::os::unix::fs::MetadataExt;
            if !meta.is_file() || meta.nlink() != 1 || meta.len() > 65536 {
                return Err(io_error("invalid_enrollment_file"));
            }
            let f = File::open(&path)?;
            let after = f.metadata()?;
            if (meta.dev(), meta.ino()) != (after.dev(), after.ino()) {
                return Err(io_error("enrollment_changed"));
            }
            let mut bytes = Vec::new();
            f.take(65537).read_to_end(&mut bytes)?;
            edge_contracts::parse_json(&bytes).map_err(io_error)?
        } else {
            let e = Enrollment {
                schema_version: "edge-action-enrollment.v2".into(),
                owner: credential(&Uuid::new_v4().to_string(), "owner"),
                peers: vec![],
            };
            crate::enrollment::save(directory, "enrollment-v2.json", &e)?;
            e
        };
        enrollment.validate()?;
        let owner_path = directory.join("owner-v2.json");
        if owner_path.symlink_metadata().is_ok() {
            let saved: wire::Credential =
                edge_contracts::parse_json(&private_file(&owner_path)?).map_err(io_error)?;
            if serde_json::to_vec(&saved)? != serde_json::to_vec(&enrollment.owner)? {
                return Err(io_error("owner_credential_mismatch"));
            }
        } else {
            crate::enrollment::save(directory, "owner-v2.json", &enrollment.owner)?;
        }
        let authority = &enrollment.owner.authority_id;
        let owner = ActionAuthority::open(
            &directory.join("journal-v2"),
            authority,
            build(directory, authority).map_err(io_error)?,
        )
        .map_err(io_error)?;
        for peer in &enrollment.peers {
            let handle = owner.client(&peer.credential.principal).map_err(io_error)?;
            if peer.revoked {
                owner.revoke(&handle).map_err(io_error)?;
            }
        }
        let socket = directory.join("execution-v2.sock");
        if socket.symlink_metadata().is_ok() {
            if !private_metadata(&socket)?.file_type().is_socket() {
                return Err(io_error("unsafe_socket_path"));
            }
            fs::remove_file(&socket)?; // validated stale socket; exclusive service lease held
        }
        let listener = UnixListener::bind(&socket)?;
        fs::set_permissions(&socket, fs::Permissions::from_mode(0o600))?;
        listener.set_nonblocking(true)?;
        Ok(Self {
            listener,
            socket,
            _lease: lease,
            runtime: Arc::new(Runtime {
                owner,
                enrollment: Mutex::new(enrollment),
                directory: directory.into(),
            }),
        })
    }
    pub fn serve_until(&self, stop: &AtomicBool) -> io::Result<()> {
        let mut workers: Vec<thread::JoinHandle<()>> = vec![];
        while !stop.load(Ordering::Acquire) {
            let mut i = 0;
            while i < workers.len() {
                if workers[i].is_finished() {
                    let _ = workers.swap_remove(i).join();
                } else {
                    i += 1;
                }
            }
            match self.listener.accept() {
                Ok((stream, _)) => {
                    if same_user(&stream).is_err() {
                        continue;
                    }
                    if workers.len() >= 16 {
                        let mut stream = DeadlineStream {
                            stream,
                            deadline: Instant::now() + Duration::from_millis(20),
                        };
                        let _ = write_frame(
                            &mut stream,
                            &wire::Response::new(
                                "admission",
                                wire::Reply::Error {
                                    code: "overloaded".into(),
                                },
                            ),
                        );
                        continue;
                    }
                    let runtime = self.runtime.clone();
                    workers.push(thread::spawn(move || {
                        let _ = handle(stream, &runtime);
                    }));
                }
                Err(e) if e.kind() == io::ErrorKind::WouldBlock => {
                    thread::sleep(Duration::from_millis(2))
                }
                Err(e) if e.kind() == io::ErrorKind::Interrupted => (),
                Err(e) => {
                    self.runtime.owner.close();
                    for worker in workers {
                        let _ = worker.join();
                    }
                    return Err(e);
                }
            }
        }
        self.runtime.owner.close();
        for worker in workers {
            let _ = worker.join();
        }
        Ok(())
    }
}
impl Drop for ActionServer {
    fn drop(&mut self) {
        self.runtime.owner.close();
        let _ = fs::remove_file(&self.socket);
    }
}
impl Runtime {
    fn identity(&self, token: &str) -> Result<String, String> {
        let e = self.enrollment.lock().map_err(|_| "service_unavailable")?;
        if bool::from(token.as_bytes().ct_eq(e.owner.token.as_bytes())) {
            return Ok("owner".into());
        }
        for peer in &e.peers {
            if bool::from(token.as_bytes().ct_eq(peer.credential.token.as_bytes())) && !peer.revoked
            {
                return Ok(peer.credential.principal.clone());
            }
        }
        Err("unauthenticated".into())
    }
    fn client(&self, principal: &str) -> Result<ActionClient, String> {
        if principal == "owner" {
            return Err("client_credential_required".into());
        }
        self.owner.client(principal)
    }
    fn command(&self, principal: &str, command: wire::Command) -> Result<wire::Reply, String> {
        use wire::{Command as C, Reply as R};
        match command {
            C::Hello { .. } => Err("already_negotiated".into()),
            C::Enroll {
                principal: who,
                permissions,
            } if principal == "owner" => {
                let mut e = self.enrollment.lock().map_err(|_| "service_unavailable")?;
                if let Some(peer) = e.peers.iter().find(|p| p.credential.principal == who) {
                    if peer.revoked {
                        return Err("principal_revoked".into());
                    }
                    if edge_contracts::digest(&peer.permissions)?
                        != edge_contracts::digest(&permissions)?
                    {
                        return Err("enrollment_conflict".into());
                    }
                    return Ok(R::Enrolled {
                        credential: peer.credential.clone(),
                    });
                }
                if e.peers.len() >= 64 {
                    return Err("principal_capacity".into());
                }
                let credential = credential(&e.owner.authority_id, &who);
                e.peers.push(Peer {
                    credential: credential.clone(),
                    permissions: permissions.clone(),
                    revoked: false,
                });
                if serde_json::to_vec(&*e)
                    .map_err(|_| "enrollment_encoding_failed")?
                    .len()
                    > 65536
                {
                    e.peers.pop();
                    return Err("principal_capacity".into());
                }
                e.peers.pop();
                self.owner.enroll(
                    &who,
                    permissions
                        .iter()
                        .map(|p| Permission {
                            endpoint: p.endpoint.clone(),
                            action: p.action.clone(),
                        })
                        .collect(),
                )?;
                e.peers.push(Peer {
                    credential: credential.clone(),
                    permissions,
                    revoked: false,
                });
                if crate::enrollment::save(&self.directory, "enrollment-v2.json", &*e).is_err() {
                    self.owner.close();
                    return Err("persistence_uncertain".into());
                }
                Ok(R::Enrolled { credential })
            }
            C::Revoke { principal: who } if principal == "owner" => {
                let mut e = self.enrollment.lock().map_err(|_| "service_unavailable")?;
                let peer = e
                    .peers
                    .iter_mut()
                    .find(|p| p.credential.principal == who)
                    .ok_or("unknown_principal")?;
                peer.revoked = true;
                if crate::enrollment::save(&self.directory, "enrollment-v2.json", &*e).is_err() {
                    self.owner.close();
                    return Err("persistence_uncertain".into());
                }
                self.owner.revoke(&self.owner.client(&who)?)?;
                Ok(R::Revoked { principal: who })
            }
            C::Approve {
                principal: who,
                request_id,
                plan_sha256,
            } if principal == "owner" => {
                let e = self.enrollment.lock().map_err(|_| "service_unavailable")?;
                if !e
                    .peers
                    .iter()
                    .any(|p| p.credential.principal == who && !p.revoked)
                {
                    return Err("unknown_principal".into());
                }
                self.owner
                    .approve(&self.owner.client(&who)?, &request_id, &plan_sha256)?;
                Ok(R::Approved {
                    request_id,
                    plan_sha256,
                })
            }
            C::Inspect {
                principal: who,
                request_id,
            } if principal == "owner" => Ok(R::Record {
                record: Box::new(
                    self.owner
                        .client(&who)?
                        .status(&request_id)?
                        .ok_or("unknown_request")?,
                ),
            }),
            C::Enroll { .. } | C::Revoke { .. } | C::Approve { .. } | C::Inspect { .. } => {
                Err("forbidden".into())
            }
            C::Capabilities { after, limit } => {
                let mut items = self.client(principal)?.capabilities()?;
                items.sort_by_key(|c| format!("{}:{}", c.target.endpoint_id, c.definition.action));
                let offset = match after {
                    None => 0,
                    Some(cursor) => cursor.parse::<usize>().map_err(|_| "invalid_cursor")?,
                };
                if offset > items.len() {
                    return Err("invalid_cursor".into());
                }
                let end = (offset + limit as usize).min(items.len());
                let next = (end < items.len()).then(|| end.to_string());
                Ok(R::Capabilities {
                    items: items[offset..end].to_vec(),
                    next,
                })
            }
            C::Preview { request } => Ok(R::Record {
                record: Box::new(self.client(principal)?.preview(&request)?),
            }),
            C::Execute {
                request_id,
                plan_sha256,
            } => Ok(R::Record {
                record: Box::new(self.client(principal)?.execute(&request_id, &plan_sha256)?),
            }),
            C::Status { request_id } => Ok(R::Record {
                record: Box::new(
                    self.client(principal)?
                        .status(&request_id)?
                        .ok_or("unknown_request")?,
                ),
            }),
            C::Cancel { request_id } => Ok(R::Record {
                record: Box::new(self.client(principal)?.cancel(&request_id)?),
            }),
            C::Reconcile { request_id } => Ok(R::Record {
                record: Box::new(self.client(principal)?.reconcile(&request_id)?),
            }),
            C::Events { after, limit } => Ok(R::Events {
                items: self.client(principal)?.events(after, limit)?,
            }),
        }
    }
}
fn public_error(error: String) -> wire::Reply {
    // Never send raw storage errors, paths, request content or credentials.
    let allowed = [
        "unauthenticated",
        "forbidden",
        "unknown_request",
        "unknown_principal",
        "approval_required",
        "invalid_confirmation",
        "expired_or_already_approved",
        "preview_expired",
        "policy_denied",
        "policy_changed_or_revoked",
        "request_identity_conflict",
        "repreview_required",
        "authority_overloaded",
        "authority_stopping_or_fenced",
        "principal_revoked",
        "enrollment_conflict",
        "principal_capacity",
        "persistence_uncertain",
        "operation_still_active",
        "invalid_cursor",
        "client_credential_required",
        "action_capacity",
        "deadline_expired",
    ];
    wire::Reply::Error {
        code: if allowed.contains(&error.as_str()) {
            error
        } else {
            "request_failed_inspect_status".into()
        },
    }
}
fn handle(stream: UnixStream, runtime: &Runtime) -> io::Result<()> {
    let mut stream = DeadlineStream {
        stream,
        deadline: Instant::now() + Duration::from_secs(2),
    };
    let hello: wire::Request = read_frame(&mut stream)?.ok_or_else(|| io_error("missing_hello"))?;
    let principal = match hello
        .validate()
        .and_then(|_| runtime.identity(&hello.credential))
    {
        Ok(p) if matches!(hello.command, wire::Command::Hello { .. }) => p,
        _ => {
            write_frame(
                &mut stream,
                &wire::Response::new(
                    &hello.call_id,
                    wire::Reply::Error {
                        code: "negotiation_or_authentication_failed".into(),
                    },
                ),
            )?;
            return Ok(());
        }
    };
    let authority_id = runtime
        .enrollment
        .lock()
        .map_err(|_| io_error("service_unavailable"))?
        .owner
        .authority_id
        .clone();
    write_frame(
        &mut stream,
        &wire::Response::new(
            &hello.call_id,
            wire::Reply::Hello {
                protocol_version: 2,
                authority_id,
                principal: principal.clone(),
            },
        ),
    )?;
    let Some(request) = read_frame::<wire::Request>(&mut stream)? else {
        return Ok(());
    };
    let result = request.validate().and_then(|_| {
        if !bool::from(
            request
                .credential
                .as_bytes()
                .ct_eq(hello.credential.as_bytes()),
        ) {
            return Err("unauthenticated".into());
        }
        if runtime.identity(&request.credential)? != principal {
            return Err("unauthenticated".into());
        }
        runtime.command(&principal, request.command)
    });
    // Client waiting is separate from the execution budget; a dropped response never cancels.
    stream.deadline = Instant::now() + Duration::from_secs(2);
    write_frame(
        &mut stream,
        &wire::Response::new(&request.call_id, result.unwrap_or_else(public_error)),
    )
}
