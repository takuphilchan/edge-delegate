use edge_protocol::execution::{Command, Request};
#[test]
fn execution_commands_reject_unknown_fields_and_client_principal_injection() {
    for bytes in [
        br#"{"method":"submit","request_id":"x","principal":"owner"}"#.as_slice(),
        br#"{"method":"preview_volume","percent":40,"budget_ms":2000,"execute":true}"#,
        br#"{"method":"preview_volume","percent":40,"percent":99,"budget_ms":2000}"#,
        br#"{"method":"shell","command":"anything"}"#,
    ] {
        assert!(edge_contracts::parse_json::<Command>(bytes).is_err());
    }
}
#[test]
fn execution_envelope_and_values_are_explicitly_bounded() {
    for command in [
        Command::PreviewVolume {
            percent: 101,
            budget_ms: 2000,
        },
        Command::PreviewVolume {
            percent: 40,
            budget_ms: 5001,
        },
        Command::Enroll {
            principal: "owner".into(),
            scope: edge_protocol::execution::Scope::Control,
        },
        Command::Submit {
            request_id: "x".repeat(129),
        },
    ] {
        assert!(command.validate().is_err());
    }
    let mut request = Request {
        schema_version: edge_protocol::execution::VERSION.into(),
        call_id: "one".into(),
        credential: "a".repeat(64),
        command: Command::Capabilities {},
    };
    request.validate().unwrap();
    request.schema_version = "edge-service-envelope.v1".into();
    assert!(request.validate().is_err());
}
