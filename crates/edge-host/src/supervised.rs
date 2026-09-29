//! Linux installed-adapter process supervision. Not an OS security sandbox.
use edge_contracts::Result;
use edge_core::{
    PlanStep, PreviewContext,
    cancellation::DispatchControl,
    execution::{Adapter, Receipt, check_deadline},
};
use edge_protocol::{
    adapter::{
        ADAPTER_VERSION, AdapterCommand, AdapterReply, AdapterRequest, AdapterResponse,
        SimulatorFault,
    },
    local::DeadlineStream,
    read_frame, write_frame,
};
use std::{
    io::{self, Read, Write},
    net::Shutdown,
    os::{fd::OwnedFd, unix::net::UnixStream},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    thread,
    time::{Duration, Instant},
};

pub struct SupervisedSimulator {
    executable: PathBuf,
    database: PathBuf,
    child: Option<Child>,
    channel: Option<DeadlineStream>,
    sequence: u32,
    cancellation: Option<DispatchControl>,
}
impl SupervisedSimulator {
    /// Paths are supplied by installed host setup, never by a planner or client request.
    pub fn spawn(executable: &Path, database: &Path, fault: SimulatorFault) -> Result<Self> {
        let mut adapter = Self {
            executable: executable.into(),
            database: database.into(),
            child: None,
            channel: None,
            sequence: 0,
            cancellation: None,
        };
        adapter.start(fault)?;
        Ok(adapter)
    }
    fn start(&mut self, fault: SimulatorFault) -> Result<()> {
        let (host, worker) = UnixStream::pair().map_err(|_| "adapter_channel_failed")?;
        let input: OwnedFd = worker
            .try_clone()
            .map_err(|_| "adapter_channel_failed")?
            .into();
        let output: OwnedFd = worker.into();
        let child = Command::new(&self.executable)
            .env_clear()
            .arg("--database")
            .arg(&self.database)
            .arg("--fault")
            .arg(fault.as_str())
            .arg("--parent-pid")
            .arg(std::process::id().to_string())
            .stdin(Stdio::from(input))
            .stdout(Stdio::from(output))
            .stderr(Stdio::null())
            .spawn()
            .map_err(|_| "adapter_spawn_failed")?;
        self.child = Some(child);
        self.channel = Some(DeadlineStream {
            stream: host,
            deadline: Instant::now(),
        });
        Ok(())
    }
    pub fn healthy(&self) -> bool {
        self.channel.is_some()
    }
    pub fn process_id(&self) -> Option<u32> {
        self.child.as_ref().map(Child::id)
    }
    pub fn set_cancellation(&mut self, control: Option<DispatchControl>) {
        self.cancellation = control;
    }

    fn retire(&mut self) {
        if let Some(channel) = self.channel.take() {
            let _ = channel.stream.shutdown(Shutdown::Both);
        }
        if let Some(child) = self.child.as_mut() {
            let _ = child.kill();
        }
    }
    /// Kill/reap first. Restart never reissues an interrupted operation.
    pub fn restart(&mut self, fault: SimulatorFault, deadline: Instant) -> Result<()> {
        self.retire();
        while let Some(child) = self.child.as_mut() {
            check_deadline(deadline)?;
            match child.try_wait().map_err(|_| "adapter_reap_failed")? {
                Some(_) => self.child = None,
                None => thread::sleep(Duration::from_millis(2)),
            }
        }
        check_deadline(deadline)?;
        self.start(fault)
    }
    fn call(&mut self, command: AdapterCommand, deadline: Instant) -> Result<AdapterReply> {
        check_deadline(deadline)?;
        self.sequence = self
            .sequence
            .checked_add(1)
            .ok_or("adapter_sequence_exhausted")?;
        let remaining = deadline.saturating_duration_since(Instant::now());
        let budget_ms =
            u32::try_from(remaining.as_millis().min(5000)).map_err(|_| "invalid_adapter_budget")?;
        if budget_ms == 0 {
            return Err("deadline_expired".into());
        }
        let request = AdapterRequest {
            schema_version: ADAPTER_VERSION.into(),
            call_id: self.sequence,
            budget_ms,
            command,
        };
        request.validate()?;
        let result = (|| {
            let channel = self.channel.as_mut().ok_or("adapter_restart_required")?;
            channel.deadline = deadline;
            let mut channel = Interruptible {
                channel,
                control: self.cancellation.as_ref(),
                deadline,
            };
            write_frame(&mut channel, &request).map_err(|_| "adapter_channel_failed")?;
            let response: AdapterResponse = read_frame(&mut channel)
                .map_err(|_| "adapter_channel_failed")?
                .ok_or("adapter_disconnected")?;
            check_deadline(deadline)?;
            if response.schema_version != ADAPTER_VERSION || response.call_id != request.call_id {
                return Err("adapter_response_mismatch".into());
            }
            match &response.reply {
                AdapterReply::Context { context } => context.validate()?,
                AdapterReply::Receipt { receipt } => receipt.validate()?,
                AdapterReply::Unavailable {} => (),
            }
            Ok(response.reply)
        })();
        if result.is_err() {
            self.retire();
        }
        result
    }
    fn unexpected<T>(&mut self) -> Result<T> {
        self.retire();
        Err("unexpected_adapter_response".into())
    }
}

