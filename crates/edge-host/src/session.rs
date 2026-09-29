//! Trusted-owner software session. This API is not exposed by the preview socket server.
use crate::supervised::SupervisedSimulator;
use edge_contracts::{
    ControlRequest, Parameter, RequestInput, Result,
    preview::{Plan, PreviewDecision},
};
use edge_core::{
    execution::{Adapter, Journal, Operation, execute, reconcile},
    preview,
};
use edge_protocol::{
    adapter::SimulatorFault,
    local::{private_directory, private_metadata},
};
use edge_storage::{APPROVAL_TTL, SqliteJournal};
use serde::Serialize;
use std::{
    collections::BTreeMap,
    fs,
    os::unix::fs::{DirBuilderExt, MetadataExt},
    path::Path,
    time::{Duration, Instant},
};
use uuid::Uuid;

const PRINCIPAL: &str = "local-owner";
fn deadline() -> Instant {
    Instant::now() + Duration::from_secs(2)
}

#[derive(Debug, Clone, Serialize)]
pub struct SoftwarePreview {
    pub schema_version: &'static str,
    pub software_only: bool,
    pub execution_attempted: bool,
    pub plan: Plan,
    pub plan_sha256: String,
}
struct Pending {
    request: ControlRequest,
    preview: SoftwarePreview,
    created: Instant,
    approval: Option<String>,
}
pub struct SoftwareSession {
    adapter: SupervisedSimulator,
    journal: SqliteJournal,
    pending: Option<Pending>,
}

impl SoftwareSession {
    pub(crate) fn into_runtime(self) -> (SupervisedSimulator, SqliteJournal) {
        (self.adapter, self.journal)
    }
    pub fn open(directory: &Path, executable: &Path, fault: SimulatorFault) -> Result<Self> {
        match fs::DirBuilder::new().mode(0o700).create(directory) {
            Ok(()) => (),
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => (),
            Err(_) => return Err("cannot_create_session_directory".into()),
        }
        private_directory(directory).map_err(|_| "session_directory_must_be_private_and_owned")?;
        let database = directory.join("device.sqlite");
        for file in [&database, &directory.join("device.lock")] {
            match file.symlink_metadata() {
                Ok(_) => {
                    let meta = private_metadata(file).map_err(|_| "unsafe_device_storage")?;
                    if !meta.is_file() || meta.nlink() != 1 {
                        return Err("unsafe_device_storage".into());
                    }
                }
                Err(e) if e.kind() == std::io::ErrorKind::NotFound => (),
                Err(_) => return Err("device_storage_unavailable".into()),
            }
        }
        let mut adapter = SupervisedSimulator::spawn(executable, &database, fault)?;
        let context = adapter.observe(Instant::now() + Duration::from_secs(5))?;
        let journal = SqliteJournal::open(&directory.join("journal"), &context.authority_id)?;
        Ok(Self {
            adapter,
            journal,
            pending: None,
        })
    }
    pub fn authority_id(&self) -> &str {
        self.journal.authority_id()
    }
    pub fn worker_healthy(&self) -> bool {
        self.adapter.healthy()
    }
    pub fn worker_pid(&self) -> Option<u32> {
        self.adapter.process_id()
    }

