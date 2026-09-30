//! Generic single-action contracts. Separate from legacy preview and execution records.
//! A valid request, catalog or plan is not permission to execute.
use crate::preview::{Effect, ParameterRule};
use crate::{Evidence, Parameter, Result, TargetBinding, digest, identifier, parse_json};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

pub type Fields = BTreeMap<String, Parameter>;
pub type Shape = BTreeMap<String, FieldRule>;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum FieldRule {
    Scalar {
        rule: ParameterRule,
    },
    /// Syntax only. Resource ownership must still be checked by the host/adapter.
    ResourceReference {},
}
impl FieldRule {
    pub fn validate(&self) -> Result<()> {
        match self {
            Self::Scalar { rule } => rule.validate(),
            Self::ResourceReference {} => Ok(()),
        }
    }
    pub fn accepts(&self, value: &Parameter) -> bool {
        value.validate().is_ok()
            && match self {
                Self::Scalar { rule } => rule.accepts(value),
                Self::ResourceReference {} => matches!(value, Parameter::Resource { .. }),
            }
    }
}
pub fn validate_shape(shape: &Shape) -> Result<()> {
    if shape.len() > 16 {
        return Err("too_many_fields".into());
    }
    for (name, rule) in shape {
        identifier(name)?;
        rule.validate()?;
    }
    Ok(())
}
pub fn validate_fields(fields: &Fields, shape: &Shape) -> Result<()> {
    validate_shape(shape)?;
    if fields.len() != shape.len()
        || !shape
            .iter()
            .all(|(name, rule)| fields.get(name).is_some_and(|v| rule.accepts(v)))
    {
        return Err("invalid_fields".into());
    }
    Ok(())
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum OutputRule {
    Scalar { rule: FieldRule },
    Record { fields: Shape },
    Page { fields: Shape, max_items: usize },
}
impl OutputRule {
    pub fn validate(&self) -> Result<()> {
        match self {
            Self::Scalar { rule } => rule.validate(),
            Self::Record { fields } => validate_shape(fields),
            Self::Page { fields, max_items } => {
                if !(1..=20).contains(max_items) {
                    return Err("invalid_page_limit".into());
                }
                validate_shape(fields)
            }
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Output {
    Scalar {
        value: Parameter,
    },
    Record {
        fields: Fields,
    },
    Page {
        items: Vec<Fields>,
        next_cursor: Option<String>,
    },
}
impl Output {
    pub fn validate(&self, rule: &OutputRule) -> Result<()> {
        rule.validate()?;
        match (self, rule) {
            (Self::Scalar { value }, OutputRule::Scalar { rule }) if rule.accepts(value) => (),
            (Self::Record { fields }, OutputRule::Record { fields: shape }) => {
                validate_fields(fields, shape)?
            }
            (Self::Page { items, next_cursor }, OutputRule::Page { fields, max_items }) => {
                if items.len() > *max_items {
                    return Err("page_too_large".into());
                }
                if let Some(cursor) = next_cursor {
                    identifier(cursor)?;
                }
                for item in items {
                    validate_fields(item, fields)?;
                }
            }
            _ => return Err("wrong_output_shape".into()),
        }
        // Includes escaping/UTF-8 cost, not just unescaped field lengths. Leave room
        // for the enclosing result and transport envelope.
        if crate::canonical_bytes(self)?.len() > 32_768 {
            return Err("output_too_large".into());
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Action {
    pub action: String,
    pub effect: Effect,
    pub parameters: Shape,
    pub output: OutputRule,
    pub max_duration_ms: u32,
    pub expected_evidence: Evidence,
    pub allows_handoff: bool,
}
impl Action {
    pub fn validate(&self) -> Result<()> {
        identifier(&self.action)?;
        if !(1..=5000).contains(&self.max_duration_ms) {
            return Err("invalid_action_budget".into());
        }
        validate_shape(&self.parameters)?;
        self.output.validate()
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Endpoint {
    pub binding: TargetBinding,
    pub actions: Vec<Action>,
}

/// A permission-filtered catalog view. The binding retains the full installed
/// catalog fingerprint; it is not recomputed from this filtered action subset.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Capability {
    pub target: TargetBinding,
    pub definition: Action,
}
impl Endpoint {
    pub fn validate(&self) -> Result<()> {
        self.binding.validate()?;
        if self.actions.is_empty()
            || self.actions.len() > 128
            || digest(&self.actions)? != self.binding.catalog_sha256
        {
            return Err("invalid_catalog".into());
        }
        let mut names = BTreeSet::new();
        for action in &self.actions {
            action.validate()?;
            if !names.insert(&action.action) {
                return Err("duplicate_action".into());
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub schema_version: String,
    pub request_id: String,
    pub target: TargetBinding,
    pub action: String,
    pub parameters: Fields,
    pub budget_ms: u32,
}
impl Request {
    pub fn parse(bytes: &[u8]) -> Result<Self> {
        let request: Self = parse_json(bytes)?;
        request.validate()?;
        Ok(request)
    }
    pub fn validate(&self) -> Result<()> {
        if self.schema_version != "edge-action-request.v1" {
            return Err("incompatible_action_request".into());
        }
        identifier(&self.request_id)?;
        self.target.validate()?;
        identifier(&self.action)?;
        if !(1..=5000).contains(&self.budget_ms) || self.parameters.len() > 16 {
            return Err("invalid_request_limits".into());
        }
        for (name, value) in &self.parameters {
            identifier(name)?;
            value.validate()?;
        }
        if crate::canonical_bytes(self)?.len() > 32_768 {
            return Err("action_request_too_large".into());
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Plan {
    pub schema_version: String,
    pub request: Request,
    pub request_sha256: String,
    pub policy_sha256: String,
    pub definition: Action,
    pub timeout_ms: u32,
}
impl Plan {
    pub fn validate(&self) -> Result<()> {
        if self.schema_version != "edge-action-plan.v1" {
            return Err("incompatible_action_plan".into());
        }
        self.request.validate()?;
        self.definition.validate()?;
        crate::fingerprint(&self.policy_sha256)?;
        if self.request_sha256 != digest(&self.request)?
            || self.definition.action != self.request.action
            || self.timeout_ms != self.request.budget_ms.min(self.definition.max_duration_ms)
        {
            return Err("invalid_plan_binding".into());
        }
        validate_fields(&self.request.parameters, &self.definition.parameters)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum Receipt {
    Succeeded { output: Output, evidence: Evidence },
    HandedOff { evidence: Evidence },
    Failed { reason: String },
    Unknown { reason: String },
}
impl Receipt {
    pub fn validate(&self, action: &Action) -> Result<()> {
        action.validate()?;
        match self {
            Self::Succeeded { output, evidence } if *evidence == action.expected_evidence => {
                output.validate(&action.output)
            }
            Self::HandedOff { evidence }
                if action.allows_handoff && *evidence == Evidence::ApiAcknowledgement =>
            {
                Ok(())
            }
            Self::Failed { reason } | Self::Unknown { reason } => identifier(reason),
            _ => Err("invalid_receipt_evidence".into()),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum State {
    Offered,
    Prepared,
    Dispatching,
    Succeeded,
    HandedOff,
    Failed,
    Unknown,
    CancelledBeforeDispatch,
    ExpiredBeforeDispatch,
}
impl State {
    pub fn from_receipt(receipt: &Receipt) -> Self {
        match receipt {
            Receipt::Succeeded { .. } => Self::Succeeded,
            Receipt::HandedOff { .. } => Self::HandedOff,
            Receipt::Failed { .. } => Self::Failed,
            Receipt::Unknown { .. } => Self::Unknown,
        }
    }
    pub fn terminal(self) -> bool {
        matches!(
            self,
            Self::Succeeded
                | Self::HandedOff
                | Self::Failed
                | Self::CancelledBeforeDispatch
                | Self::ExpiredBeforeDispatch
        )
    }
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Record {
    pub schema_version: String,
    pub principal: String,
    pub operation_id: String,
    pub plan: Plan,
    pub state: State,
    pub receipt: Option<Receipt>,
}
impl Record {
    pub fn validate(&self) -> Result<()> {
        if self.schema_version != "edge-action-record.v1" {
            return Err("incompatible_action_record".into());
        }
        identifier(&self.principal)?;
        identifier(&self.operation_id)?;
        self.plan.validate()?;
        match (&self.receipt, self.state) {
            (Some(receipt), state) if State::from_receipt(receipt) == state => {
                receipt.validate(&self.plan.definition)
            }
            (
                None,
                State::Offered
                | State::Prepared
                | State::Dispatching
                | State::CancelledBeforeDispatch
                | State::ExpiredBeforeDispatch,
            ) => Ok(()),
            _ => Err("invalid_record_outcome".into()),
        }
    }
}

/// Metadata only: no note bodies, credentials, request parameters or receipts.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Event {
    pub sequence: u64,
    pub principal: String,
    pub request_id: Option<String>,
    pub kind: String,
}
