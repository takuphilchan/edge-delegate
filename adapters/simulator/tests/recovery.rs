use edge_contracts::{ControlRequest, Parameter, RequestInput};
use edge_core::{
    Plan, PreviewDecision,
    cancellation::{CancelDisposition, DispatchControl},
    execution::{
        Adapter, Claim, Journal, Operation, OperationState, Receipt, execute, execute_controlled,
        reconcile,
    },
    preview,
};
use edge_simulator::{Fault, Simulator};
use edge_storage::SqliteJournal;
use std::time::{Duration, Instant};
use tempfile::{TempDir, tempdir};

fn deadline() -> Instant {
    Instant::now() + Duration::from_secs(5)
}
fn plan(device: &mut Simulator, request: &ControlRequest) -> Plan {
    match preview(request, &device.observe(deadline()).unwrap())
        .unwrap()
        .decision
    {
        PreviewDecision::Proposed { plan, .. } => plan,
        other => panic!("{other:?}"),
    }
}
fn setup() -> (TempDir, Simulator, SqliteJournal, ControlRequest, Plan) {
    let root = tempdir().unwrap();
    let mut device = Simulator::open(&root.path().join("device.sqlite")).unwrap();
    let journal = SqliteJournal::open(&root.path().join("journal"), device.authority_id()).unwrap();
    let request = device.request("request-1", 40, deadline()).unwrap();
    let proposed = plan(&mut device, &request);
    (root, device, journal, request, proposed)
}

enum Interruption {
    AfterClaim,
    AfterIntent,
    ExpireAfterIntent,
}
struct InterruptedJournal<'a> {
    inner: &'a mut SqliteJournal,
    control: DispatchControl,
    at: Interruption,
}
impl Journal for InterruptedJournal<'_> {
    fn authority_id(&self) -> &str {
        self.inner.authority_id()
    }
    fn lookup(
        &mut self,
        principal: &str,
        id: &str,
        deadline: Instant,
    ) -> edge_contracts::Result<Option<Operation>> {
        self.inner.lookup(principal, id, deadline)
    }
    fn claim(
        &mut self,
        principal: &str,
        plan: &Plan,
        approval: Option<&str>,
        required: bool,
        deadline: Instant,
    ) -> edge_contracts::Result<Claim> {
        let result = self
            .inner
            .claim(principal, plan, approval, required, deadline)?;
        if matches!(self.at, Interruption::AfterClaim) {
            assert_eq!(self.control.cancel(), CancelDisposition::PreventedDispatch);
        }
        Ok(result)
    }
    fn dispatch_intent(
        &mut self,
        id: &str,
        deadline: Instant,
    ) -> edge_contracts::Result<Operation> {
        let result = self.inner.dispatch_intent(id, deadline)?;
        match self.at {
            Interruption::AfterIntent => {
                assert_eq!(self.control.cancel(), CancelDisposition::PreventedDispatch)
            }
            Interruption::ExpireAfterIntent => std::thread::sleep(
                deadline.saturating_duration_since(Instant::now()) + Duration::from_millis(1),
            ),
            Interruption::AfterClaim => panic!("cancelled claim must not reach intent"),
        }
        Ok(result)
    }
    fn stop_before_dispatch(
        &mut self,
        id: &str,
        expired: bool,
        deadline: Instant,
    ) -> edge_contracts::Result<Operation> {
        self.inner.stop_before_dispatch(id, expired, deadline)
    }
    fn finish(
        &mut self,
        id: &str,
        receipt: Receipt,
        deadline: Instant,
    ) -> edge_contracts::Result<Operation> {
        self.inner.finish(id, receipt, deadline)
    }
}

