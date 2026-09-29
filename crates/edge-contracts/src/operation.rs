//! Durable operation records shared by the coordinator and adapter protocol.
use crate::{Evidence, Parameter, Result, identifier, preview::Plan};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OperationState {
    Prepared,
    Dispatching,
    Succeeded,
    Failed,
    Unknown,
    CancelledBeforeDispatch,
    ExpiredBeforeDispatch,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum Receipt {
    Succeeded {
        value: Parameter,
        evidence: Evidence,
    },
    Failed {
        reason: String,
    },
    Unknown {
        reason: String,
    },
}

impl Receipt {
    pub fn validate(&self) -> Result<()> {
        match self {
            Self::Succeeded { value, .. } => value.validate(),
            Self::Failed { reason } | Self::Unknown { reason } => identifier(reason),
        }
    }
    pub fn state(&self) -> OperationState {
        match self {
            Self::Succeeded { .. } => OperationState::Succeeded,
            Self::Failed { .. } => OperationState::Failed,
            Self::Unknown { .. } => OperationState::Unknown,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Operation {
    pub operation_id: String,
    pub principal: String,
    pub request_id: String,
    pub request_sha256: String,
    pub plan: Plan,
    pub state: OperationState,
    pub receipt: Option<Receipt>,
}