    /// Preview from a fresh software observation. No operation is claimed or invoked.
    pub fn preview_volume(&mut self, percent: i64) -> Result<SoftwarePreview> {
        if !(0..=100).contains(&percent) {
            return Err("percent_must_be_0_to_100".into());
        }
        let limit = deadline();
        let context = self.adapter.observe(limit)?;
        if context.authority_id != self.authority_id() {
            return Err("device_identity_changed".into());
        }
        let request = ControlRequest {
            schema_version: "edge-control-request.v2".into(),
            request_id: Uuid::new_v4().to_string(),
            authority_id: self.authority_id().into(),
            budget_ms: 2000,
            input: RequestInput::Action {
                target: context
                    .endpoints
                    .first()
                    .ok_or("no_software_endpoint")?
                    .binding
                    .clone(),
                action: "audio.volume.set".into(),
                parameters: BTreeMap::from([(
                    "percent".into(),
                    Parameter::Integer { value: percent },
                )]),
            },
        };
        let PreviewDecision::Proposed {
            plan, plan_sha256, ..
        } = preview(&request, &context)?.decision
        else {
            return Err("software_preview_rejected".into());
        };
        let output = SoftwarePreview {
            schema_version: "edge-software-preview.v1",
            software_only: true,
            execution_attempted: false,
            plan,
            plan_sha256,
        };
        if let Some(pending) = &self.pending
            && let Some(token) = &pending.approval
        {
            self.journal.revoke(token, limit)?;
        }
        self.pending = Some(Pending {
            request,
            preview: output.clone(),
            created: Instant::now(),
            approval: None,
        });
        Ok(output)
    }
    /// Only the trusted owner console/test harness may call this, not an untrusted RPC.
    /// The exact preview fingerprint must be confirmed; callers cannot submit their own plan.
    pub fn approve(&mut self, confirmed_plan_sha256: &str) -> Result<()> {
        let pending = self.pending.as_ref().ok_or("preview_required")?;
        if pending.preview.plan_sha256 != confirmed_plan_sha256 {
            return Err("approval_fingerprint_mismatch".into());
        }
        if pending.created.elapsed() >= APPROVAL_TTL {
            return Err("preview_expired".into());
        }
        let limit = deadline();
        let current = preview(&pending.request, &self.adapter.observe(limit)?)?;
        let PreviewDecision::Proposed {
            plan, plan_sha256, ..
        } = current.decision
        else {
            return Err("repreview_required".into());
        };
        if plan_sha256 != pending.preview.plan_sha256 {
            return Err("repreview_required".into());
        }
        // Repeated confirmations never refresh an existing token's lifetime.
        if pending.approval.is_none() {
            let token = self.journal.approve(PRINCIPAL, &plan, limit)?;
            self.pending.as_mut().ok_or("preview_required")?.approval = Some(token);
        }
        Ok(())
    }
    pub fn execute(&mut self) -> Result<Operation> {
        let pending = self.pending.as_ref().ok_or("preview_required")?;
        let token = pending
            .approval
            .as_deref()
            .ok_or("explicit_approval_required")?;
        execute(
            &mut self.journal,
            &mut self.adapter,
            PRINCIPAL,
            &pending.request,
            Some(token),
            deadline(),
        )
    }
    pub fn status(&mut self, request_id: &str) -> Result<Option<Operation>> {
        self.journal.lookup(PRINCIPAL, request_id, deadline())
    }
    pub fn reconcile(&mut self, request_id: &str) -> Result<Operation> {
        reconcile(
            &mut self.journal,
            &mut self.adapter,
            PRINCIPAL,
            request_id,
            deadline(),
        )
    }
    pub fn cancel(&mut self, request_id: &str) -> Result<Option<Operation>> {
        let limit = deadline();
        let record = self.journal.lookup(PRINCIPAL, request_id, limit)?;
        if let Some(pending) = &self.pending
            && pending.request.request_id == request_id
        {
            if let Some(token) = &pending.approval {
                self.journal.revoke(token, limit)?;
            }
            self.pending = None;
            if record.is_none() {
                return Ok(None);
            } // only an in-memory preview existed; nothing dispatched
        }
        if record.is_none() {
            return Err("unknown_request".into());
        }
        self.journal.cancel(PRINCIPAL, request_id, limit).map(Some)
    }
    pub fn restart_adapter(&mut self) -> Result<()> {
        let limit = Instant::now() + Duration::from_secs(5);
        self.adapter.restart(SimulatorFault::None, limit)?;
        let context = self.adapter.observe(limit)?;
        if context.authority_id != self.authority_id() {
            return Err("device_identity_changed".into());
        }
        Ok(())
    }
    pub fn pending_request_id(&self) -> Option<&str> {
        self.pending.as_ref().map(|p| p.request.request_id.as_str())
    }
}
