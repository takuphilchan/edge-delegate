//! Public Linux software-execution client. No automatic submission retries or approval.
pub use edge_protocol::execution::{Command, Credential, Progress, Reply, Scope};
use edge_protocol::{
    execution as wire,
    local::{DeadlineStream, private_directory, private_file, private_metadata, same_user},
    read_frame, write_frame,
};
use socket2::{Domain, SockAddr, Socket, Type};
use std::{
    fs::OpenOptions,
    io::{self, Write},
    os::unix::{
        fs::{FileTypeExt, OpenOptionsExt},
        net::UnixStream,
    },
    path::{Path, PathBuf},
    time::{Duration, Instant},
};

pub struct ExecutionClient {
    directory: PathBuf,
    credential: Credential,
    closed: bool,
}
fn invalid(message: &str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message)
}
pub fn save_credential(path: &Path, credential: &Credential) -> io::Result<()> {
    credential.validate().map_err(io::Error::other)?;
    let parent = path
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    private_directory(parent)?;
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)?;
    serde_json::to_writer(&mut file, credential)?;
    file.flush()?;
    file.sync_all()?;
    std::fs::File::open(parent)?.sync_all()
}
impl ExecutionClient {
    pub fn connect(directory: &Path, credential_file: &Path) -> io::Result<Self> {
        let credential: Credential = edge_contracts::parse_json(&private_file(credential_file)?)
            .map_err(io::Error::other)?;
        Self::with_credential(directory, credential)
    }
    pub fn with_credential(directory: &Path, credential: Credential) -> io::Result<Self> {
        credential.validate().map_err(io::Error::other)?;
        let client = Self {
            directory: directory.into(),
            credential,
            closed: false,
        };
        client.handshake()?;
        Ok(client)
    }
    fn exchange(
        &self,
        stream: &mut DeadlineStream,
        id: &str,
        command: Command,
    ) -> io::Result<Reply> {
        write_frame(
            stream,
            &wire::Request {
                schema_version: wire::VERSION.into(),
                call_id: id.into(),
                credential: self.credential.token.clone(),
                command,
            },
        )?;
        let response: wire::Response = read_frame(stream)?.ok_or_else(|| {
            invalid("service closed without response; inspect the same request ID")
        })?;
        if response.schema_version != wire::VERSION {
            return Err(invalid("incompatible execution response"));
        }
        if matches!(
            response.reply,
            Reply::Error {
                code: wire::ErrorCode::Overloaded
            }
        ) && response.call_id == "admission"
        {
            return Err(io::Error::new(
                io::ErrorKind::WouldBlock,
                "execution service connection limit",
            ));
        }
        if response.call_id != id {
            return Err(invalid("response identity mismatch"));
        }
        if let Reply::Error { code } = response.reply {
            return Err(io::Error::other(format!("execution service: {code:?}")));
        }
        Ok(response.reply)
    }
    fn handshake(&self) -> io::Result<DeadlineStream> {
        if self.closed {
            return Err(invalid("client is closed"));
        }
        private_directory(&self.directory)?;
        let socket_path = self.directory.join("execution.sock");
        if !private_metadata(&socket_path)?.file_type().is_socket() {
            return Err(invalid("expected execution socket"));
        }
        let socket = Socket::new(Domain::UNIX, Type::STREAM, None)?;
        socket.connect_timeout(&SockAddr::unix(&socket_path)?, Duration::from_secs(2))?;
        let descriptor: std::os::fd::OwnedFd = socket.into();
        let stream = UnixStream::from(descriptor);
        same_user(&stream)?;
        let mut stream = DeadlineStream {
            stream,
            deadline: Instant::now() + Duration::from_secs(2),
        };
        match self.exchange(
            &mut stream,
            "hello",
            Command::Hello {
                minimum_version: wire::PROTOCOL,
                maximum_version: wire::PROTOCOL,
            },
        )? {
            Reply::Hello {
                protocol_version,
                authority_id,
                principal,
                software_only,
            } if protocol_version == wire::PROTOCOL
                && authority_id == self.credential.authority_id
                && principal == self.credential.principal
                && software_only =>
            {
                Ok(stream)
            }
            _ => Err(invalid("execution host identity or mode mismatch")),
        }
    }
    /// One call per fresh authenticated connection. A network timeout does not cancel
    /// accepted work. Reuse its request ID for status; never blindly create a new request.
    pub fn call(&self, command: Command) -> io::Result<Reply> {
        command.validate().map_err(io::Error::other)?;
        let mut stream = self.handshake()?;
        stream.deadline = Instant::now() + Duration::from_secs(10);
        let reply = self.exchange(&mut stream, "command", command.clone())?;
        self.validate_reply(&command, &reply)?;
        Ok(reply)
    }
    fn validate_reply(&self, command: &Command, reply: &Reply) -> io::Result<()> {
        let valid = match (command, reply) {
            (
                Command::Capabilities {},
                Reply::Capabilities {
                    software_only: true,
                    action,
                    endpoint,
                    ..
                },
            ) => action == "audio.volume.set" && endpoint == "output",
            (
                Command::PreviewVolume { percent, .. },
                Reply::Preview {
                    request_id,
                    plan,
                    plan_sha256,
                },
            ) => {
                plan.schema_version == "edge-plan.v2"
                    && plan.request_id == *request_id
                    && plan.authority_id == self.credential.authority_id
                    && edge_contracts::digest(plan).map_err(io::Error::other)? == *plan_sha256
                    && plan.steps.len() == 1
                    && plan.steps[0].action == "audio.volume.set"
                    && plan.steps[0].target.authority_id == self.credential.authority_id
                    && plan.steps[0].target.endpoint_id == "output"
                    && plan.steps[0].parameters.get("percent")
                        == Some(&edge_contracts::Parameter::Integer { value: *percent })
            }
            (Command::Enroll { principal, .. }, Reply::Enrolled { credential }) => {
                credential.validate().is_ok()
                    && credential.principal == *principal
                    && credential.authority_id == self.credential.authority_id
            }
            (
                Command::Submit { request_id },
                Reply::Submission {
                    request_id: actual, ..
                },
            )
            | (
                Command::Cancel { request_id },
                Reply::Cancelled {
                    request_id: actual, ..
                },
            ) => request_id == actual,
            (
                Command::Status { request_id },
                Reply::Status {
                    request_id: actual,
                    admission,
                    operation,
                    ..
                },
            ) => {
                request_id == actual
                    && self.records_match(
                        &self.credential.principal,
                        request_id,
                        admission.as_deref(),
                        operation.as_deref(),
                    )?
            }
            (
                Command::Inspect {
                    principal,
                    request_id,
                },
                Reply::Status {
                    request_id: actual,
                    admission,
                    operation,
                    ..
                },
            ) => {
                request_id == actual
                    && self.records_match(
                        principal,
                        request_id,
                        admission.as_deref(),
                        operation.as_deref(),
                    )?
            }
            (
                Command::Approve {
                    request_id,
                    plan_sha256,
                    ..
                },
                Reply::Confirmed {
                    request_id: actual,
                    plan_sha256: hash,
                },
            ) => request_id == actual && plan_sha256 == hash,
            (Command::Reconcile { request_id }, Reply::Reconciled { operation }) => self
                .records_match(
                    &self.credential.principal,
                    request_id,
                    None,
                    Some(operation),
                )?,
            (
                Command::Recover {
                    principal,
                    request_id,
                },
                Reply::Reconciled { operation },
            ) => self.records_match(principal, request_id, None, Some(operation))?,
            (Command::Revoke { principal }, Reply::Revoked { principal: actual }) => {
                principal == actual
            }
            (Command::RestartAdapter {}, Reply::AdapterRestarted {})
            | (Command::Peers {}, Reply::Peers { .. }) => true,
            _ => false,
        };
        if valid {
            Ok(())
        } else {
            Err(invalid("unexpected or misbound execution response"))
        }
    }
    fn records_match(
        &self,
        principal: &str,
        id: &str,
        admission: Option<&edge_contracts::admission::Admission>,
        operation: Option<&edge_contracts::operation::Operation>,
    ) -> io::Result<bool> {
        if let Some(a) = admission
            && (a.schema_version != "edge-admission.v1"
                || a.plan.schema_version != "edge-plan.v2"
                || a.plan.authority_id != self.credential.authority_id
                || a.plan.request_id != id
                || a.principal != principal
                || a.request.request_id != id
                || a.request.authority_id != self.credential.authority_id
                || a.request.validate().is_err()
                || edge_contracts::digest(&a.request).map_err(io::Error::other)?
                    != a.plan.request_sha256)
        {
            return Ok(false);
        }
        if let Some(o) = operation {
            if o.principal != principal
                || o.plan.schema_version != "edge-plan.v2"
                || o.request_id != id
                || o.plan.request_id != id
                || o.plan.authority_id != self.credential.authority_id
                || o.request_sha256 != o.plan.request_sha256
            {
                return Ok(false);
            }
            if let Some(receipt) = &o.receipt {
                if receipt.validate().is_err() || receipt.state() != o.state {
                    return Ok(false);
                }
            } else if matches!(
                o.state,
                edge_contracts::operation::OperationState::Succeeded
                    | edge_contracts::operation::OperationState::Failed
            ) {
                return Ok(false);
            }
            if let Some(a) = admission
                && edge_contracts::digest(&a.plan).map_err(io::Error::other)?
                    != edge_contracts::digest(&o.plan).map_err(io::Error::other)?
            {
                return Ok(false);
            }
        }
        Ok(true)
    }
    pub fn close(&mut self) {
        self.closed = true;
    }
}
