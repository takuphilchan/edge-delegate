//! Private installed-adapter channel, not a client permission or execution API.
use edge_contracts::{
    Result, identifier,
    operation::Receipt,
    preview::{PlanStep, PreviewContext},
};
use serde::{Deserialize, Serialize};

pub const ADAPTER_VERSION: &str = "edge-adapter-worker.v1";

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AdapterRequest {
    pub schema_version: String,
    pub call_id: u32,
    /// Remaining duration at send, not a timestamp from another process/machine.
    pub budget_ms: u32,
    pub command: AdapterCommand,
}

#[derive(Serialize, Deserialize)]
#[serde(tag = "method", rename_all = "snake_case", deny_unknown_fields)]
pub enum AdapterCommand {
    Observe {},
    Invoke {
        operation_id: String,
        step: PlanStep,
    },
    Reconcile {
        operation_id: String,
    },
}
impl AdapterRequest {
    pub fn validate(&self) -> Result<()> {
        if self.schema_version != ADAPTER_VERSION
            || self.call_id == 0
            || !(1..=5000).contains(&self.budget_ms)
        {
            return Err("invalid_adapter_envelope".into());
        }
        match &self.command {
            AdapterCommand::Observe {} => (),
            AdapterCommand::Reconcile { operation_id } => identifier(operation_id)?,
            AdapterCommand::Invoke { operation_id, step } => {
                identifier(operation_id)?;
                identifier(&step.step_id)?;
                identifier(&step.action)?;
                step.target.validate()?;
                if !(1..=5000).contains(&step.timeout_ms) || step.parameters.len() > 16 {
                    return Err("invalid_adapter_step".into());
                }
                for (name, parameter) in &step.parameters {
                    identifier(name)?;
                    parameter.validate()?;
                }
            }
        }
        Ok(())
    }
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AdapterResponse {
    pub schema_version: String,
    pub call_id: u32,
    pub reply: AdapterReply,
}
#[derive(Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum AdapterReply {
    Context { context: PreviewContext },
    Receipt { receipt: Receipt },
    Unavailable {},
}

/// Explicit software faults selected by trusted test setup, never by a language request.
#[derive(Debug, Clone, Copy, Default)]
pub enum SimulatorFault {
    #[default]
    None,
    HangBeforeEffect,
    HangAfterEffect,
    CrashAfterEffect,
    LostAcknowledgement,
    MalformedResponse,
}
impl SimulatorFault {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::None => "none",
            Self::HangBeforeEffect => "hang-before-effect",
            Self::HangAfterEffect => "hang-after-effect",
            Self::CrashAfterEffect => "crash-after-effect",
            Self::LostAcknowledgement => "lost-ack",
            Self::MalformedResponse => "malformed-response",
        }
    }
    pub fn parse(text: &str) -> Result<Self> {
        match text {
            "none" => Ok(Self::None),
            "hang-before-effect" => Ok(Self::HangBeforeEffect),
            "hang-after-effect" => Ok(Self::HangAfterEffect),
            "crash-after-effect" => Ok(Self::CrashAfterEffect),
            "lost-ack" => Ok(Self::LostAcknowledgement),
            "malformed-response" => Ok(Self::MalformedResponse),
            _ => Err("unsupported_simulator_fault".into()),
        }
    }
}
