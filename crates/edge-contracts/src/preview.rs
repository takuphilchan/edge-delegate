//! Shared preview/catalog wire types. These records never authorize execution.
use crate::{Evidence, Parameter, Result, TargetBinding, digest, identifier};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", deny_unknown_fields)]
pub enum ParameterRule {
    #[serde(rename = "boolean")]
    Boolean {},
    #[serde(rename = "integer")]
    Integer { minimum: i64, maximum: i64 },
    #[serde(rename = "string")]
    String { max_bytes: usize },
    #[serde(rename = "enum")]
    Enum { values: BTreeSet<String> },
    #[serde(rename = "resource")]
    Resource { allowed_ids: BTreeSet<String> },
}

impl ParameterRule {
    fn validate(&self) -> Result<()> {
        match self {
            Self::Integer { minimum, maximum }
                if minimum > maximum
                    || *minimum < -crate::MAX_SAFE_INTEGER
                    || *maximum > crate::MAX_SAFE_INTEGER =>
            {
                Err("invalid integer rule".into())
            }
            Self::String { max_bytes } if *max_bytes > crate::MAX_TEXT_BYTES => {
                Err("string rule exceeds contract limit".into())
            }
            Self::Enum { values }
            | Self::Resource {
                allowed_ids: values,
            } => {
                if values.is_empty() || values.len() > 128 {
                    return Err("invalid allowed value set".into());
                }
                for value in values {
                    identifier(value)?;
                }
                Ok(())
            }
            _ => Ok(()),
        }
    }

    pub fn accepts(&self, parameter: &Parameter) -> bool {
        match (self, parameter) {
            (Self::Boolean {}, Parameter::Boolean { .. }) => true,
            (Self::Integer { minimum, maximum }, Parameter::Integer { value }) => {
                (minimum..=maximum).contains(&value)
            }
            (Self::String { max_bytes }, Parameter::String { value }) => value.len() <= *max_bytes,
            (Self::Enum { values }, Parameter::Enum { value }) => values.contains(value),
            (Self::Resource { allowed_ids }, Parameter::Resource { value }) => {
                allowed_ids.contains(value)
            }
            _ => false,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Effect {
    Read,
    Write,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ActionDefinition {
    pub action: String,
    pub effect: Effect,
    pub parameters: BTreeMap<String, ParameterRule>,
    pub max_duration_ms: u32,
    pub expected_evidence: Evidence,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Endpoint {
    pub binding: TargetBinding,
    pub actions: Vec<ActionDefinition>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PreviewPolicy {
    pub version: String,
    pub allowed_endpoints: BTreeSet<String>,
    pub allowed_actions: BTreeSet<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PreviewContext {
    pub schema_version: String,
    pub authority_id: String,
    pub policy: PreviewPolicy,
    pub endpoints: Vec<Endpoint>,
}

impl PreviewContext {
    pub fn validate(&self) -> Result<()> {
        if self.schema_version != "edge-preview-context.v1" {
            return Err("unsupported preview context version".into());
        }
        identifier(&self.authority_id)?;
        identifier(&self.policy.version)?;
        if self.endpoints.len() > 128
            || self.policy.allowed_actions.len() > 128
            || self.policy.allowed_endpoints.len() > 128
        {
            return Err("context exceeds catalog limits".into());
        }
        for id in self
            .policy
            .allowed_actions
            .iter()
            .chain(self.policy.allowed_endpoints.iter())
        {
            identifier(id)?;
        }
        let mut endpoints = BTreeSet::new();
        for endpoint in &self.endpoints {
            endpoint.binding.validate()?;
            if endpoint.binding.authority_id != self.authority_id
                || !endpoints.insert(&endpoint.binding.endpoint_id)
            {
                return Err("duplicate endpoint or wrong authority in context".into());
            }
            if endpoint.actions.len() > 128
                || endpoint.binding.catalog_sha256 != digest(&endpoint.actions)?
            {
                return Err("catalog size or fingerprint mismatch".into());
            }
            let mut actions = BTreeSet::new();
            for action in &endpoint.actions {
                identifier(&action.action)?;
                if !actions.insert(&action.action)
                    || !(1..=10_000).contains(&action.max_duration_ms)
                    || action.parameters.len() > 16
                {
                    return Err("invalid or duplicate action definition".into());
                }
                for (name, rule) in &action.parameters {
                    identifier(name)?;
                    rule.validate()?;
                }
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PlanStep {
    pub step_id: String,
    pub target: TargetBinding,
    pub action: String,
    pub parameters: BTreeMap<String, Parameter>,
    pub timeout_ms: u32,
    pub expected_evidence: Evidence,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Plan {
    pub schema_version: String,
    pub request_id: String,
    pub request_sha256: String,
    pub authority_id: String,
    pub policy_sha256: String,
    pub steps: Vec<PlanStep>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum PreviewDecision {
    Proposed {
        plan: Plan,
        plan_sha256: String,
        requires_approval: bool,
    },
    ClarificationRequired {
        reason: String,
    },
    Rejected {
        reason: String,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Preview {
    pub schema_version: String,
    pub execution_attempted: bool,
    pub context_kind: String,
    pub decision: PreviewDecision,
}
