//! Bounded installed-worker transport. Process supervision is not an OS sandbox.
use edge_contracts::{
    Result,
    actions::{Endpoint, Receipt, Request},
};
use edge_core::actions::Adapter;
use edge_protocol::{action_adapter as wire, local::DeadlineStream, read_frame, write_frame};
use std::{
    os::{fd::OwnedFd, unix::net::UnixStream},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Mutex,
    time::{Duration, Instant},
};

pub struct ProcessAdapter {
    inner: Mutex<Worker>,
}
struct Worker {
    executable: PathBuf,
    args: Vec<String>,
    child: Option<Child>,
    channel: Option<DeadlineStream>,
    sequence: u64,
}
impl Worker {
    fn retire(&mut self) {
        self.channel = None;
        if let Some(child) = self.child.as_mut() {
            let _ = child.kill();
        }
    }
    fn start(&mut self, deadline: Instant) -> Result<()> {
        if let Some(child) = self.child.as_mut() {
            loop {
                edge_core::execution::check_deadline(deadline)?;
                if child
                    .try_wait()
                    .map_err(|_| "worker_reap_failed")?
                    .is_some()
                {
                    break;
                }
                std::thread::sleep(Duration::from_millis(1));
            }
            self.child = None;
        }
        let (host, child) = UnixStream::pair().map_err(|_| "worker_channel_failed")?;
        let input: OwnedFd = child
            .try_clone()
            .map_err(|_| "worker_channel_failed")?
            .into();
        let output: OwnedFd = child.into();
        self.child = Some(
            Command::new(&self.executable)
                .args(&self.args)
                .arg("--parent-pid")
                .arg(std::process::id().to_string())
                .env_clear()
                .stdin(Stdio::from(input))
                .stdout(Stdio::from(output))
                .stderr(Stdio::null())
                .spawn()
                .map_err(|_| "worker_spawn_failed")?,
        );
        self.channel = Some(DeadlineStream {
            stream: host,
            deadline,
        });
        Ok(())
    }
    fn call(&mut self, command: wire::Command, deadline: Instant) -> Result<wire::Reply> {
        edge_core::execution::check_deadline(deadline)?;
        // Restart only for observation/reconciliation, never to replay invocation.
        if self.channel.is_none() {
            if matches!(command, wire::Command::Invoke { .. }) {
                return Err("worker_unavailable".into());
            }
            self.start(deadline)?;
        }
        self.sequence = self
            .sequence
            .checked_add(1)
            .ok_or("worker_sequence_exhausted")?;
        let result = (|| {
            let channel = self.channel.as_mut().ok_or("worker_unavailable")?;
            channel.deadline = deadline;
            write_frame(
                channel,
                &wire::Message {
                    schema_version: wire::VERSION.into(),
                    sequence: self.sequence,
                    command,
                },
            )
            .map_err(|_| "worker_transport_failed")?;
            let response: wire::Response = read_frame(channel)
                .map_err(|_| "worker_transport_failed")?
                .ok_or("worker_disconnected")?;
            if response.schema_version != wire::VERSION || response.sequence != self.sequence {
                return Err("worker_identity_mismatch".into());
            }
            edge_core::execution::check_deadline(deadline)?;
            Ok(response.reply)
        })();
        if result.is_err() {
            self.retire();
        }
        result
    }
}
impl ProcessAdapter {
    /// Executable and arguments come only from trusted installation configuration.
    pub fn spawn(executable: &Path, args: Vec<String>) -> Result<Self> {
        if !executable.is_absolute() {
            return Err("worker_path_must_be_absolute".into());
        }
        let adapter = Self {
            inner: Mutex::new(Worker {
                executable: executable.into(),
                args,
                child: None,
                channel: None,
                sequence: 0,
            }),
        };
        adapter.describe()?;
        Ok(adapter)
    }
    fn receipt(&self, command: wire::Command, deadline: Instant) -> Result<Receipt> {
        let mut worker = self.inner.lock().map_err(|_| "worker_lock_poisoned")?;
        match worker.call(command, deadline)? {
            wire::Reply::Receipt { receipt } => Ok(receipt),
            _ => {
                worker.retire();
                Err("invalid_worker_receipt".into())
            }
        }
    }
}
fn budget(deadline: Instant) -> Result<u32> {
    edge_core::execution::check_deadline(deadline)?;
    let ms = deadline
        .saturating_duration_since(Instant::now())
        .as_millis()
        .min(5000) as u32;
    if ms == 0 {
        return Err("deadline_expired".into());
    }
    Ok(ms)
}
impl Adapter for ProcessAdapter {
    fn describe(&self) -> Result<Endpoint> {
        self.describe_until(Instant::now() + Duration::from_secs(2))
    }
    fn describe_until(&self, deadline: Instant) -> Result<Endpoint> {
        let mut worker = self.inner.lock().map_err(|_| "worker_lock_poisoned")?;
        match worker.call(wire::Command::Describe {}, deadline)? {
            wire::Reply::Description { endpoint } => {
                endpoint.validate()?;
                Ok(endpoint)
            }
            _ => {
                worker.retire();
                Err("invalid_worker_description".into())
            }
        }
    }
    fn invoke(
        &mut self,
        principal: &str,
        operation_id: &str,
        request: &Request,
        deadline: Instant,
    ) -> Result<Receipt> {
        self.receipt(
            wire::Command::Invoke {
                principal: principal.into(),
                operation_id: operation_id.into(),
                request: request.clone(),
                budget_ms: budget(deadline)?,
            },
            deadline,
        )
    }
    fn reconcile(
        &mut self,
        principal: &str,
        operation_id: &str,
        request: &Request,
        deadline: Instant,
    ) -> Result<Receipt> {
        self.receipt(
            wire::Command::Reconcile {
                principal: principal.into(),
                operation_id: operation_id.into(),
                request: request.clone(),
                budget_ms: budget(deadline)?,
            },
            deadline,
        )
    }
}
impl Drop for Worker {
    fn drop(&mut self) {
        self.retire();
        let until = Instant::now() + Duration::from_millis(100);
        while let Some(child) = self.child.as_mut() {
            if child.try_wait().is_ok_and(|status| status.is_some()) {
                self.child = None;
                break;
            }
            if Instant::now() >= until {
                break;
            }
            std::thread::sleep(Duration::from_millis(1));
        }
        if let Some(mut child) = self.child.take() {
            // One reaper for this retired worker; no replacement is started before reaping.
            let _ = std::thread::Builder::new()
                .name("action-worker-reaper".into())
                .spawn(move || {
                    let _ = child.wait();
                });
        }
    }
}
