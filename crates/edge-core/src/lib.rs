//! Portable compiler and single-operation coordinator. Concrete I/O is supplied by ports.
//! Saved-context previews are for inspection; they cannot authorize live execution.

pub mod actions;
pub mod cancellation;
pub mod execution;

pub use edge_contracts::preview::{
    ActionDefinition, Effect, Endpoint, ParameterRule, Plan, PlanStep, Preview, PreviewContext,
    PreviewDecision, PreviewPolicy,
};
use edge_contracts::{ControlRequest, RequestInput, Result, digest};

/// Strict single-action foundation. No approval issuer, interpretation worker,
/// workflow executor, or adapter is implemented by this function.
pub fn preview(request: &ControlRequest, context: &PreviewContext) -> Result<Preview> {
    request.validate()?;
    context.validate()?;
    let decision = compile(request, context)?;
    Ok(Preview {
        schema_version: "edge-control-preview.v2".into(),
        execution_attempted: false,
        context_kind: "saved_untrusted_for_execution".into(),
        decision,
    })
}

fn compile(request: &ControlRequest, context: &PreviewContext) -> Result<PreviewDecision> {
    let reject = |reason: &str| {
        Ok(PreviewDecision::Rejected {
            reason: reason.into(),
        })
    };
    if request.authority_id != context.authority_id {
        return reject("wrong_authority");
    }
    let RequestInput::Action {
        target,
        action,
        parameters,
    } = &request.input
    else {
        return Ok(PreviewDecision::ClarificationRequired {
            reason: "text_planner_not_installed_use_structured_request".into(),
        });
    };
    let Some(endpoint) = context
        .endpoints
        .iter()
        .find(|e| e.binding.endpoint_id == target.endpoint_id)
    else {
        return reject("unknown_target");
    };
    if &endpoint.binding != target {
        return reject("repreview_required");
    }
    let Some(definition) = endpoint.actions.iter().find(|a| &a.action == action) else {
        return reject("unsupported_action");
    };
    if !context
        .policy
        .allowed_endpoints
        .contains(&target.endpoint_id)
        || !context.policy.allowed_actions.contains(action)
    {
        return reject("policy_denied");
    }
    if parameters.len() != definition.parameters.len()
        || !definition
            .parameters
            .iter()
            .all(|(key, rule)| parameters.get(key).is_some_and(|p| rule.accepts(p)))
    {
        return reject("invalid_parameters");
    }
    let plan = Plan {
        schema_version: "edge-plan.v2".into(),
        request_id: request.request_id.clone(),
        request_sha256: digest(request)?,
        authority_id: request.authority_id.clone(),
        policy_sha256: digest(&context.policy)?,
        steps: vec![PlanStep {
            step_id: "step-1".into(),
            target: target.clone(),
            action: action.clone(),
            parameters: parameters.clone(),
            timeout_ms: request.budget_ms.min(definition.max_duration_ms),
            expected_evidence: definition.expected_evidence,
        }],
    };
    Ok(PreviewDecision::Proposed {
        plan_sha256: digest(&plan)?,
        plan,
        requires_approval: definition.effect == Effect::Write,
    })
}
