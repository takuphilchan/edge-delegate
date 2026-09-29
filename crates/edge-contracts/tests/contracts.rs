use edge_contracts::{
    ControlRequest, MAX_FRAME_BYTES, Parameter, canonical_bytes, decimal, digest, parse_json,
};
use serde_json::{Value, json};

const REQUEST: &[u8] = include_bytes!("../../../conformance/contracts/preview-v2/request.json");

#[test]
fn zero_field_catalog_rule_does_not_ignore_extra_fields() {
    use edge_contracts::preview::ParameterRule;
    let rule: ParameterRule = parse_json(br#"{"type":"boolean"}"#).unwrap();
    assert_eq!(
        serde_json::to_value(rule).unwrap(),
        json!({"type": "boolean"})
    );
    assert!(parse_json::<ParameterRule>(br#"{"type":"boolean","execute":true}"#).is_err());
}

#[test]
fn shared_golden_round_trip_and_hash() {
    let request = ControlRequest::parse(REQUEST).unwrap();
    let expected: Value = parse_json(include_bytes!(
        "../../../conformance/contracts/preview-v2/canonical.json"
    ))
    .unwrap();
    assert_eq!(
        String::from_utf8(canonical_bytes(&request).unwrap()).unwrap(),
        expected["canonical_utf8"]
    );
    assert_eq!(digest(&request).unwrap(), expected["sha256"]);
    assert_eq!(
        ControlRequest::parse(&serde_json::to_vec(&request).unwrap()).unwrap(),
        request
    );
}

#[test]
fn strict_json_rejects_duplicates_at_every_level_and_trailing_data() {
    for text in [
        r#"{"a":1,"a":2}"#,
        r#"{"outer":{"a":1,"a":2}}"#,
        r#"[{"a":1,"\u0061":2}]"#,
        "{} {}",
        "NaN",
        "[Infinity]",
        "{\"a\":1e999}",
    ] {
        assert!(parse_json::<Value>(text.as_bytes()).is_err(), "{text}");
    }
}

#[test]
fn frame_utf8_and_nesting_are_bounded() {
    assert!(parse_json::<Value>(&vec![b' '; MAX_FRAME_BYTES + 1]).is_err());
    assert!(parse_json::<Value>(&[0xff]).is_err());
    assert!(
        parse_json::<Value>(format!("{}0{}", "[".repeat(200), "]".repeat(200)).as_bytes()).is_err()
    );
}

#[test]
fn unknown_fields_rejected_in_envelope_input_target_and_parameters() {
    for path in ["", "/input", "/input/target", "/input/parameters/percent"] {
        let mut value: Value = serde_json::from_slice(REQUEST).unwrap();
        value
            .pointer_mut(path)
            .unwrap()
            .as_object_mut()
            .unwrap()
            .insert("unexpected".into(), json!(true));
        assert!(
            ControlRequest::parse(&serde_json::to_vec(&value).unwrap()).is_err(),
            "{path}"
        );
    }
}

#[test]
fn malformed_requests_are_not_defaulted_into_valid_requests() {
    for (pointer, replacement) in [
        ("/schema_version", json!("edge-control-request.v1")),
        ("/budget_ms", json!(0)),
        ("/budget_ms", json!(5001)),
        ("/budget_ms", json!(true)),
        ("/request_id", json!("")),
        ("/request_id", json!("../../shell")),
        ("/input/target/authority_id", json!("another-device")),
        ("/input/target/catalog_sha256", json!("a")),
        ("/input/target/registration_generation", json!(-1)),
        ("/input/parameters/percent/value", json!(true)),
        ("/input/parameters/percent/value", json!(40.5)),
        (
            "/input/parameters/percent/value",
            json!(9_007_199_254_740_992_i64),
        ),
    ] {
        let mut value: Value = serde_json::from_slice(REQUEST).unwrap();
        *value.pointer_mut(pointer).unwrap() = replacement;
        assert!(
            ControlRequest::parse(&serde_json::to_vec(&value).unwrap()).is_err(),
            "{pointer}"
        );
    }
    let mut value: Value = serde_json::from_slice(REQUEST).unwrap();
    value.as_object_mut().unwrap().remove("budget_ms");
    assert!(ControlRequest::parse(&serde_json::to_vec(&value).unwrap()).is_err());
}

#[test]
fn text_limit_counts_utf8_bytes_not_characters() {
    let mut request = ControlRequest::parse(REQUEST).unwrap();
    for text in [" ".into(), "a\0b".into(), "é".repeat(2049)] {
        request.input = edge_contracts::RequestInput::Text { text };
        assert!(request.validate().is_err());
    }
    request.input = edge_contracts::RequestInput::Text {
        text: "é".repeat(2048),
    };
    request.validate().unwrap();
}

#[test]
fn decimals_are_exact_strings_with_one_canonical_form() {
    for value in ["0", "12", "-3.5", "0.01", "-0.01", "1000"] {
        decimal(value).unwrap();
    }
    for value in [
        "", "-", "+1", "01", "-0", "-0.0", "1.0", "1.", ".5", "1e2", "1,000", "NaN", "1.2.3", "１",
    ] {
        assert!(decimal(value).is_err(), "{value}");
    }
    Parameter::Decimal {
        value: "-3.5".into(),
        unit: "celsius".into(),
    }
    .validate()
    .unwrap();
}

#[test]
fn canonicalizer_rejects_ambiguous_numbers_and_sorts_objects() {
    for value in [
        json!(1.5),
        json!(9_007_199_254_740_992_u64),
        json!({"é": 1}),
    ] {
        assert!(canonical_bytes(&value).is_err());
    }
    assert_eq!(
        canonical_bytes(&json!({"z": "é", "a": {"b": 1}})).unwrap(),
        "{\"a\":{\"b\":1},\"z\":\"é\"}".as_bytes()
    );
}
