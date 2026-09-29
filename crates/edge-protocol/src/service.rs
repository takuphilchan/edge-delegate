//! Preview-service subset. No execution/approval command is admitted by this schema.
use edge_contracts::{
    ControlRequest, Result, identifier,
    preview::{Preview, PreviewContext},
};
use serde::{Deserialize, Serialize};

pub const SERVICE_VERSION: &str = "edge-service-envelope.v1";
pub const PROTOCOL_VERSION: u32 = 1;

// Deliberately no Debug: credentials and raw requests must not enter diagnostics.
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ServiceRequest {
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
    Capabilities {},
    Preview {
        request: ControlRequest,
    },
}

impl ServiceRequest {
    pub fn validate(&self) -> Result<()> {
        if self.schema_version != SERVICE_VERSION {
            return Err("incompatible service schema".into());
        }
        identifier(&self.call_id)?;
        edge_contracts::fingerprint(&self.credential)?;
        if let Command::Preview { request } = &self.command {
            request.validate()?;
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ErrorCode {
    Unauthenticated,
    IncompatibleVersion,
    NegotiationRequired,
    InvalidRequest,
    Overloaded,
    Expired,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Reply {
    Hello {
        protocol_version: u32,
        authority_id: String,
        principal: String,
        mode: ServiceMode,
    },
    Capabilities {
        context: PreviewContext,
    },
    Preview {
        preview: Preview,
    },
    Error {
        code: ErrorCode,
    },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ServiceMode {
    SavedContextPreviewOnly,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ServiceResponse {
    pub schema_version: String,
    pub call_id: String,
    pub reply: Reply,
}

impl ServiceResponse {
    pub fn new(call_id: String, reply: Reply) -> Self {
        Self {
            schema_version: SERVICE_VERSION.into(),
            call_id,
            reply,
        }
    }
}
