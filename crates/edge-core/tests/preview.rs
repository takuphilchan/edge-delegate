use edge_contracts::{ControlRequest, Parameter, RequestInput, digest, parse_json};
use edge_core::{PreviewContext, PreviewDecision, preview};

fn fixture() -> (ControlRequest, PreviewContext) {
    (
        ControlRequest::parse(include_bytes!(
            "../../../conformance/contracts/preview-v2/request.json"
        ))
        .unwrap(),
        parse_json(include_bytes!(
            "../../../conformance/contracts/preview-v2/context.json"
        ))
        .unwrap(),
    )
}

fn reason(request: &ControlRequest, context: &PreviewContext) -> String {
    match preview(request, context).unwrap().decision {
        PreviewDecision::Rejected { reason } => reason,
        other => panic!("expected rejection, got {other:?}"),
    }
}

#[test]
fn writes_are_previewed_without_authorizing_or_executing() {
    let (request, context) = fixture();
    let output = preview(&request, &context).unwrap();
    assert!(!output.execution_attempted);
    let PreviewDecision::Proposed {
        plan,
        plan_sha256,
        requires_approval,
    } = output.decision
    else {
        panic!()
    };
    assert!(requires_approval);
    assert_eq!(plan.schema_version, "edge-plan.v2");
    assert_eq!(plan_sha256, digest(&plan).unwrap());
    assert_eq!(plan.steps.len(), 1);
    assert_eq!(plan.steps[0].timeout_ms, 1000);
}

#[test]
fn identical_previews_are_deterministic_and_parameter_changes_change_hash() {
    let (mut request, context) = fixture();
    let a = serde_json::to_value(preview(&request, &context).unwrap()).unwrap();
    assert_eq!(
        a,
        serde_json::to_value(preview(&request, &context).unwrap()).unwrap()
    );
    if let RequestInput::Action { parameters, .. } = &mut request.input {
        parameters.insert("percent".into(), Parameter::Integer { value: 41 });
    }
    let b = serde_json::to_value(preview(&request, &context).unwrap()).unwrap();
    assert_ne!(a["decision"]["plan_sha256"], b["decision"]["plan_sha256"]);
}

#[test]
fn both_action_and_target_must_be_allowed() {
    let (request, mut context) = fixture();
    context.policy.allowed_actions.clear();
    assert_eq!(reason(&request, &context), "policy_denied");
    let (request, mut context) = fixture();
    context.policy.allowed_endpoints.clear();
    assert_eq!(reason(&request, &context), "policy_denied");
}

#[test]
fn target_generations_and_catalog_cannot_drift() {
    for which in 0..3 {
        let (mut request, context) = fixture();
        if let RequestInput::Action { target, .. } = &mut request.input {
            match which {
                0 => target.registration_generation += 1,
                1 => target.observation_generation += 1,
                _ => target.catalog_sha256 = "b".repeat(64),
            }
        }
        assert_eq!(reason(&request, &context), "repreview_required");
    }
    let (request, mut context) = fixture();
    context.endpoints[0].actions[1].effect = edge_core::Effect::Read;
    assert!(preview(&request, &context).is_err());
}

#[test]
fn invalid_parameters_do_not_become_actions() {
    for parameters in [
        vec![],
        vec![("percent", Parameter::Integer { value: 101 })],
        vec![("percent", Parameter::Boolean { value: true })],
        vec![
            ("percent", Parameter::Integer { value: 40 }),
            (
                "shell",
                Parameter::String {
                    value: "ignored?".into(),
                },
            ),
        ],
    ] {
        let (mut request, context) = fixture();
        if let RequestInput::Action { parameters: p, .. } = &mut request.input {
            *p = parameters.into_iter().map(|(k, v)| (k.into(), v)).collect();
        }
        assert_eq!(reason(&request, &context), "invalid_parameters");
    }
}

#[test]
fn duplicates_and_invalid_context_versions_fail_closed() {
    let (request, mut context) = fixture();
    context.endpoints.push(context.endpoints[0].clone());
    assert!(preview(&request, &context).is_err());
    let (request, mut context) = fixture();
    let duplicate = context.endpoints[0].actions[0].clone();
    context.endpoints[0].actions.push(duplicate);
    context.endpoints[0].binding.catalog_sha256 = digest(&context.endpoints[0].actions).unwrap();
    assert!(preview(&request, &context).is_err());
    let (request, mut context) = fixture();
    context.schema_version = "newer-unrecognized-version".into();
    assert!(preview(&request, &context).is_err());
}

#[test]
fn text_is_not_silently_interpreted_as_an_action() {
    let (mut request, context) = fixture();
    request.input = RequestInput::Text {
        text: "Set volume to 40".into(),
    };
    assert!(matches!(
        preview(&request, &context).unwrap().decision,
        PreviewDecision::ClarificationRequired { .. }
    ));
}

#[test]
fn request_budget_caps_step_duration_and_reads_need_no_write_approval() {
    let (mut request, context) = fixture();
    request.budget_ms = 100;
    if let RequestInput::Action {
        action, parameters, ..
    } = &mut request.input
    {
        *action = "audio.volume.get".into();
        parameters.clear();
    }
    let PreviewDecision::Proposed {
        plan,
        requires_approval,
        ..
    } = preview(&request, &context).unwrap().decision
    else {
        panic!()
    };
    assert!(!requires_approval);
    assert_eq!(plan.steps[0].timeout_ms, 100);
}
