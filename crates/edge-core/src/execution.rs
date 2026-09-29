//! Experimental single-operation coordinator, invoked only by trusted embedding code.
//! Transport authentication, remote consent and supervised workers are not implemented here.

use crate::cancellation::{DispatchControl, DispatchDecision};
use crate::{Plan, PlanStep, PreviewContext, PreviewDecision, preview};
use edge_contracts::{ControlRequest, Result, digest, identifier};
use std::time::Instant;

pub use edge_contracts::operation::{Operation, OperationState, Receipt};

pub enum Claim {
    New(Operation),
    Existing(Operation),
}

/// Implementations must atomically bind claims and serialize uncertain target mutations.
/// Lock waits must respect the remaining budget and persistence must recheck it.
/// A blocking filesystem commit may overrun; that is not a hard deadline guarantee.
pub trait Journal {
    fn authority_id(&self) -> &str;
    fn lookup(
        &mut self,
        principal: &str,
        request_id: &str,
        deadline: Instant,
    ) -> Result<Option<Operation>>;
    fn claim(
        &mut self,
        principal: &str,
        plan: &Plan,
        approval: Option<&str>,
        requires_approval: bool,
        deadline: Instant,
    ) -> Result<Claim>;
    fn dispatch_intent(&mut self, operation_id: &str, deadline: Instant) -> Result<Operation>;
    /// Trusted coordinator proof: adapter invocation has NOT started. May close a
    /// persisted dispatch intent only while that proof still holds. Not a cancel RPC.
    fn stop_before_dispatch(
        &mut self,
        operation_id: &str,
        expired: bool,
        deadline: Instant,
    ) -> Result<Operation>;
    fn finish(
        &mut self,
        operation_id: &str,
        receipt: Receipt,
        deadline: Instant,
    ) -> Result<Operation>;
}

/// Installed adapters, not model code, provide current state and actual receipts.
/// Err from invoke means uncertainty, not a confirmed failure. Transport deadlines
/// must be implemented by the adapter; a synchronous call cannot be preempted here.
pub trait Adapter {
    fn observe(&mut self, deadline: Instant) -> Result<PreviewContext>;
    fn invoke(&mut self, operation_id: &str, step: &PlanStep, deadline: Instant)
    -> Result<Receipt>;
    fn reconcile(&mut self, operation_id: &str, deadline: Instant) -> Result<Receipt>;
}

pub fn check_deadline(deadline: Instant) -> Result<()> {
    if Instant::now() >= deadline {
        Err("deadline_expired".into())
    } else {
        Ok(())
    }
}

fn proposed(request: &ControlRequest, context: &PreviewContext) -> Result<(Plan, bool)> {
    match preview(request, context)?.decision {
        PreviewDecision::Proposed {
            plan,
            requires_approval,
            ..
        } => Ok((plan, requires_approval)),
        PreviewDecision::Rejected { reason }
        | PreviewDecision::ClarificationRequired { reason } => Err(reason),
    }
}

/// A one-step experimental runtime. The embedding layer authenticates principal.
/// An existing record is returned, never dispatched again, even after approval expiry.
pub fn execute(
    journal: &mut impl Journal,
    adapter: &mut impl Adapter,
    principal: &str,
    request: &ControlRequest,
    approval: Option<&str>,
    deadline: Instant,
) -> Result<Operation> {
    execute_controlled(
        journal,
        adapter,
        principal,
        request,
        approval,
        deadline,
        &DispatchControl::default(),
    )
}