fn check_interruption(at: Interruption, expected: OperationState) {
    let (root, mut device, mut journal, request, proposed) = setup();
    let token = journal.approve("owner", &proposed, deadline()).unwrap();
    let control = DispatchControl::default();
    let until = Instant::now() + Duration::from_secs(1);
    let result = execute_controlled(
        &mut InterruptedJournal {
            inner: &mut journal,
            control: control.clone(),
            at,
        },
        &mut device,
        "owner",
        &request,
        Some(&token),
        until,
        &control,
    )
    .unwrap();
    assert_eq!(result.state, expected);
    assert_eq!(device.invoke_calls, 0);
    assert_eq!(device.writes().unwrap(), 0);
    drop(journal);
    let mut journal =
        SqliteJournal::open(&root.path().join("journal"), device.authority_id()).unwrap();
    let retry = execute(
        &mut journal,
        &mut device,
        "owner",
        &request,
        None,
        deadline(),
    )
    .unwrap();
    assert_eq!(retry.state, expected);
    assert_eq!(retry.operation_id, result.operation_id);
    assert_eq!(device.invoke_calls, 0);
}

#[test]
fn cancellation_after_claim_persists_a_no_dispatch_fence() {
    check_interruption(
        Interruption::AfterClaim,
        OperationState::CancelledBeforeDispatch,
    );
}
#[test]
fn cancellation_after_intent_persists_a_no_dispatch_fence() {
    check_interruption(
        Interruption::AfterIntent,
        OperationState::CancelledBeforeDispatch,
    );
}
#[test]
fn deadline_overrun_during_intent_commit_never_invokes() {
    check_interruption(
        Interruption::ExpireAfterIntent,
        OperationState::ExpiredBeforeDispatch,
    );
}

#[test]
fn missing_approval_never_invokes() {
    let (_root, mut device, mut journal, request, _) = setup();
    assert!(
        execute(
            &mut journal,
            &mut device,
            "owner",
            &request,
            None,
            deadline()
        )
        .is_err()
    );
    assert_eq!(device.invoke_calls, 0);
    assert_eq!(device.writes().unwrap(), 0);
}

#[test]
fn approved_operation_executes_once_and_replays_without_a_new_approval() {
    let (_root, mut device, mut journal, request, proposed) = setup();
    let token = journal.approve("owner", &proposed, deadline()).unwrap();
    let first = execute(
        &mut journal,
        &mut device,
        "owner",
        &request,
        Some(&token),
        deadline(),
    )
    .unwrap();
    assert_eq!(first.state, OperationState::Succeeded);
    assert_eq!(device.volume().unwrap(), 40);
    let retry = execute(
        &mut journal,
        &mut device,
        "owner",
        &request,
        None,
        deadline(),
    )
    .unwrap();
    assert_eq!(retry.operation_id, first.operation_id);
    assert_eq!(device.invoke_calls, 1);
    assert_eq!(device.writes().unwrap(), 1);
}

#[test]
fn approvals_bind_principal_parameters_and_request_id() {
    let (_root, mut device, mut journal, request, proposed) = setup();
    let token = journal.approve("owner", &proposed, deadline()).unwrap();
    assert!(
        execute(
            &mut journal,
            &mut device,
            "other",
            &request,
            Some(&token),
            deadline()
        )
        .is_err()
    );
    let mut changed = request.clone();
    if let RequestInput::Action { parameters, .. } = &mut changed.input {
        parameters.insert("percent".into(), Parameter::Integer { value: 41 });
    }
    assert!(
        execute(
            &mut journal,
            &mut device,
            "owner",
            &changed,
            Some(&token),
            deadline()
        )
        .is_err()
    );
    changed = request.clone();
    changed.request_id = "request-2".into();
    assert!(
        execute(
            &mut journal,
            &mut device,
            "owner",
            &changed,
            Some(&token),
            deadline()
        )
        .is_err()
    );
    assert_eq!(device.invoke_calls, 0);
    // Failed claims roll back token consumption.
    execute(
        &mut journal,
        &mut device,
        "owner",
        &request,
        Some(&token),
        deadline(),
    )
    .unwrap();
    assert!(
        execute(
            &mut journal,
            &mut device,
            "owner",
            &changed,
            Some(&token),
            deadline()
        )
        .is_err()
    );
    assert_eq!(device.writes().unwrap(), 1);
}

