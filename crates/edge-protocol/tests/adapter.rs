use edge_contracts::parse_json;
use edge_protocol::adapter::{ADAPTER_VERSION, AdapterCommand, AdapterReply, AdapterRequest};

#[test]
fn adapter_channel_validates_version_budget_and_call_identity() {
    let mut request = AdapterRequest {
        schema_version: ADAPTER_VERSION.into(),
        call_id: 1,
        budget_ms: 1000,
        command: AdapterCommand::Observe {},
    };
    assert!(request.validate().is_ok());
    for budget in [0, 5001, u32::MAX] {
        request.budget_ms = budget;
        assert!(request.validate().is_err());
    }
    request.budget_ms = 1000;
    request.call_id = 0;
    assert!(request.validate().is_err());
    request.call_id = 1;
    request.schema_version = "unknown".into();
    assert!(request.validate().is_err());
}

#[test]
fn adapter_zero_field_variants_and_unknown_commands_are_strict() {
    assert!(parse_json::<AdapterCommand>(br#"{"method":"observe"}"#).is_ok());
    for bytes in [
        br#"{"method":"observe","execute":true}"#.as_slice(),
        br#"{"method":"shell","command":"echo bad"}"#,
        br#"{"method":"observe","method":"invoke"}"#,
    ] {
        assert!(parse_json::<AdapterCommand>(bytes).is_err());
    }
    assert!(parse_json::<AdapterReply>(br#"{"kind":"unavailable","succeeded":true}"#).is_err());
}

#[test]
fn adapter_reconciliation_uses_bounded_opaque_operation_identity() {
    let mut request = AdapterRequest {
        schema_version: ADAPTER_VERSION.into(),
        call_id: 1,
        budget_ms: 1000,
        command: AdapterCommand::Reconcile {
            operation_id: "operation-1".into(),
        },
    };
    assert!(request.validate().is_ok());
    request.command = AdapterCommand::Reconcile {
        operation_id: "../database".into(),
    };
    assert!(request.validate().is_err());
}
