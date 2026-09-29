//! Explicit software-execution service. Distinct from the saved-context preview protocol.
use edge_contracts::{
    Result, admission::Admission, fingerprint, identifier, operation::Operation, preview::Plan,
};
use serde::{Deserialize, Serialize};

pub const VERSION: &str = "edge-execution-service.v1";
pub const PROTOCOL: u32 = 1;
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Scope {
    Inspect,
    Control,
}

// Secrets and raw requests deliberately have no Debug representation.
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Credential {
    pub schema_version: String,
    pub authority_id: String,
    pub principal: String,
    pub token: String,
}
impl Credential {
    pub fn validate(&self) -> Result<()> {
        if self.schema_version != "edge-execution-credential.v1" {
            return Err("incompatible_credential".into());
        }
        identifier(&self.authority_id)?;
        identifier(&self.principal)?;
        fingerprint(&self.token)
    }
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(tag = "method", rename_all = "snake_case", deny_unknown_fields)]
pub enum Command {
    Hello {
        minimum_version: u32,
        maximum_version: u32,
    },
    Capabilities {},
    PreviewVolume {
        percent: i64,
        budget_ms: u32,
    },
    Submit {
        request_id: String,
    },
    Status {
        request_id: String,
    },
    Cancel {
        request_id: String,
    },
    Reconcile {
        request_id: String,
    },
    Enroll {
        principal: String,
        scope: Scope,
    },
    Peers {},
    Approve {
        principal: String,
        request_id: String,
        plan_sha256: String,
    },
    Inspect {
        principal: String,
        request_id: String,
    },
    Recover {
        principal: String,
        request_id: String,
    },
    Revoke {
        principal: String,
    },
    RestartAdapter {},
}
impl Command {
    pub fn validate(&self) -> Result<()> {
        match self {
            Self::PreviewVolume { percent, budget_ms } => {
                if !(0..=100).contains(percent) || !(1..=5000).contains(budget_ms) {
                    return Err("invalid_parameter".into());
                }
            }
            Self::Submit { request_id }
            | Self::Status { request_id }
            | Self::Cancel { request_id }
            | Self::Reconcile { request_id } => identifier(request_id)?,
            Self::Approve {
                principal,
                request_id,
                plan_sha256,
            } => {
                identifier(principal)?;
                identifier(request_id)?;
                fingerprint(plan_sha256)?;
            }
            Self::Inspect {
                principal,
                request_id,
            }
            | Self::Recover {
                principal,
                request_id,
            } => {
                identifier(principal)?;
                identifier(request_id)?;
            }
            Self::Enroll { principal, .. } | Self::Revoke { principal } => {
                identifier(principal)?;
                if principal == "owner" {
                    return Err("reserved_principal".into());
                }
            }
            _ => (),
        }
        Ok(())
    }
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub schema_version: String,
    pub call_id: String,
    pub credential: String,
    pub command: Command,
}
impl Request {
    pub fn validate(&self) -> Result<()> {
        if self.schema_version != VERSION {
            return Err("incompatible_version".into());
        }
        identifier(&self.call_id)?;
        fingerprint(&self.credential)?;
        self.command.validate()
    }
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Peer {
    pub principal: String,
    pub scope: Scope,
    pub revoked: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Progress {
    Persisting,
    Queued,
    Running,
    CancelledBeforeDispatch,
    ExpiredBeforeDispatch,
    Completed,
    NeedsInspection,
    NotInMemory,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Cancellation {
    PreventedDispatch,
    PossiblyDispatched,
    AlreadyFinished,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ErrorCode {
    Unauthenticated,
    Forbidden,
    InvalidRequest,
    IncompatibleVersion,
    NegotiationRequired,
    Overloaded,
    ApprovalRequired,
    RepreviewRequired,
    NotFound,
    Conflict,
    Capacity,
    PersistenceUncertain,
    Rejected,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Reply {
    Hello {
        protocol_version: u32,
        authority_id: String,
        principal: String,
        software_only: bool,
    },
    Capabilities {
        software_only: bool,
        action: String,
        endpoint: String,
        scope: Option<Scope>,
    },
    Preview {
        request_id: String,
        plan: Plan,
        plan_sha256: String,
    },
    Submission {
        request_id: String,
        progress: Progress,
        admission_durable: bool,
    },
    Status {
        request_id: String,
        progress: Progress,
        admission: Option<Box<Admission>>,
        operation: Option<Box<Operation>>,
    },
    Cancelled {
        request_id: String,
        disposition: Cancellation,
    },
    Reconciled {
        operation: Box<Operation>,
    },
    Enrolled {
        credential: Credential,
    },
    Peers {
        peers: Vec<Peer>,
    },
    Confirmed {
        request_id: String,
        plan_sha256: String,
    },
    Revoked {
        principal: String,
    },
    AdapterRestarted {},
    Error {
        code: ErrorCode,
    },
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Response {
    pub schema_version: String,
    pub call_id: String,
    pub reply: Reply,
}
impl Response {
    pub fn new(call_id: String, reply: Reply) -> Self {
        Self {
            schema_version: VERSION.into(),
            call_id,
            reply,
        }
    }
}
