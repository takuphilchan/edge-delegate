use edge_contracts::preview::PreviewContext;
use edge_protocol::{
    local::{
        DeadlineStream, LocalCredential, private_directory, private_file, private_metadata,
        same_user,
    },
    read_frame,
    service::{
        Command, ErrorCode, PROTOCOL_VERSION, Reply, SERVICE_VERSION, ServiceMode, ServiceRequest,
        ServiceResponse,
    },
    write_frame,
};
use fs2::FileExt;
use std::{
    fs::{self, DirBuilder, File, OpenOptions},
    io::{self, Write},
    os::unix::{
        fs::{DirBuilderExt, FileTypeExt, OpenOptionsExt, PermissionsExt},
        net::{UnixListener, UnixStream},
    },
    path::{Path, PathBuf},
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    thread,
    time::{Duration, Instant},
};
use subtle::ConstantTimeEq;
use uuid::Uuid;

pub const MAX_CONNECTIONS: usize = 8;
pub const CONNECTION_BUDGET: Duration = Duration::from_secs(2);

pub struct PreviewServer {
    listener: UnixListener,
    socket: PathBuf,
    _owner: File,
    context: Arc<PreviewContext>,
    credential: LocalCredential,
}

fn invalid(message: &str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidInput, message)
}

impl PreviewServer {
    /// Owner-only bootstrap. The credential permits inspection, never approval or dispatch.
    /// A dedicated directory is required; this is not a legacy journal directory.
    pub fn bind(directory: &Path, context: PreviewContext) -> io::Result<Self> {
        context
            .validate()
            .map_err(|_| invalid("invalid saved context"))?;
        // Ensure even the largest response can be encoded before announcing readiness.
        write_frame(
            &mut Vec::new(),
            &ServiceResponse::new(
                "capabilities".into(),
                Reply::Capabilities {
                    context: context.clone(),
                },
            ),
        )?;
        match DirBuilder::new().mode(0o700).create(directory) {
            Ok(()) => (),
            Err(e) if e.kind() == io::ErrorKind::AlreadyExists => (),
            Err(e) => return Err(e),
        }
        private_directory(directory)?;
        let lock_path = directory.join("preview.lock");
        let owner = match OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&lock_path)
        {
            Ok(file) => file,
            Err(e) if e.kind() == io::ErrorKind::AlreadyExists => {
                private_file(&lock_path)?;
                OpenOptions::new().read(true).write(true).open(&lock_path)?
            }
            Err(e) => return Err(e),
        };
        owner
            .try_lock_exclusive()
            .map_err(|_| invalid("preview directory already owned"))?;
        let socket = directory.join("preview.sock");
        match fs::symlink_metadata(&socket) {
            Ok(_) => {
                if !private_metadata(&socket)?.file_type().is_socket() {
                    return Err(invalid("refusing to replace a non-socket path"));
                }
                // Lock is held: only our stale socket from an earlier host may be removed.
                fs::remove_file(&socket)?;
            }
            Err(e) if e.kind() == io::ErrorKind::NotFound => (),
            Err(e) => return Err(e),
        }
        let listener = UnixListener::bind(&socket)?;
        fs::set_permissions(&socket, fs::Permissions::from_mode(0o600))?;
        listener.set_nonblocking(true)?;
        let credential = LocalCredential {
            schema_version: "edge-local-credential.v1".into(),
            principal: "local-owner".into(),
            authority_id: context.authority_id.clone(),
            token: format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple()),
        };
        let server = Self {
            listener,
            socket,
            _owner: owner,
            context: Arc::new(context),
            credential,
        };
        let credential_path = directory.join("client.json");
        if fs::symlink_metadata(&credential_path).is_ok() {
            // Never replace an unrelated private file in a mistakenly selected directory.
            LocalCredential::load(directory)?;
        }
        let temporary = directory.join(format!("credential-{}.tmp", Uuid::new_v4()));
        let result = (|| {
            let mut file = OpenOptions::new()
                .write(true)
                .create_new(true)
                .mode(0o600)
                .open(&temporary)?;
            serde_json::to_writer(&mut file, &server.credential).map_err(io::Error::other)?;
            file.flush()?;
            file.sync_all()?;
            fs::rename(&temporary, &credential_path)?;
            File::open(directory)?.sync_all()
        })();
        if result.is_err() {
            let _ = fs::remove_file(temporary);
        }
        result?;
        Ok(server)
    }

    pub fn serve_until(&self, stop: &AtomicBool) -> io::Result<()> {
        let mut workers: Vec<thread::JoinHandle<()>> = Vec::new();
        while !stop.load(Ordering::Acquire) {
            let mut index = 0;
            while index < workers.len() {
                if workers[index].is_finished() {
                    let _ = workers.swap_remove(index).join();
                } else {
                    index += 1;
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
                            &ServiceResponse::new(
                                "admission".into(),
                                Reply::Error {
                                    code: ErrorCode::Overloaded,
                                },
                            ),
                        );
                        continue;
                    }
                    let context = self.context.clone();
                    let credential = self.credential.clone();
                    let deadline = Instant::now() + CONNECTION_BUDGET;
                    workers.push(thread::spawn(move || {
                        let _ = handle(stream, &context, &credential, deadline);
                    }));
                }
                Err(e) if e.kind() == io::ErrorKind::WouldBlock => {
                    thread::sleep(Duration::from_millis(5))
                }
                Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
                Err(e) => return Err(e),
            }
        }
        for worker in workers {
            let _ = worker.join();
        }
        Ok(())
    }
}