#[test]
fn changed_input_cannot_reuse_a_completed_request_identity() {
    let (_root, mut device, mut journal, mut request, proposed) = setup();
    let token = journal.approve("owner", &proposed, deadline()).unwrap();
    execute(
        &mut journal,
        &mut device,
        "owner",
        &request,
        Some(&token),
        deadline(),
    )
    .unwrap();
    request.budget_ms -= 1;
    assert_eq!(
        execute(
            &mut journal,
            &mut device,
            "owner",
            &request,
            None,
            deadline()
        )
        .unwrap_err(),
        "request_identity_conflict"
    );
    assert_eq!(device.invoke_calls, 1);
}

#[test]
fn revoked_and_expired_tokens_do_not_dispatch() {
    let (root, mut device, mut journal, request, proposed) = setup();
    let token = journal.approve("owner", &proposed, deadline()).unwrap();
    journal.revoke(&token, deadline()).unwrap();
    assert!(
        execute(
            &mut journal,
            &mut device,
            "owner",
            &request,
            Some(&token),
            deadline()
        )
        .is_err()
    );
    let token = journal.approve("owner", &proposed, deadline()).unwrap();
    let db = rusqlite::Connection::open(root.path().join("journal/journal-v2.sqlite")).unwrap();
    db.execute("UPDATE approvals SET expires_ms=0", []).unwrap();
    assert!(
        execute(
            &mut journal,
            &mut device,
            "owner",
            &request,
            Some(&token),
            deadline()
        )
        .is_err()
    );
    assert_eq!(device.invoke_calls, 0);
}

#[test]
fn approvals_expire_on_restart_even_if_wall_time_has_not_advanced() {
    let (root, mut device, mut journal, request, proposed) = setup();
    let token = journal.approve("owner", &proposed, deadline()).unwrap();
    drop(journal);
    let mut journal =
        SqliteJournal::open(&root.path().join("journal"), device.authority_id()).unwrap();
    assert!(
        execute(
            &mut journal,
            &mut device,
            "owner",
            &request,
            Some(&token),
            deadline()
        )
        .is_err()
    );
    assert_eq!(device.invoke_calls, 0);
}

#[test]
fn lost_ack_reconciles_after_both_process_owners_restart_without_replay() {
    let (root, mut device, mut journal, request, proposed) = setup();
    let token = journal.approve("owner", &proposed, deadline()).unwrap();
    device.fault = Fault::LostAcknowledgement;
    let result = execute(
        &mut journal,
        &mut device,
        "owner",
        &request,
        Some(&token),
        deadline(),
    )
    .unwrap();
    assert_eq!(result.state, OperationState::Unknown);
    assert_eq!(device.writes().unwrap(), 1);
    drop(journal);
    drop(device);
    let mut device = Simulator::open(&root.path().join("device.sqlite")).unwrap();
    let mut journal =
        SqliteJournal::open(&root.path().join("journal"), device.authority_id()).unwrap();
    assert_eq!(
        execute(
            &mut journal,
            &mut device,
            "owner",
            &request,
            None,
            deadline()
        )
        .unwrap()
        .state,
        OperationState::Unknown
    );
    let confirmed = reconcile(
        &mut journal,
        &mut device,
        "owner",
        &request.request_id,
        deadline(),
    )
    .unwrap();
    assert_eq!(confirmed.state, OperationState::Succeeded);
    assert_eq!(device.invoke_calls, 0);
    assert_eq!(device.writes().unwrap(), 1);
}

