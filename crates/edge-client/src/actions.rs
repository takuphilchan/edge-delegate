//! Public v2 local client. No runtime imports, implicit consent or submission retries.
use edge_contracts::actions::{Record, Request};
pub use edge_protocol::execution_v2::{Command, Credential, Permission, Reply};
use edge_protocol::{
    execution_v2 as wire,
    local::{DeadlineStream, private_directory, private_file, private_metadata, same_user},
    read_frame, write_frame,
};
use socket2::{Domain, SockAddr, Socket, Type};
use std::{
    io,
    os::unix::{
        fs::{FileTypeExt, OpenOptionsExt},
        net::UnixStream,
    },
    path::{Path, PathBuf},
    time::{Duration, Instant},
};
pub struct GatewayClient {
    directory: PathBuf,
    credential: Credential,
    closed: bool,
}

fn invalid(e: impl ToString) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, e.to_string())
}
pub fn save_credential(path: &Path, credential: &Credential) -> io::Result<()> {
    use std::io::Write;
    credential.validate().map_err(invalid)?;
    let parent = path
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    private_directory(parent)?;
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)?;
    serde_json::to_writer(&mut file, credential)?;
    file.flush()?;
    file.sync_all()?;
    std::fs::File::open(parent)?.sync_all()
}
impl GatewayClient {
    pub fn connect(directory: &Path, credential_file: &Path) -> io::Result<Self> {
        Self::with_credential(
            directory,
            edge_contracts::parse_json(&private_file(credential_file)?).map_err(invalid)?,
        )
    }
    pub fn with_credential(directory: &Path, credential: Credential) -> io::Result<Self> {
        credential.validate().map_err(invalid)?;
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
        let request = wire::Request {
            schema_version: wire::VERSION.into(),
            call_id: id.into(),
            credential: self.credential.token.clone(),
            command,
        };
        request.validate().map_err(invalid)?;
        write_frame(stream, &request)?;
        let response: wire::Response = read_frame(stream)?
            .ok_or_else(|| invalid("service disconnected; inspect the original request ID"))?;
        if response.schema_version == wire::VERSION
            && response.call_id == "admission"
            && matches!(&response.reply, Reply::Error {code} if code=="overloaded")
        {
            return Err(io::Error::new(
                io::ErrorKind::WouldBlock,
                "service_connection_limit",
            ));
        }
        if response.schema_version != wire::VERSION || response.call_id != id {
            return Err(invalid("response_binding_mismatch"));
        }
        if let Reply::Error { code } = response.reply {
            edge_contracts::identifier(&code).map_err(invalid)?;
            return Err(io::Error::other(code));
        }
        Ok(response.reply)
    }
    fn handshake(&self) -> io::Result<DeadlineStream> {
        if self.closed {
            return Err(invalid("client_closed"));
        }
        private_directory(&self.directory)?;
        let path = self.directory.join("execution-v2.sock");
        if !private_metadata(&path)?.file_type().is_socket() {
            return Err(invalid("expected_v2_socket"));
        }
        let socket = Socket::new(Domain::UNIX, Type::STREAM, None)?;
        socket.connect_timeout(&SockAddr::unix(&path)?, Duration::from_secs(2))?;
        let fd: std::os::fd::OwnedFd = socket.into();
        let stream = UnixStream::from(fd);
        same_user(&stream)?;
        let mut stream = DeadlineStream {
            stream,
            deadline: Instant::now() + Duration::from_secs(2),
        };
        match self.exchange(
            &mut stream,
            "hello",
            Command::Hello {
                minimum_version: 2,
                maximum_version: 2,
            },
        )? {
            Reply::Hello {
                protocol_version: 2,
                authority_id,
                principal,
            } if authority_id == self.credential.authority_id
                && principal == self.credential.principal =>
            {
                Ok(stream)
            }
            _ => Err(invalid("host_identity_mismatch")),
        }
    }
    /// Every call re-authenticates. Transport failure is not cancellation or proof of no effect.
    /// Execute/status/cancel/reconcile retain the caller's identity; nothing retries automatically.
    pub fn call(&self, command: Command) -> io::Result<Reply> {
        let mut stream = self.handshake()?;
        stream.deadline = Instant::now() + Duration::from_secs(10);
        let reply = self.exchange(&mut stream, "command", command.clone())?;
        self.validate_reply(&command, &reply)?;
        Ok(reply)
    }
    fn validate_reply(&self, command: &Command, reply: &Reply) -> io::Result<()> {
        let valid = match (command, reply) {
            (Command::Capabilities { limit, .. }, Reply::Capabilities { items, next }) => {
                items.len() <= *limit as usize
                    && next.as_ref().is_none_or(|v| v.parse::<usize>().is_ok())
                    && items.iter().all(|c| {
                        c.target.authority_id == self.credential.authority_id
                            && c.target.validate().is_ok()
                            && c.definition.validate().is_ok()
                    })
            }
            (Command::Preview { request }, Reply::Record { record }) => {
                self.valid_record(record, &self.credential.principal, &request.request_id)
                    && edge_contracts::digest(request).map_err(invalid)?
                        == record.plan.request_sha256
            }
            (
                Command::Execute {
                    request_id,
                    plan_sha256,
                },
                Reply::Record { record },
            ) => {
                self.valid_record(record, &self.credential.principal, request_id)
                    && edge_contracts::digest(&record.plan).map_err(invalid)? == *plan_sha256
            }
            (
                Command::Status { request_id }
                | Command::Cancel { request_id }
                | Command::Reconcile { request_id },
                Reply::Record { record },
            ) => self.valid_record(record, &self.credential.principal, request_id),
            (
                Command::Inspect {
                    principal,
                    request_id,
                },
                Reply::Record { record },
            ) => self.valid_record(record, principal, request_id),
            (
                Command::Approve {
                    request_id,
                    plan_sha256,
                    ..
                },
                Reply::Approved {
                    request_id: actual,
                    plan_sha256: hash,
                },
            ) => request_id == actual && plan_sha256 == hash,
            (Command::Enroll { principal, .. }, Reply::Enrolled { credential }) => {
                credential.validate().is_ok()
                    && credential.principal == *principal
                    && credential.authority_id == self.credential.authority_id
            }
            (Command::Revoke { principal }, Reply::Revoked { principal: actual }) => {
                principal == actual
            }
            (Command::Events { after, limit }, Reply::Events { items }) => {
                let mut sequence = *after;
                items.len() <= *limit as usize
                    && items.iter().all(|e| {
                        let valid = e.principal == self.credential.principal
                            && e.sequence > sequence
                            && e.sequence <= edge_contracts::MAX_SAFE_INTEGER as u64
                            && edge_contracts::identifier(&e.kind).is_ok()
                            && e.request_id
                                .as_ref()
                                .is_none_or(|id| edge_contracts::identifier(id).is_ok());
                        sequence = e.sequence;
                        valid
                    })
            }
            _ => false,
        };
        if valid {
            Ok(())
        } else {
            Err(invalid("invalid_v2_response"))
        }
    }
    fn valid_record(&self, record: &Record, principal: &str, id: &str) -> bool {
        record.validate().is_ok()
            && record.principal == principal
            && record.plan.request.request_id == id
            && record.plan.request.target.authority_id == self.credential.authority_id
    }
    pub fn preview(&self, request: Request) -> io::Result<Record> {
        self.record(Command::Preview { request })
    }
    pub fn capabilities(
        &self,
        after: Option<String>,
        limit: u32,
    ) -> io::Result<(Vec<edge_contracts::actions::Capability>, Option<String>)> {
        match self.call(Command::Capabilities { after, limit })? {
            Reply::Capabilities { items, next } => Ok((items, next)),
            _ => Err(invalid("expected_capabilities")),
        }
    }
    pub fn events(
        &self,
        after: u64,
        limit: u32,
    ) -> io::Result<Vec<edge_contracts::actions::Event>> {
        match self.call(Command::Events { after, limit })? {
            Reply::Events { items } => Ok(items),
            _ => Err(invalid("expected_events")),
        }
    }
    /// Requires an owner credential; ordinary application credentials cannot approve.
    pub fn approve(&self, principal: &str, request_id: &str, plan_sha256: &str) -> io::Result<()> {
        self.call(Command::Approve {
            principal: principal.into(),
            request_id: request_id.into(),
            plan_sha256: plan_sha256.into(),
        })?;
        Ok(())
    }
    pub fn execute(&self, request_id: &str, plan_sha256: &str) -> io::Result<Record> {
        self.record(Command::Execute {
            request_id: request_id.into(),
            plan_sha256: plan_sha256.into(),
        })
    }
    pub fn status(&self, request_id: &str) -> io::Result<Record> {
        self.record(Command::Status {
            request_id: request_id.into(),
        })
    }
    pub fn cancel(&self, request_id: &str) -> io::Result<Record> {
        self.record(Command::Cancel {
            request_id: request_id.into(),
        })
    }
    pub fn reconcile(&self, request_id: &str) -> io::Result<Record> {
        self.record(Command::Reconcile {
            request_id: request_id.into(),
        })
    }
    fn record(&self, command: Command) -> io::Result<Record> {
        match self.call(command)? {
            Reply::Record { record } => Ok(*record),
            _ => Err(invalid("expected_record")),
        }
    }
    pub fn close(&mut self) {
        self.closed = true;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn event_replies_reject_cross_principal_duplicates_and_bad_order() {
        let client = GatewayClient {
            directory: "unused".into(),
            credential: Credential {
                schema_version: "edge-action-credential.v2".into(),
                authority_id: "host".into(),
                principal: "alice".into(),
                token: "a".repeat(64),
            },
            closed: false,
        };
        let event = edge_contracts::actions::Event {
            sequence: 1,
            principal: "alice".into(),
            request_id: Some("request".into()),
            kind: "accepted".into(),
        };
        let command = Command::Events { after: 0, limit: 2 };
        assert!(
            client
                .validate_reply(
                    &command,
                    &Reply::Events {
                        items: vec![event.clone()]
                    }
                )
                .is_ok()
        );
        assert!(
            client
                .validate_reply(
                    &command,
                    &Reply::Events {
                        items: vec![event.clone(), event.clone()]
                    }
                )
                .is_err()
        );
        let mut wrong = event;
        wrong.principal = "bob".into();
        assert!(
            client
                .validate_reply(&command, &Reply::Events { items: vec![wrong] })
                .is_err()
        );
    }
}
