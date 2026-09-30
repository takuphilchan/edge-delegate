use edge_contracts::actions::*;
use edge_contracts::preview::{Effect, ParameterRule};
use edge_contracts::{Evidence, Parameter, TargetBinding, digest};
use edge_core::actions::{Permission, Policy, compile};

#[test]
fn discovery_filters_pairs_without_rehashing_bindings() {
    let (endpoints, mut policy, _) = fixture();
    policy.permissions.remove(0);
    let visible = edge_core::actions::discover(&endpoints, &policy).unwrap();
    assert_eq!(visible.len(), 1);
    assert_eq!(visible[0].target, endpoints[1].binding);
    assert_eq!(visible[0].definition.action, "notes.create");
    policy.permissions.clear();
    assert!(
        edge_core::actions::discover(&endpoints, &policy)
            .unwrap()
            .is_empty()
    );
}

fn fixture() -> (Vec<Endpoint>, Policy, Vec<Request>) {
    let mut endpoints = Vec::new();
    let mut requests = Vec::new();
    let mut permissions = Vec::new();
    for (endpoint, action, name, value, rule) in [
        (
            "output",
            "audio.volume.set",
            "percent",
            Parameter::Integer { value: 40 },
            ParameterRule::Integer {
                minimum: 0,
                maximum: 100,
            },
        ),
        (
            "notes",
            "notes.create",
            "body",
            Parameter::String {
                value: "café".into(),
            },
            ParameterRule::String { max_bytes: 4096 },
        ),
    ] {
        let actions = vec![Action {
            action: action.into(),
            effect: Effect::Write,
            parameters: [(name.into(), FieldRule::Scalar { rule })].into(),
            output: OutputRule::Scalar {
                rule: FieldRule::ResourceReference {},
            },
            max_duration_ms: 1000,
            expected_evidence: Evidence::DurableReceipt,
            allows_handoff: false,
        }];
        let binding = TargetBinding {
            authority_id: "host".into(),
            endpoint_id: endpoint.into(),
            registration_generation: 1,
            observation_generation: 0,
            catalog_sha256: digest(&actions).unwrap(),
        };
        requests.push(Request {
            schema_version: "edge-action-request.v1".into(),
            request_id: format!("{endpoint}-1"),
            target: binding.clone(),
            action: action.into(),
            parameters: [(name.into(), value)].into(),
            budget_ms: 2000,
        });
        endpoints.push(Endpoint { binding, actions });
        permissions.push(Permission {
            endpoint: endpoint.into(),
            action: action.into(),
        });
    }
    (
        endpoints,
        Policy {
            authority_id: "host".into(),
            principal: "alice".into(),
            revision: 1,
            permissions,
        },
        requests,
    )
}
#[test]
fn two_families_use_identical_compilation_and_bound_plans() {
    let (endpoints, policy, requests) = fixture();
    for request in requests {
        let plan = compile(&request, &endpoints, &policy).unwrap();
        plan.validate().unwrap();
        assert_eq!(plan.timeout_ms, 1000);
        assert_eq!(
            digest(&plan).unwrap(),
            digest(&compile(&request, &endpoints, &policy).unwrap()).unwrap()
        );
        let mut changed = plan.clone();
        changed.timeout_ms += 1;
        assert!(changed.validate().is_err());
        let mut changed = plan;
        changed.request.request_id = "replacement".into();
        assert!(changed.validate().is_err());
    }
}
#[test]
fn policy_pairs_are_exact_and_principal_revision_bind_the_plan() {
    let (endpoints, mut policy, requests) = fixture();
    let plan = compile(&requests[0], &endpoints, &policy).unwrap();
    policy.revision += 1;
    assert_ne!(
        digest(&plan).unwrap(),
        digest(&compile(&requests[0], &endpoints, &policy).unwrap()).unwrap()
    );
    policy.principal = "bob".into();
    assert_ne!(
        plan.policy_sha256,
        compile(&requests[0], &endpoints, &policy)
            .unwrap()
            .policy_sha256
    );
    policy.permissions[0].endpoint = "notes".into();
    assert_eq!(
        compile(&requests[0], &endpoints, &policy).unwrap_err(),
        "policy_denied"
    );
}
#[test]
fn stale_bindings_malformed_catalogs_and_extra_parameters_fail() {
    let (endpoints, policy, requests) = fixture();
    let mut stale = requests[0].clone();
    stale.target.observation_generation += 1;
    assert_eq!(
        compile(&stale, &endpoints, &policy).unwrap_err(),
        "repreview_required"
    );
    let mut extra = requests[0].clone();
    extra.parameters.insert(
        "shell".into(),
        Parameter::String {
            value: "anything".into(),
        },
    );
    assert!(compile(&extra, &endpoints, &policy).is_err());
    let mut corrupt = endpoints.clone();
    corrupt[0].actions[0].max_duration_ms += 1;
    assert!(compile(&requests[0], &corrupt, &policy).is_err());
    let mut duplicate = endpoints.clone();
    duplicate.push(endpoints[0].clone());
    assert!(compile(&requests[0], &duplicate, &policy).is_err());
    let mut wrong = requests[0].clone();
    wrong.target.authority_id = "other-host".into();
    assert!(compile(&wrong, &endpoints, &policy).is_err());
}
