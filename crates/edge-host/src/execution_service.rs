//! Linux, per-user, software-only execution IPC. Same-user installed applications are
//! trusted; token scopes do not sandbox malicious processes under that OS account.
use crate::{
    authority::{Grant, Permission, ScopedClient, SoftwareAuthority, TicketStatus},
    enrollment::{Entry, Registry, credential},
};
use edge_core::cancellation::CancelDisposition;
use edge_protocol::{
    adapter::SimulatorFault,
    execution::{self as wire, Command, ErrorCode, Progress, Reply, Scope},
    local::{DeadlineStream, private_directory, private_file, private_metadata, same_user},
    read_frame, write_frame,
};
use fs2::FileExt;
use std::{
    collections::{BTreeMap, BTreeSet},
    fs::{self, File, OpenOptions},
    io,
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

pub const MAX_CONNECTIONS: usize = 8;
struct Peers {
    registry: Registry,
    handles: BTreeMap<String, ScopedClient>,
}
struct Runtime {
    authority: SoftwareAuthority,
    peers: Mutex<Peers>,
    directory: PathBuf,
}
#[derive(Clone)]
enum Identity {
    Owner,
    Client {
        principal: String,
        scope: Scope,
        handle: ScopedClient,
    },
}
pub struct ExecutionServer {
    listener: UnixListener,
    socket: PathBuf,
    _lease: File,
    runtime: Arc<Runtime>,
}
fn invalid(message: &str) -> io::Error {
    io::Error::other(message)
}
fn grant(principal: &str, scope: Scope) -> Grant {
    let mut permissions = BTreeSet::from([Permission::Preview, Permission::Status]);
    if scope == Scope::Control {
        permissions.extend([
            Permission::Execute,
            Permission::Cancel,
            Permission::Reconcile,
        ]);
    }
    Grant {
        principal: principal.into(),
        actions: BTreeSet::from(["audio.volume.set".into()]),
        endpoints: BTreeSet::from(["output".into()]),
        permissions,
    }
}
fn progress(status: &TicketStatus) -> Progress {
    match status {
        TicketStatus::Persisting => Progress::Persisting,
        TicketStatus::Queued => Progress::Queued,
        TicketStatus::Running => Progress::Running,
        TicketStatus::CancelledBeforeDispatch => Progress::CancelledBeforeDispatch,
        TicketStatus::ExpiredBeforeDispatch => Progress::ExpiredBeforeDispatch,
        TicketStatus::Completed { .. } => Progress::Completed,
        TicketStatus::NeedsInspection { .. } => Progress::NeedsInspection,
    }
}
impl ExecutionServer {
    /// Installed configuration supplies the worker path, never a remote request.
    pub fn bind(directory: &Path, worker: &Path, fault: SimulatorFault) -> io::Result<Self> {
        match fs::DirBuilder::new().mode(0o700).create(directory) {
            Ok(()) => (),
            Err(e) if e.kind() == io::ErrorKind::AlreadyExists => (),
            Err(e) => return Err(e),
        }
        private_directory(directory)?;
        // Do not adopt an unrelated/legacy directory or silently reset lost enrollment.
        let registry_path = directory.join("enrollment.json");
        if registry_path.symlink_metadata().is_err() && fs::read_dir(directory)?.next().is_some() {
            return Err(invalid(
                "new service needs an empty directory; existing service needs enrollment.json",
            ));
        }
        let lock = directory.join("execution.lock");
        let lease = match OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&lock)
        {
            Ok(file) => file,
            Err(e) if e.kind() == io::ErrorKind::AlreadyExists => {
                private_file(&lock)?;
                OpenOptions::new().read(true).write(true).open(&lock)?
            }
            Err(e) => return Err(e),
        };
        lease
            .try_lock_exclusive()
            .map_err(|_| invalid("execution service already owned"))?;
        let authority = SoftwareAuthority::start(&directory.join("authority"), worker, fault)
            .map_err(io::Error::other)?;
        let registry = if registry_path.symlink_metadata().is_ok() {
            Registry::load(&registry_path, authority.authority_id())?
        } else {
            let registry = Registry::new(authority.authority_id());
            registry.save(directory)?;
            registry
        };
        registry.ensure_owner_file(directory)?;
        let mut handles = BTreeMap::new();
        for peer in &registry.peers {
            if !peer.revoked {
                handles.insert(
                    peer.credential.principal.clone(),
                    authority
                        .enroll(grant(&peer.credential.principal, peer.scope))
                        .map_err(io::Error::other)?,
                );
            }
        }
        let socket = directory.join("execution.sock");
        if socket.symlink_metadata().is_ok() {
            if !private_metadata(&socket)?.file_type().is_socket() {
                return Err(invalid("refusing to replace non-socket execution path"));
            }
            fs::remove_file(&socket)?; // validated stale socket, exclusive service lease held
        }
        let listener = UnixListener::bind(&socket)?;
        fs::set_permissions(&socket, fs::Permissions::from_mode(0o600))?;
        listener.set_nonblocking(true)?;
        Ok(Self {
            listener,
            socket,
            _lease: lease,
            runtime: Arc::new(Runtime {
                authority,
                peers: Mutex::new(Peers { registry, handles }),
                directory: directory.into(),
            }),
        })
    }
    pub fn serve_until(&self, stop: &AtomicBool) -> io::Result<()> {
        let mut workers: Vec<thread::JoinHandle<()>> = Vec::new();
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
                    if workers.len() >= MAX_CONNECTIONS {
                        let mut stream = DeadlineStream {
                            stream,
                            deadline: Instant::now() + Duration::from_millis(20),
                        };
                        let _ = write_frame(
                            &mut stream,
                            &wire::Response::new(
                                "admission".into(),
                                Reply::Error {
                                    code: ErrorCode::Overloaded,
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
                    thread::sleep(Duration::from_millis(5))
                }
                Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
                Err(e) => {
                    for worker in workers {
                        let _ = worker.join();
                    }
                    return Err(e);
                }
            }
        }
        for worker in workers {
            let _ = worker.join();
        }
        Ok(())
    }
}
impl Drop for ExecutionServer {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.socket);
    }
}

