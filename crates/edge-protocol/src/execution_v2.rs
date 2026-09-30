//! Generic execution service contract, isolated from v1 credentials and scopes.
//! Validation checks shape, NOT authentication or permission. Hosts must resolve
//! credentials and enforce roles before interpreting a command.
use edge_contracts::actions::Request as ActionRequest;
use edge_contracts::{Result, fingerprint, identifier, parse_json};
use serde::{Deserialize, Serialize};

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
        if self.schema_version != "edge-action-credential.v2" {
            return Err("incompatible_credential".into());
        }
        identifier(&self.authority_id)?;
        identifier(&self.principal)?;
        fingerprint(&self.token)
    }
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Permission {
    pub endpoint: String,
    pub action: String,
}

pub const VERSION: &str = "edge-execution-service.v2";
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub schema_version: String,
    pub call_id: String,
    pub credential: String,
    pub command: Command,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(tag = "method", rename_all = "snake_case", deny_unknown_fields)]
pub enum Command {
    Hello {
        minimum_version: u32,
        maximum_version: u32,
    },
    Capabilities {
        after: Option<String>,
        limit: u32,
    },
    Preview {
        request: ActionRequest,
    },
    Execute {
        request_id: String,
        plan_sha256: String,
    },
    Status {
        request_id: String,
    },
    Events {
        after: u64,
        limit: u32,
    },
    Cancel {
        request_id: String,
    },
    Reconcile {
        request_id: String,
    },
    /// Owner-only. A client supplying this valid shape still has no authority.
    Approve {
        principal: String,
        request_id: String,
        plan_sha256: String,
    },
    Enroll {
        principal: String,
        permissions: Vec<Permission>,
    },
    Revoke {
        principal: String,
    },
    Inspect {
        principal: String,
        request_id: String,
    },
}
impl Request {
    pub fn parse(bytes: &[u8]) -> Result<Self> {
        let request: Self = parse_json(bytes)?;
        request.validate()?;
        Ok(request)
    }
    pub fn validate(&self) -> Result<()> {
        if self.schema_version != VERSION {
            return Err("incompatible_execution_service".into());
        }
        identifier(&self.call_id)?;
        fingerprint(&self.credential)?;
        match &self.command {
            Command::Enroll {
                principal,
                permissions,
            } => {
                identifier(principal)?;
                if principal == "owner" || permissions.len() > 128 {
                    return Err("invalid_enrollment".into());
                }
                let mut pairs = std::collections::BTreeSet::new();
                for p in permissions {
                    identifier(&p.endpoint)?;
                    identifier(&p.action)?;
                    if !pairs.insert((&p.endpoint, &p.action)) {
                        return Err("duplicate_permission".into());
                    }
                }
            }
            Command::Revoke { principal } => {
                identifier(principal)?;
                if principal == "owner" {
                    return Err("reserved_principal".into());
                }
            }
            Command::Inspect {
                principal,
                request_id,
            } => {
                identifier(principal)?;
                identifier(request_id)?;
            }
            Command::Hello {
                minimum_version,
                maximum_version,
            } => {
                if *minimum_version != 2 || *maximum_version != 2 {
                    return Err("incompatible_protocol_version".into());
                }
            }
            Command::Capabilities { after, limit } => {
                if !(1..=20).contains(limit) {
                    return Err("invalid_page_limit".into());
                }
                if let Some(cursor) = after {
                    identifier(cursor)?;
                }
            }
            Command::Preview { request } => request.validate()?,
            Command::Execute {
                request_id,
                plan_sha256,
            } => {
                identifier(request_id)?;
                fingerprint(plan_sha256)?;
            }
            Command::Status { request_id }
            | Command::Cancel { request_id }
            | Command::Reconcile { request_id } => identifier(request_id)?,
            Command::Events { after, limit } => {
                if *after > edge_contracts::MAX_SAFE_INTEGER as u64 || !(1..=100).contains(limit) {
                    return Err("invalid_event_page".into());
                }
            }
            Command::Approve {
                principal,
                request_id,
                plan_sha256,
            } => {
                identifier(principal)?;
                identifier(request_id)?;
                fingerprint(plan_sha256)?;
            }
        }
        Ok(())
    }
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Reply {
    Hello {
        protocol_version: u32,
        authority_id: String,
        principal: String,
    },
    Capabilities {
        items: Vec<edge_contracts::actions::Capability>,
        next: Option<String>,
    },
    Record {
        record: Box<edge_contracts::actions::Record>,
    },
    Events {
        items: Vec<edge_contracts::actions::Event>,
    },
    Enrolled {
        credential: Credential,
    },
    Approved {
        request_id: String,
        plan_sha256: String,
    },
    Revoked {
        principal: String,
    },
    Error {
        code: String,
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
    pub fn new(call_id: &str, reply: Reply) -> Self {
        Self {
            schema_version: VERSION.into(),
            call_id: call_id.into(),
            reply,
        }
    }
}