impl Drop for PreviewServer {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.socket);
    }
}

fn authenticated(request: &ServiceRequest, credential: &LocalCredential) -> bool {
    request
        .credential
        .as_bytes()
        .ct_eq(credential.token.as_bytes())
        .into()
}

fn handle(
    stream: UnixStream,
    context: &PreviewContext,
    credential: &LocalCredential,
    deadline: Instant,
) -> io::Result<()> {
    let mut stream = DeadlineStream { stream, deadline };
    let Some(hello) = read_frame::<ServiceRequest>(&mut stream)? else {
        return Ok(());
    };
    let hello_reply = if !authenticated(&hello, credential) {
        Reply::Error {
            code: ErrorCode::Unauthenticated,
        }
    } else if hello.schema_version != SERVICE_VERSION {
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
            } if minimum_version <= PROTOCOL_VERSION && maximum_version >= PROTOCOL_VERSION => {
                Reply::Hello {
                    protocol_version: PROTOCOL_VERSION,
                    authority_id: context.authority_id.clone(),
                    principal: credential.principal.clone(),
                    mode: ServiceMode::SavedContextPreviewOnly,
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
    let accepted = matches!(hello_reply, Reply::Hello { .. });
    write_frame(
        &mut stream,
        &ServiceResponse::new(hello.call_id, hello_reply),
    )?;
    if !accepted {
        return Ok(());
    }
    let Some(request) = read_frame::<ServiceRequest>(&mut stream)? else {
        return Ok(());
    };
    if let Command::Preview { request } = &request.command
        && (1..=5000).contains(&request.budget_ms)
    {
        stream.deadline = stream
            .deadline
            .min(Instant::now() + Duration::from_millis(request.budget_ms.into()));
    }
    let reply = if !authenticated(&request, credential) {
        Reply::Error {
            code: ErrorCode::Unauthenticated,
        }
    } else if request.validate().is_err() {
        Reply::Error {
            code: ErrorCode::InvalidRequest,
        }
    } else {
        match request.command {
            Command::Capabilities {} => Reply::Capabilities {
                context: context.clone(),
            },
            Command::Preview { request } => match edge_core::preview(&request, context) {
                Ok(preview) => Reply::Preview { preview },
                Err(_) => Reply::Error {
                    code: ErrorCode::InvalidRequest,
                },
            },
            Command::Hello { .. } => Reply::Error {
                code: ErrorCode::InvalidRequest,
            },
        }
    };
    if Instant::now() >= stream.deadline {
        return Err(io::Error::new(io::ErrorKind::TimedOut, "preview expired"));
    }
    write_frame(&mut stream, &ServiceResponse::new(request.call_id, reply))
}