impl Runtime {
    fn identity(&self, token: &str) -> Result<Identity, ErrorCode> {
        let peers = self.peers.lock().map_err(|_| ErrorCode::Rejected)?;
        if bool::from(
            token
                .as_bytes()
                .ct_eq(peers.registry.owner.token.as_bytes()),
        ) {
            return Ok(Identity::Owner);
        }
        for peer in &peers.registry.peers {
            if !peer.revoked && bool::from(token.as_bytes().ct_eq(peer.credential.token.as_bytes()))
            {
                return peers
                    .handles
                    .get(&peer.credential.principal)
                    .cloned()
                    .map(|handle| Identity::Client {
                        principal: peer.credential.principal.clone(),
                        scope: peer.scope,
                        handle,
                    })
                    .ok_or(ErrorCode::Unauthenticated);
            }
        }
        Err(ErrorCode::Unauthenticated)
    }
    fn client(&self, principal: &str) -> Result<ScopedClient, String> {
        let peers = self.peers.lock().map_err(|_| "registry_poisoned")?;
        if !peers
            .registry
            .peers
            .iter()
            .any(|p| p.credential.principal == principal && !p.revoked)
        {
            return Err("client_unavailable".into());
        }
        peers
            .handles
            .get(principal)
            .cloned()
            .ok_or("client_unavailable".into())
    }
    fn status(&self, principal: &str, id: &str) -> Result<Reply, String> {
        let live = self
            .client(principal)
            .ok()
            .and_then(|h| self.authority.ticket_status(&h, id).ok())
            .map(|s| progress(&s))
            .unwrap_or(Progress::NotInMemory);
        Ok(Reply::Status {
            request_id: id.into(),
            progress: live,
            admission: self
                .authority
                .inspect_admission(principal, id)?
                .map(Box::new),
            operation: self
                .authority
                .inspect_operation(principal, id)?
                .map(Box::new),
        })
    }
    fn dispatch(&self, identity: Identity, command: Command) -> Reply {
        let result: Result<Reply, String> = (|| {
            match (&identity, command) {
                (_, Command::Capabilities {}) => Ok(Reply::Capabilities {
                    software_only: true,
                    action: "audio.volume.set".into(),
                    endpoint: "output".into(),
                    scope: match identity {
                        Identity::Owner => None,
                        Identity::Client { scope, .. } => Some(scope),
                    },
                }),
                (
                    Identity::Client { handle, .. },
                    Command::PreviewVolume { percent, budget_ms },
                ) => {
                    let offer = handle.preview_volume(percent, budget_ms)?;
                    Ok(Reply::Preview {
                        request_id: offer.request_id,
                        plan: offer.plan,
                        plan_sha256: offer.plan_sha256,
                    })
                }
                (
                    Identity::Client {
                        handle, principal, ..
                    },
                    Command::Submit { request_id },
                ) => {
                    let progress = progress(&handle.submit(&request_id)?);
                    let admission_durable = self
                        .authority
                        .inspect_admission(principal, &request_id)?
                        .is_some();
                    Ok(Reply::Submission {
                        progress,
                        admission_durable,
                        request_id,
                    })
                }
                (Identity::Client { principal, .. }, Command::Status { request_id }) => {
                    self.status(principal, &request_id)
                }
                (Identity::Client { handle, .. }, Command::Cancel { request_id }) => {
                    Ok(Reply::Cancelled {
                        disposition: match handle.cancel(&request_id)? {
                            CancelDisposition::PreventedDispatch => {
                                wire::Cancellation::PreventedDispatch
                            }
                            CancelDisposition::PossiblyDispatched => {
                                wire::Cancellation::PossiblyDispatched
                            }
                            CancelDisposition::AlreadyFinished => {
                                wire::Cancellation::AlreadyFinished
                            }
                        },
                        request_id,
                    })
                }
                (Identity::Client { handle, .. }, Command::Reconcile { request_id }) => {
                    Ok(Reply::Reconciled {
                        operation: Box::new(handle.reconcile(&request_id)?),
                    })
                }
                (Identity::Owner, Command::Enroll { principal, scope }) => {
                    let mut peers = self.peers.lock().map_err(|_| "registry_poisoned")?;
                    if let Some(entry) = peers
                        .registry
                        .peers
                        .iter()
                        .find(|p| p.credential.principal == principal)
                    {
                        if entry.scope != scope || entry.revoked {
                            return Err("enrollment_conflict".into());
                        }
                        return Ok(Reply::Enrolled {
                            credential: entry.credential.clone(),
                        });
                    }
                    if peers.registry.peers.len() >= 64 {
                        return Err("client_capacity_reached".into());
                    }
                    let handle = self.authority.enroll(grant(&principal, scope))?;
                    let credential = credential(self.authority.authority_id(), &principal);
                    peers.registry.peers.push(Entry {
                        credential: credential.clone(),
                        scope,
                        revoked: false,
                    });
                    peers.handles.insert(principal.clone(), handle.clone());
                    if peers.registry.save(&self.directory).is_err() {
                        if let Some(entry) = peers.registry.peers.last_mut() {
                            entry.revoked = true;
                        }
                        let _ = self.authority.revoke(&handle);
                        return Err("enrollment_persistence_uncertain".into());
                    }
                    Ok(Reply::Enrolled { credential })
                }
                (Identity::Owner, Command::Peers {}) => {
                    let peers = self.peers.lock().map_err(|_| "registry_poisoned")?;
                    Ok(Reply::Peers {
                        peers: peers
                            .registry
                            .peers
                            .iter()
                            .map(|p| wire::Peer {
                                principal: p.credential.principal.clone(),
                                scope: p.scope,
                                revoked: p.revoked,
                            })
                            .collect(),
                    })
                }
                (
                    Identity::Owner,
                    Command::Approve {
                        principal,
                        request_id,
                        plan_sha256,
                    },
                ) => {
                    self.authority
                        .approve(&self.client(&principal)?, &request_id, &plan_sha256)?;
                    Ok(Reply::Confirmed {
                        request_id,
                        plan_sha256,
                    })
                }
                (
                    Identity::Owner,
                    Command::Inspect {
                        principal,
                        request_id,
                    },
                ) => self.status(&principal, &request_id),
                (
                    Identity::Owner,
                    Command::Recover {
                        principal,
                        request_id,
                    },
                ) => Ok(Reply::Reconciled {
                    operation: Box::new(self.authority.reconcile_record(&principal, &request_id)?),
                }),
                (Identity::Owner, Command::RestartAdapter {}) => {
                    self.authority.restart_adapter()?;
                    Ok(Reply::AdapterRestarted {})
                }
                (Identity::Owner, Command::Revoke { principal }) => {
                    let mut peers = self.peers.lock().map_err(|_| "registry_poisoned")?;
                    let entry = peers
                        .registry
                        .peers
                        .iter_mut()
                        .find(|p| p.credential.principal == principal)
                        .ok_or("unknown_peer")?;
                    entry.revoked = true;
                    // Gate first; durable enrollment then ensures new connections stay denied after restart.
                    let cancel = peers
                        .handles
                        .get(&principal)
                        .map(|h| self.authority.revoke(h))
                        .transpose();
                    let saved = peers.registry.save(&self.directory);
                    saved.map_err(|_| "revocation_persistence_uncertain")?;
                    cancel?;
                    Ok(Reply::Revoked { principal })
                }
                _ => Err("forbidden".into()),
            }
        })();
        result.unwrap_or_else(|e| Reply::Error {
            code: match e.as_str() {
                "forbidden" | "permission_denied" | "client_revoked" => ErrorCode::Forbidden,
                "authority_overloaded" => ErrorCode::Overloaded,
                "owner_approval_required" => ErrorCode::ApprovalRequired,
                "invalid_or_expired_confirmation"
                | "invalid_expired_or_consumed_approval"
                | "repreview_required" => ErrorCode::RepreviewRequired,
                "unknown_offer" | "unknown_ticket" | "unknown_request" | "unknown_peer" => {
                    ErrorCode::NotFound
                }
                "enrollment_conflict" | "request_identity_conflict" => ErrorCode::Conflict,
                "client_capacity_reached"
                | "offer_capacity_reached"
                | "admission_capacity_reached" => ErrorCode::Capacity,
                "enrollment_persistence_uncertain" | "revocation_persistence_uncertain" => {
                    ErrorCode::PersistenceUncertain
                }
                _ => ErrorCode::Rejected,
            },
        })
    }
}

