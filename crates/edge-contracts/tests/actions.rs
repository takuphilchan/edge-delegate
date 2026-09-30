use edge_contracts::actions::*;
use edge_contracts::preview::{Effect, ParameterRule};
use edge_contracts::{Evidence, Parameter, canonical_bytes, digest, parse_json};
use serde_json::{Value, json};

fn fixtures() -> Vec<Value> {
    parse_json(include_bytes!(
        "../../../conformance/execution-v2/action-vectors.json"
    ))
    .unwrap()
}
fn request() -> Request {
    Request::parse(fixtures()[0]["canonical_utf8"].as_str().unwrap().as_bytes()).unwrap()
}
fn boolean() -> FieldRule {
    FieldRule::Scalar {
        rule: ParameterRule::Boolean {},
    }
}
#[test]
fn both_action_families_have_stable_canonical_hashes() {
    for fixture in fixtures() {
        let request =
            Request::parse(fixture["canonical_utf8"].as_str().unwrap().as_bytes()).unwrap();
        assert_eq!(
            String::from_utf8(canonical_bytes(&request).unwrap()).unwrap(),
            fixture["canonical_utf8"]
        );
        assert_eq!(digest(&request).unwrap(), fixture["sha256"]);
        assert!(
            edge_contracts::ControlRequest::parse(
                fixture["canonical_utf8"].as_str().unwrap().as_bytes()
            )
            .is_err()
        );
    }
}
#[test]
fn malformed_execution_requests_do_not_default_to_valid_actions() {
    let original = serde_json::to_value(request()).unwrap();
    for (field, value) in [
        ("schema_version", json!("edge-control-request.v2")),
        ("budget_ms", json!(0)),
        ("budget_ms", json!(5001)),
        ("principal", json!("owner")),
        ("action", json!("notes create")),
    ] {
        let mut bad = original.clone();
        bad[field] = value;
        assert!(Request::parse(&serde_json::to_vec(&bad).unwrap()).is_err());
    }
    let payload = fixtures()[0]["canonical_utf8"].as_str().unwrap().to_owned();
    assert!(
        Request::parse(
            payload
                .replacen(
                    "\"budget_ms\":2000",
                    "\"budget_ms\":2000,\"budget_ms\":2000",
                    1
                )
                .as_bytes()
        )
        .is_err()
    );
    let mut bad = original.clone();
    bad["parameters"]["body"]["value"] = json!("\0");
    assert!(Request::parse(&serde_json::to_vec(&bad).unwrap()).is_err());
    let mut bad = original;
    bad["target"]["extra"] = json!(true);
    assert!(Request::parse(&serde_json::to_vec(&bad).unwrap()).is_err());
}
#[test]
fn output_shapes_fields_and_cursors_are_checked() {
    let rule = OutputRule::Record {
        fields: [("ok".into(), boolean())].into(),
    };
    assert!(
        Output::Record {
            fields: [("ok".into(), Parameter::Boolean { value: true })].into()
        }
        .validate(&rule)
        .is_ok()
    );
    assert!(
        Output::Record {
            fields: [("other".into(), Parameter::Boolean { value: true })].into()
        }
        .validate(&rule)
        .is_err()
    );
    assert!(
        Output::Scalar {
            value: Parameter::Boolean { value: true }
        }
        .validate(&rule)
        .is_err()
    );
    let page = OutputRule::Page {
        fields: Default::default(),
        max_items: 1,
    };
    assert!(
        Output::Page {
            items: vec![Default::default(), Default::default()],
            next_cursor: None
        }
        .validate(&page)
        .is_err()
    );
    assert!(
        Output::Page {
            items: vec![],
            next_cursor: Some("../secret".into())
        }
        .validate(&page)
        .is_err()
    );
    assert!(
        OutputRule::Page {
            fields: Default::default(),
            max_items: 21
        }
        .validate()
        .is_err()
    );
    let fields = (0..16)
        .map(|n| {
            (
                format!("f{n}"),
                FieldRule::Scalar {
                    rule: ParameterRule::String { max_bytes: 4096 },
                },
            )
        })
        .collect();
    let values = (0..16)
        .map(|n| {
            (
                format!("f{n}"),
                Parameter::String {
                    value: "x".repeat(4096),
                },
            )
        })
        .collect();
    assert!(
        Output::Record { fields: values }
            .validate(&OutputRule::Record { fields })
            .is_err()
    );
}
#[test]
fn receipts_cannot_invent_evidence_or_claim_handoff_for_notes() {
    let action = Action {
        action: "test".into(),
        effect: Effect::Write,
        parameters: Default::default(),
        output: OutputRule::Scalar { rule: boolean() },
        max_duration_ms: 2000,
        expected_evidence: Evidence::DurableReceipt,
        allows_handoff: false,
    };
    let receipt = Receipt::Succeeded {
        output: Output::Scalar {
            value: Parameter::Boolean { value: true },
        },
        evidence: Evidence::IndependentObservation,
    };
    assert!(receipt.validate(&action).is_err());
    assert!(
        Receipt::HandedOff {
            evidence: Evidence::ApiAcknowledgement
        }
        .validate(&action)
        .is_err()
    );
    let mut launch = action;
    launch.allows_handoff = true;
    assert!(
        Receipt::HandedOff {
            evidence: Evidence::ApiAcknowledgement
        }
        .validate(&launch)
        .is_ok()
    );
    assert!(
        Receipt::HandedOff {
            evidence: Evidence::IndependentObservation
        }
        .validate(&launch)
        .is_err()
    );
}
