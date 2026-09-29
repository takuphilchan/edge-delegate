use edge_contracts::{
    ControlRequest, digest,
    preview::{Preview, PreviewContext, PreviewDecision},
};
use edge_protocol::{
    local::{DeadlineStream, LocalCredential, private_metadata, same_user},
    read_frame,
    service::{
        Command, ErrorCode, PROTOCOL_VERSION, Reply, SERVICE_VERSION, ServiceMode, ServiceRequest,
        ServiceResponse,
    },
    write_frame,
};
use socket2::{Domain, SockAddr, Socket, Type};
use std::{
    io,
    os::unix::{fs::FileTypeExt, net::UnixStream},
    path::{Path, PathBuf},
    time::{Duration, Instant},
};

/// One credential is scoped to one host lifetime and the local OS owner. No automatic retries.
pub struct LocalClient {
    directory: PathBuf,
    credential: LocalCredential,
    closed: bool,
}
fn invalid(message: &str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message)
}

impl LocalClient {
    pub fn connect(directory: &Path) -> io::Result<Self> {
        let client = Self {
            directory: directory.into(),
            credential: LocalCredential::load(directory)?,
            closed: false,
        };
        client.handshake()?;
        Ok(client)
    }
    fn exchange(
        &self,
        stream: &mut DeadlineStream,
        call_id: &str,
        command: Command,
    ) -> io::Result<Reply> {
        write_frame(
            stream,
            &ServiceRequest {
                schema_version: SERVICE_VERSION.into(),
                call_id: call_id.into(),
                credential: self.credential.token.clone(),
                command,
            },
        )?;
        let response: ServiceResponse =
            read_frame(stream)?.ok_or_else(|| invalid("host closed without a response"))?;
        if response.schema_version != SERVICE_VERSION {
            return Err(invalid("incompatible response schema"));
        }
        if matches!(
            response.reply,
            Reply::Error {
                code: ErrorCode::Overloaded
            }
        ) {
            return Err(io::Error::new(
                io::ErrorKind::WouldBlock,
                "preview host overloaded",
            ));
        }
        if response.call_id != call_id {
            return Err(invalid("response call identity mismatch"));
        }
        match response.reply {
            Reply::Error { code } => {
                Err(io::Error::other(format!("preview service error: {code:?}")))
            }
            reply => Ok(reply),
        }
    }
    fn handshake(&self) -> io::Result<DeadlineStream> {
        if self.closed {
            return Err(invalid("client is closed"));
        }
        let deadline = Instant::now() + Duration::from_secs(2);
        edge_protocol::local::private_directory(&self.directory)?;
        let path = self.directory.join("preview.sock");
        if !private_metadata(&path)?.file_type().is_socket() {
            return Err(invalid("expected a local socket"));
        }
        let socket = Socket::new(Domain::UNIX, Type::STREAM, None)?;
        socket.connect_timeout(
            &SockAddr::unix(&path)?,
            deadline.saturating_duration_since(Instant::now()),
        )?;
        let descriptor: std::os::fd::OwnedFd = socket.into();
        let stream = UnixStream::from(descriptor);
        same_user(&stream)?;
        let mut stream = DeadlineStream { stream, deadline };
        let reply = self.exchange(
            &mut stream,
            "hello",
            Command::Hello {
                minimum_version: PROTOCOL_VERSION,
                maximum_version: PROTOCOL_VERSION,
            },
        )?;
        match reply {
            Reply::Hello {
                protocol_version,
                authority_id,
                principal,
                mode,
            } if protocol_version == PROTOCOL_VERSION
                && authority_id == self.credential.authority_id
                && principal == self.credential.principal
                && mode == ServiceMode::SavedContextPreviewOnly =>
            {
                Ok(stream)
            }
            _ => Err(invalid("host identity, version or service mode mismatch")),
        }
    }
    pub fn capabilities(&self) -> io::Result<PreviewContext> {
        let mut stream = self.handshake()?;
        match self.exchange(&mut stream, "capabilities", Command::Capabilities {})? {
            Reply::Capabilities { context }
                if context.authority_id == self.credential.authority_id =>
            {
                context
                    .validate()
                    .map_err(|_| invalid("invalid host catalog"))?;
                Ok(context)
            }
            _ => Err(invalid("expected capabilities for selected authority")),
        }
    }
    pub fn preview(&self, request: &ControlRequest) -> io::Result<Preview> {
        request
            .validate()
            .map_err(|_| invalid("invalid control request"))?;
        if request.authority_id != self.credential.authority_id {
            return Err(invalid("request authority differs from selected host"));
        }
        let mut stream = self.handshake()?;
        stream.deadline = stream
            .deadline
            .min(Instant::now() + Duration::from_millis(request.budget_ms.into()));
        match self.exchange(
            &mut stream,
            "preview",
            Command::Preview {
                request: request.clone(),
            },
        )? {
            Reply::Preview { preview }
                if preview.schema_version == "edge-control-preview.v2"
                    && !preview.execution_attempted
                    && preview.context_kind == "saved_untrusted_for_execution" =>
            {
                if let PreviewDecision::Proposed {
                    plan, plan_sha256, ..
                } = &preview.decision
                    && (plan.schema_version != "edge-plan.v2"
                        || plan.request_id != request.request_id
                        || plan.authority_id != request.authority_id
                        || digest(request).map_err(io::Error::other)? != plan.request_sha256
                        || digest(plan).map_err(io::Error::other)? != *plan_sha256)
                {
                    return Err(invalid("preview plan binding mismatch"));
                }
                Ok(preview)
            }
            _ => Err(invalid("expected non-executing saved-context preview")),
        }
    }
    pub fn close(&mut self) {
        self.closed = true;
    }
}