/// Controlled variant for a host with out-of-band cancellation. A cancellation accepted
/// before begin_dispatch fences invocation even if intent has already been persisted.
pub fn execute_controlled(
    journal: &mut impl Journal,
    adapter: &mut impl Adapter,
    principal: &str,
    request: &ControlRequest,
    approval: Option<&str>,
    deadline: Instant,
    control: &DispatchControl,
) -> Result<Operation> {
    let started = Instant::now();
    check_deadline(deadline)?;
    identifier(principal)?;
    request.validate()?;
    let deadline =
        deadline.min(started + std::time::Duration::from_millis(request.budget_ms.into()));
    if request.authority_id != journal.authority_id() {
        return Err("wrong_authority".into());
    }
    if let Some(record) = journal.lookup(principal, &request.request_id, deadline)? {
        if record.request_sha256 != digest(request)? {
            return Err("request_identity_conflict".into());
        }
        return Ok(record);
    }
    if control.cancelled() {
        return Err("cancelled_before_dispatch".into());
    }
    let (plan, requires_approval) = proposed(request, &adapter.observe(deadline)?)?;
    check_deadline(deadline)?;
    let operation = match journal.claim(principal, &plan, approval, requires_approval, deadline)? {
        Claim::Existing(record) => return Ok(record),
        Claim::New(record) => record,
    };
    if control.cancelled() {
        return journal.stop_before_dispatch(&operation.operation_id, false, cleanup_deadline());
    }
    // Fresh validation after durable claim, immediately before dispatch intent.
    let fresh = adapter
        .observe(deadline)
        .and_then(|context| proposed(request, &context));
    match fresh {
        Ok((current, current_approval))
            if digest(&current)? == digest(&plan)? && current_approval == requires_approval => {}
        _ => {
            // No invocation occurred. If storage is unavailable, Prepared remains fenced.
            return journal.stop_before_dispatch(
                &operation.operation_id,
                Instant::now() >= deadline,
                cleanup_deadline(),
            );
        }
    }
    if control.cancelled() || Instant::now() >= deadline {
        return journal.stop_before_dispatch(
            &operation.operation_id,
            !control.cancelled(),
            cleanup_deadline(),
        );
    }
    let intent = journal.dispatch_intent(&operation.operation_id, deadline)?;
    if intent.state != OperationState::Dispatching {
        return Ok(intent);
    }
    match control.begin_dispatch(deadline) {
        DispatchDecision::Proceed => (),
        DispatchDecision::Cancelled => {
            return journal.stop_before_dispatch(
                &operation.operation_id,
                false,
                cleanup_deadline(),
            );
        }
        DispatchDecision::Expired => {
            return journal.stop_before_dispatch(&operation.operation_id, true, cleanup_deadline());
        }
    }
    let step = &plan.steps[0];
    let invocation_deadline =
        deadline.min(Instant::now() + std::time::Duration::from_millis(step.timeout_ms.into()));
    let receipt = match adapter.invoke(&operation.operation_id, step, invocation_deadline) {
        Ok(receipt)
            if receipt.validate().is_ok()
                && match &receipt {
                    Receipt::Succeeded { evidence, .. } => *evidence == step.expected_evidence,
                    _ => true,
                } =>
        {
            receipt
        }
        _ => Receipt::Unknown {
            reason: "adapter_error_or_invalid_receipt".into(),
        },
    };
    // Returning late cannot establish an in-budget acknowledged outcome.
    let receipt = if Instant::now() >= invocation_deadline {
        Receipt::Unknown {
            reason: "late_adapter_result".into(),
        }
    } else {
        receipt
    };
    journal.finish(&operation.operation_id, receipt, deadline)
}

// Recording a no-dispatch fence is cleanup, never renewed permission to invoke an adapter.
fn cleanup_deadline() -> Instant {
    Instant::now() + std::time::Duration::from_secs(2)
}

/// Only recovery observes an uncertain operation. Missing receipts stay unknown.
/// Prepared operations are never resumed by this method.
pub fn reconcile(
    journal: &mut impl Journal,
    adapter: &mut impl Adapter,
    principal: &str,
    request_id: &str,
    deadline: Instant,
) -> Result<Operation> {
    check_deadline(deadline)?;
    let operation = journal
        .lookup(principal, request_id, deadline)?
        .ok_or("unknown_request")?;
    if !matches!(
        operation.state,
        OperationState::Dispatching | OperationState::Unknown
    ) {
        return Ok(operation);
    }
    let context = adapter.observe(deadline)?;
    context.validate()?;
    let target = &operation.plan.steps[0].target;
    if context.authority_id != target.authority_id
        || !context.endpoints.iter().any(|endpoint| {
            endpoint.binding.endpoint_id == target.endpoint_id
                && endpoint.binding.registration_generation == target.registration_generation
                && endpoint.binding.catalog_sha256 == target.catalog_sha256
        })
    {
        return Err("reconciliation_target_changed".into());
    }
    let receipt = adapter
        .reconcile(&operation.operation_id, deadline)
        .unwrap_or(Receipt::Unknown {
            reason: "reconciliation_unavailable".into(),
        });
    receipt.validate()?;
    if let Receipt::Succeeded { evidence, .. } = &receipt
        && *evidence != operation.plan.steps[0].expected_evidence
    {
        return Err("reconciliation_evidence_mismatch".into());
    }
    check_deadline(deadline)?;
    journal.finish(&operation.operation_id, receipt, deadline)
}