#[test]
fn effect_without_receipt_stays_unknown_and_fences_the_target() {
    let (_root, mut device, mut journal, request, proposed) = setup();
    let token = journal.approve("owner", &proposed, deadline()).unwrap();
    device.fault = Fault::EffectWithoutReceipt;
    let unknown = execute(
        &mut journal,
        &mut device,
        "owner",
        &request,
        Some(&token),
        deadline(),
    )
    .unwrap();
    assert_eq!(unknown.state, OperationState::Unknown);
    assert_eq!(
        reconcile(
            &mut journal,
            &mut device,
            "owner",
            &request.request_id,
            deadline()
        )
        .unwrap()
        .state,
        OperationState::Unknown
    );
    let next = device.request("next", 50, deadline()).unwrap();
    let next_plan = plan(&mut device, &next);
    let token = journal.approve("owner", &next_plan, deadline()).unwrap();
    assert_eq!(
        execute(
            &mut journal,
            &mut device,
            "owner",
            &next,
            Some(&token),
            deadline()
        )
        .unwrap_err(),
        "target_fenced_by_unresolved_operation"
    );
    // Even a direct duplicate at the adapter must not repeat the uncertain effect.
    device
        .invoke(&unknown.operation_id, &proposed.steps[0], deadline())
        .unwrap();
    assert_eq!(device.writes().unwrap(), 1);
}

#[test]
fn confirmed_failure_is_terminal_and_does_not_repeat() {
    let (_root, mut device, mut journal, request, proposed) = setup();
    let token = journal.approve("owner", &proposed, deadline()).unwrap();
    device.fault = Fault::RejectBeforeEffect;
    assert_eq!(
        execute(
            &mut journal,
            &mut device,
            "owner",
            &request,
            Some(&token),
            deadline()
        )
        .unwrap()
        .state,
        OperationState::Failed
    );
    execute(
        &mut journal,
        &mut device,
        "owner",
        &request,
        None,
        deadline(),
    )
    .unwrap();
    assert_eq!(device.invoke_calls, 1);
    assert_eq!(device.writes().unwrap(), 0);
}

#[test]
fn predispatch_cancellation_is_a_durable_fence() {
    let (_root, mut device, mut journal, request, proposed) = setup();
    let token = journal.approve("owner", &proposed, deadline()).unwrap();
    let Claim::New(record) = journal
        .claim("owner", &proposed, Some(&token), true, deadline())
        .unwrap()
    else {
        panic!()
    };
    journal
        .cancel("owner", &request.request_id, deadline())
        .unwrap();
    assert_eq!(
        journal
            .dispatch_intent(&record.operation_id, deadline())
            .unwrap()
            .state,
        OperationState::CancelledBeforeDispatch
    );
    assert_eq!(
        execute(
            &mut journal,
            &mut device,
            "owner",
            &request,
            None,
            deadline()
        )
        .unwrap()
        .state,
        OperationState::CancelledBeforeDispatch
    );
    assert_eq!(device.invoke_calls, 0);
}

#[test]
fn cancellation_after_dispatch_does_not_claim_undo() {
    let (_root, mut device, mut journal, request, proposed) = setup();
    let token = journal.approve("owner", &proposed, deadline()).unwrap();
    device.fault = Fault::LostAcknowledgement;
    execute(
        &mut journal,
        &mut device,
        "owner",
        &request,
        Some(&token),
        deadline(),
    )
    .unwrap();
    assert_eq!(
        journal
            .cancel("owner", &request.request_id, deadline())
            .unwrap()
            .state,
        OperationState::Unknown
    );
    assert_eq!(device.volume().unwrap(), 40);
    assert_eq!(
        reconcile(
            &mut journal,
            &mut device,
            "owner",
            &request.request_id,
            deadline()
        )
        .unwrap()
        .state,
        OperationState::Succeeded
    );
}

#[test]
fn expired_admission_and_timed_out_device_do_not_apply_effects() {
    let (_root, mut device, mut journal, mut request, _) = setup();
    assert!(
        execute(
            &mut journal,
            &mut device,
            "owner",
            &request,
            None,
            Instant::now()
        )
        .is_err()
    );
    assert_eq!(device.invoke_calls, 0);
    request.budget_ms = 150;
    let proposed = plan(&mut device, &request);
    let token = journal.approve("owner", &proposed, deadline()).unwrap();
    device.fault = Fault::Delay(Duration::from_secs(1));
    assert!(
        execute(
            &mut journal,
            &mut device,
            "owner",
            &request,
            Some(&token),
            deadline()
        )
        .is_err()
    );
    assert_eq!(device.writes().unwrap(), 0);
}