/// Poll bounded I/O without renewing the original deadline. Cancellation closes the
/// channel through retire(); it never converts a possible effect into confirmed failure.
struct Interruptible<'a> {
    channel: &'a mut DeadlineStream,
    control: Option<&'a DispatchControl>,
    deadline: Instant,
}
impl Interruptible<'_> {
    fn prepare(&mut self) -> io::Result<()> {
        if self.control.is_some_and(DispatchControl::cancelled) {
            return Err(io::Error::other("adapter_cancelled"));
        }
        if Instant::now() >= self.deadline {
            return Err(io::Error::new(io::ErrorKind::TimedOut, "adapter_deadline"));
        }
        self.channel.deadline = self
            .deadline
            .min(Instant::now() + Duration::from_millis(25));
        Ok(())
    }
}
impl Read for Interruptible<'_> {
    fn read(&mut self, bytes: &mut [u8]) -> io::Result<usize> {
        loop {
            self.prepare()?;
            match self.channel.read(bytes) {
                Err(e)
                    if matches!(
                        e.kind(),
                        io::ErrorKind::WouldBlock
                            | io::ErrorKind::TimedOut
                            | io::ErrorKind::Interrupted
                    ) =>
                {
                    continue;
                }
                result => return result,
            }
        }
    }
}
impl Write for Interruptible<'_> {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        loop {
            self.prepare()?;
            match self.channel.write(bytes) {
                Err(e)
                    if matches!(
                        e.kind(),
                        io::ErrorKind::WouldBlock
                            | io::ErrorKind::TimedOut
                            | io::ErrorKind::Interrupted
                    ) =>
                {
                    continue;
                }
                result => return result,
            }
        }
    }
    fn flush(&mut self) -> io::Result<()> {
        self.channel.flush()
    }
}
impl Adapter for SupervisedSimulator {
    fn observe(&mut self, deadline: Instant) -> Result<PreviewContext> {
        match self.call(AdapterCommand::Observe {}, deadline)? {
            AdapterReply::Context { context } => Ok(context),
            AdapterReply::Unavailable {} => Err("adapter_observation_unavailable".into()),
            _ => self.unexpected(),
        }
    }
    fn invoke(
        &mut self,
        operation_id: &str,
        step: &PlanStep,
        deadline: Instant,
    ) -> Result<Receipt> {
        match self.call(
            AdapterCommand::Invoke {
                operation_id: operation_id.into(),
                step: step.clone(),
            },
            deadline,
        )? {
            AdapterReply::Receipt { receipt } => Ok(receipt),
            AdapterReply::Unavailable {} => Err("adapter_outcome_unavailable".into()),
            _ => self.unexpected(),
        }
    }
    fn reconcile(&mut self, operation_id: &str, deadline: Instant) -> Result<Receipt> {
        match self.call(
            AdapterCommand::Reconcile {
                operation_id: operation_id.into(),
            },
            deadline,
        )? {
            AdapterReply::Receipt { receipt } => Ok(receipt),
            AdapterReply::Unavailable {} => Err("adapter_receipt_unavailable".into()),
            _ => self.unexpected(),
        }
    }
}
impl Drop for SupervisedSimulator {
    fn drop(&mut self) {
        self.retire();
        let limit = Instant::now() + Duration::from_millis(100);
        while let Some(child) = self.child.as_mut() {
            if child.try_wait().is_ok_and(|status| status.is_some()) {
                self.child = None;
                break;
            }
            if Instant::now() >= limit {
                break;
            }
            thread::sleep(Duration::from_millis(2));
        }
        if let Some(mut child) = self.child.take() {
            // Reap without making session teardown wait on an uninterruptible kernel I/O.
            // One reaper per retired session; no restart is allowed before a previous child exits.
            let _ = thread::Builder::new()
                .name("adapter-reaper".into())
                .spawn(move || {
                    let _ = child.wait();
                });
        }
    }
}
