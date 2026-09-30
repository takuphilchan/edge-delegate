//! Pure compilation against host-supplied policy. Adapters never grant permissions.
use edge_contracts::actions::Receipt;
use edge_contracts::actions::{Endpoint, Plan, Request, validate_fields};
use edge_contracts::{Result, digest, identifier};
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use std::time::Instant;

/// Trusted embedding boundary, not an authenticated client interface. The host
/// supplies principal after authentication and approval. Invocation errors mean
/// uncertain outcome; they never authorize retry under a replacement identity.
pub trait Adapter {
    fn describe(&self) -> Result<Endpoint>;
    /// Trusted in-process adapters must honor this budget. Process adapters enforce
    /// it in their transport, including observation before an invocation.
    fn describe_until(&self, deadline: Instant) -> Result<Endpoint> {
        crate::execution::check_deadline(deadline)?;
        let endpoint = self.describe()?;
        crate::execution::check_deadline(deadline)?;
        Ok(endpoint)
    }
    fn invoke(
        &mut self,
        principal: &str,
        operation_id: &str,
        request: &Request,
        deadline: Instant,
    ) -> Result<Receipt>;
    fn reconcile(
        &mut self,
        principal: &str,
        operation_id: &str,
        request: &Request,
        deadline: Instant,
    ) -> Result<Receipt>;
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Permission {
    pub endpoint: String,
    pub action: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Policy {
    pub authority_id: String,
    pub principal: String,
    pub revision: u32,
    /// Exact pairs, not the Cartesian product of action and target sets.
    pub permissions: Vec<Permission>,
}
impl Policy {
    pub fn validate(&self) -> Result<()> {
        identifier(&self.authority_id)?;
        identifier(&self.principal)?;
        if self.permissions.len() > 128 {
            return Err("policy_too_large".into());
        }
        let mut pairs = BTreeSet::new();
        for permission in &self.permissions {
            identifier(&permission.endpoint)?;
            identifier(&permission.action)?;
            if !pairs.insert((&permission.endpoint, &permission.action)) {
                return Err("duplicate_permission".into());
            }
        }
        Ok(())
    }
    pub fn allows(&self, endpoint: &str, action: &str) -> bool {
        self.permissions
            .iter()
            .any(|p| p.endpoint == endpoint && p.action == action)
    }
}

/// Non-executing single action compilation. The host authenticates the principal
/// and supplies current definitions/observations. No consent is issued here.
pub fn compile(request: &Request, endpoints: &[Endpoint], policy: &Policy) -> Result<Plan> {
    request.validate()?;
    policy.validate()?;
    if endpoints.len() > 128 {
        return Err("too_many_endpoints".into());
    }
    let mut ids = BTreeSet::new();
    for endpoint in endpoints {
        endpoint.validate()?;
        if endpoint.binding.authority_id != policy.authority_id
            || !ids.insert(&endpoint.binding.endpoint_id)
        {
            return Err("invalid_endpoint_registry".into());
        }
    }
    if request.target.authority_id != policy.authority_id {
        return Err("wrong_authority".into());
    }
    if !policy.allows(&request.target.endpoint_id, &request.action) {
        return Err("policy_denied".into());
    }
    let endpoint = endpoints
        .iter()
        .find(|e| e.binding.endpoint_id == request.target.endpoint_id)
        .ok_or("unknown_target")?;
    if endpoint.binding != request.target {
        return Err("repreview_required".into());
    }
    let definition = endpoint
        .actions
        .iter()
        .find(|a| a.action == request.action)
        .ok_or("unsupported_action")?;
    validate_fields(&request.parameters, &definition.parameters)?;
    let plan = Plan {
        schema_version: "edge-action-plan.v1".into(),
        request: request.clone(),
        request_sha256: digest(request)?,
        policy_sha256: digest(policy)?,
        definition: definition.clone(),
        timeout_ms: request.budget_ms.min(definition.max_duration_ms),
    };
    plan.validate()?;
    Ok(plan)
}

/// Return only permitted action/endpoint pairs, keeping their original bindings.
/// Full registry validation happens before filtering, even for hidden entries.
pub fn discover(
    endpoints: &[Endpoint],
    policy: &Policy,
) -> Result<Vec<edge_contracts::actions::Capability>> {
    policy.validate()?;
    if endpoints.len() > 128 {
        return Err("too_many_endpoints".into());
    }
    let mut ids = BTreeSet::new();
    let mut visible = Vec::new();
    for endpoint in endpoints {
        endpoint.validate()?;
        if endpoint.binding.authority_id != policy.authority_id
            || !ids.insert(&endpoint.binding.endpoint_id)
        {
            return Err("invalid_endpoint_registry".into());
        }
        for action in &endpoint.actions {
            if policy.allows(&endpoint.binding.endpoint_id, &action.action) {
                visible.push(edge_contracts::actions::Capability {
                    target: endpoint.binding.clone(),
                    definition: action.clone(),
                });
            }
        }
    }
    Ok(visible)
}