#[test]
fn failed_receipt_persistence_keeps_intent_for_reconciliation() {
    let (root, mut device, mut journal, request, proposed) = setup();
    let token = journal.approve("owner", &proposed, deadline()).unwrap();
    let db = rusqlite::Connection::open(root.path().join("journal/journal-v2.sqlite")).unwrap();
    db.execute_batch(
        "CREATE TRIGGER fail_receipt BEFORE UPDATE ON operations WHEN NEW.state='succeeded'
        BEGIN SELECT RAISE(FAIL,'simulated_receipt_write_failure'); END;",
    )
    .unwrap();
    assert!(
        execute(
            &mut journal,
            &mut device,
            "owner",
            &request,
            Some(&token),
            deadline()
        )
        .is_err()
    );
    assert_eq!(device.writes().unwrap(), 1);
    assert_eq!(
        journal
            .lookup("owner", &request.request_id, deadline())
            .unwrap()
            .unwrap()
            .state,
        OperationState::Dispatching
    );
    db.execute_batch("DROP TRIGGER fail_receipt;").unwrap();
    assert_eq!(
        reconcile(
            &mut journal,
            &mut device,
            "owner",
            &request.request_id,
            deadline()
        )
        .unwrap()
        .state,
        OperationState::Succeeded
    );
    assert_eq!(device.invoke_calls, 1);
}

#[test]
fn failed_claim_persistence_rolls_back_approval_consumption() {
    let (root, mut device, mut journal, request, proposed) = setup();
    let token = journal.approve("owner", &proposed, deadline()).unwrap();
    let db = rusqlite::Connection::open(root.path().join("journal/journal-v2.sqlite")).unwrap();
    db.execute_batch("CREATE TRIGGER fail_claim BEFORE INSERT ON operations BEGIN SELECT RAISE(FAIL,'claim_write_failure'); END;").unwrap();
    assert!(
        execute(
            &mut journal,
            &mut device,
            "owner",
            &request,
            Some(&token),
            deadline()
        )
        .is_err()
    );
    assert_eq!(device.invoke_calls, 0);
    db.execute_batch("DROP TRIGGER fail_claim;").unwrap();
    execute(
        &mut journal,
        &mut device,
        "owner",
        &request,
        Some(&token),
        deadline(),
    )
    .unwrap();
    assert_eq!(device.writes().unwrap(), 1);
}

#[test]
fn replaced_device_cannot_reconcile_an_old_operation() {
    let (root, mut device, mut journal, request, proposed) = setup();
    let token = journal.approve("owner", &proposed, deadline()).unwrap();
    device.fault = Fault::LostAcknowledgement;
    execute(
        &mut journal,
        &mut device,
        "owner",
        &request,
        Some(&token),
        deadline(),
    )
    .unwrap();
    let mut replacement = Simulator::open(&root.path().join("replacement.sqlite")).unwrap();
    assert!(
        reconcile(
            &mut journal,
            &mut replacement,
            "owner",
            &request.request_id,
            deadline()
        )
        .is_err()
    );
    assert_eq!(replacement.invoke_calls, 0);
}

#[test]
fn exclusive_owners_and_wrong_authority_are_rejected() {
    let (root, device, journal, _, _) = setup();
    assert!(SqliteJournal::open(&root.path().join("journal"), device.authority_id()).is_err());
    assert!(Simulator::open(&root.path().join("device.sqlite")).is_err());
    drop(journal);
    assert!(SqliteJournal::open(&root.path().join("journal"), "wrong-authority").is_err());
}