fn handle(stream: UnixStream, runtime: &Runtime) -> io::Result<()> {
    let mut stream = DeadlineStream {
        stream,
        deadline: Instant::now() + Duration::from_secs(2),
    };
    let Some(hello) = read_frame::<wire::Request>(&mut stream)? else {
        return Ok(());
    };
    let identity = runtime.identity(&hello.credential);
    let reply = if let Err(code) = identity {
        Reply::Error { code }
    } else if hello.schema_version != wire::VERSION {
        Reply::Error {
            code: ErrorCode::IncompatibleVersion,
        }
    } else if hello.validate().is_err() {
        Reply::Error {
            code: ErrorCode::InvalidRequest,
        }
    } else {
        match hello.command {
            Command::Hello {
                minimum_version,
                maximum_version,
            } if minimum_version <= wire::PROTOCOL && maximum_version >= wire::PROTOCOL => {
                Reply::Hello {
                    protocol_version: wire::PROTOCOL,
                    authority_id: runtime.authority.authority_id().into(),
                    principal: match identity.as_ref().expect("authenticated") {
                        Identity::Owner => "owner".into(),
                        Identity::Client { principal, .. } => principal.clone(),
                    },
                    software_only: true,
                }
            }
            Command::Hello { .. } => Reply::Error {
                code: ErrorCode::IncompatibleVersion,
            },
            _ => Reply::Error {
                code: ErrorCode::NegotiationRequired,
            },
        }
    };
    let accepted = matches!(reply, Reply::Hello { .. });
    write_frame(&mut stream, &wire::Response::new(hello.call_id, reply))?;
    if !accepted {
        return Ok(());
    }
    let Some(request) = read_frame::<wire::Request>(&mut stream)? else {
        return Ok(());
    };
    // One authenticated identity for the entire connection. No token switching after hello.
    let reply = if !bool::from(
        request
            .credential
            .as_bytes()
            .ct_eq(hello.credential.as_bytes()),
    ) {
        Reply::Error {
            code: ErrorCode::Unauthenticated,
        }
    } else if request.validate().is_err() {
        Reply::Error {
            code: ErrorCode::InvalidRequest,
        }
    } else if Instant::now() >= stream.deadline {
        return Err(io::Error::new(
            io::ErrorKind::TimedOut,
            "request framing expired",
        ));
    } else {
        match runtime.identity(&request.credential) {
            Ok(identity) => runtime.dispatch(identity, request.command),
            Err(code) => Reply::Error { code },
        }
    };
    // Response delivery budget is separate; client disconnect/timeout never implies cancellation.
    stream.deadline = Instant::now() + Duration::from_secs(2);
    write_frame(&mut stream, &wire::Response::new(request.call_id, reply))
}