#[test]
fn revoked_or_expired_approval_after_claim_blocks_dispatch() {
    for expire in [false, true] {
        let (root, mut device, mut journal, request, proposed) = setup();
        let token = journal.approve("owner", &proposed, deadline()).unwrap();
        let Claim::New(record) = journal
            .claim("owner", &proposed, Some(&token), true, deadline())
            .unwrap()
        else {
            panic!()
        };
        if expire {
            let db =
                rusqlite::Connection::open(root.path().join("journal/journal-v2.sqlite")).unwrap();
            db.execute("UPDATE approvals SET expires_ms=0", []).unwrap();
        } else {
            journal.revoke(&token, deadline()).unwrap();
        }
        assert_eq!(
            journal
                .dispatch_intent(&record.operation_id, deadline())
                .unwrap()
                .state,
            OperationState::CancelledBeforeDispatch
        );
        assert_eq!(
            execute(
                &mut journal,
                &mut device,
                "owner",
                &request,
                Some(&token),
                deadline()
            )
            .unwrap()
            .state,
            OperationState::CancelledBeforeDispatch
        );
        assert_eq!(device.invoke_calls, 0);
    }
}

#[test]
fn fresh_policy_check_after_claim_stops_a_write() {
    struct Changed<'a> {
        device: &'a mut Simulator,
        observations: usize,
    }
    impl Adapter for Changed<'_> {
        fn observe(
            &mut self,
            deadline: Instant,
        ) -> edge_contracts::Result<edge_core::PreviewContext> {
            self.observations += 1;
            let mut context = self.device.observe(deadline)?;
            if self.observations == 2 {
                context.policy.allowed_actions.clear();
            }
            Ok(context)
        }
        fn invoke(
            &mut self,
            id: &str,
            step: &edge_core::PlanStep,
            deadline: Instant,
        ) -> edge_contracts::Result<edge_core::execution::Receipt> {
            self.device.invoke(id, step, deadline)
        }
        fn reconcile(
            &mut self,
            id: &str,
            deadline: Instant,
        ) -> edge_contracts::Result<edge_core::execution::Receipt> {
            self.device.reconcile(id, deadline)
        }
    }
    let (_root, mut device, mut journal, request, proposed) = setup();
    let token = journal.approve("owner", &proposed, deadline()).unwrap();
    let mut changing = Changed {
        device: &mut device,
        observations: 0,
    };
    assert_eq!(
        execute(
            &mut journal,
            &mut changing,
            "owner",
            &request,
            Some(&token),
            deadline()
        )
        .unwrap()
        .state,
        OperationState::CancelledBeforeDispatch
    );
    assert_eq!(device.invoke_calls, 0);
}

#[test]
fn malformed_acknowledgement_is_unknown_until_valid_receipt_reconciliation() {
    let (_root, mut device, mut journal, request, proposed) = setup();
    let token = journal.approve("owner", &proposed, deadline()).unwrap();
    device.fault = Fault::MalformedReceipt;
    assert_eq!(
        execute(
            &mut journal,
            &mut device,
            "owner",
            &request,
            Some(&token),
            deadline()
        )
        .unwrap()
        .state,
        OperationState::Unknown
    );
    assert_eq!(
        reconcile(
            &mut journal,
            &mut device,
            "owner",
            &request.request_id,
            deadline()
        )
        .unwrap()
        .state,
        OperationState::Succeeded
    );
    assert_eq!(device.writes().unwrap(), 1);
}

#[test]
fn read_uses_policy_without_a_write_token_and_terminal_receipt_is_immutable() {
    let (_root, mut device, mut journal, mut request, _) = setup();
    if let RequestInput::Action {
        action, parameters, ..
    } = &mut request.input
    {
        *action = "audio.volume.get".into();
        parameters.clear();
    }
    let record = execute(
        &mut journal,
        &mut device,
        "owner",
        &request,
        None,
        deadline(),
    )
    .unwrap();
    assert_eq!(record.state, OperationState::Succeeded);
    assert_eq!(device.writes().unwrap(), 0);
    assert!(
        journal
            .finish(
                &record.operation_id,
                edge_core::execution::Receipt::Failed {
                    reason: "forged_failure".into()
                },
                deadline()
            )
            .is_err()
    );
}
