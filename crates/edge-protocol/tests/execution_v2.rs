use edge_protocol::{execution_v2::Request, read_frame, write_frame};
use serde_json::{Value, json};

#[test]
fn both_families_round_trip_and_v1_rejects_v2() {
    let fixtures: Vec<Value> = edge_contracts::parse_json(include_bytes!(
        "../../../conformance/execution-v2/action-vectors.json"
    ))
    .unwrap();
    for fixture in fixtures {
        let wire = json!({"schema_version":"edge-execution-service.v2","call_id":"call-1","credential":"a".repeat(64),"command":{"method":"preview","request":fixture["request"]}});
        let request = Request::parse(&serde_json::to_vec(&wire).unwrap()).unwrap();
        let mut bytes = Vec::new();
        write_frame(&mut bytes, &request).unwrap();
        let read: Request = read_frame(&mut &bytes[..]).unwrap().unwrap();
        read.validate().unwrap();
        assert_eq!(serde_json::to_value(read).unwrap(), wire);
        assert!(
            edge_contracts::parse_json::<edge_protocol::execution::Request>(
                &serde_json::to_vec(&wire).unwrap()
            )
            .is_err()
        );
    }
}
#[test]
fn malformed_calls_are_rejected_before_host_routing() {
    let original = json!({"schema_version":"edge-execution-service.v2","call_id":"call-1","credential":"a".repeat(64),"command":{"method":"status","request_id":"request-1"}});
    for (key, value) in [
        ("schema_version", json!("edge-execution-service.v1")),
        ("credential", json!("short")),
        ("principal", json!("owner")),
        (
            "command",
            json!({"method":"status","request_id":"request-1","principal":"owner"}),
        ),
        ("command", json!({"method":"events","after":0,"limit":101})),
        (
            "command",
            json!({"method":"capabilities","after":null,"limit":0}),
        ),
        (
            "command",
            json!({"method":"hello","minimum_version":1,"maximum_version":2}),
        ),
    ] {
        let mut bad = original.clone();
        bad[key] = value;
        assert!(Request::parse(&serde_json::to_vec(&bad).unwrap()).is_err());
    }
}

#[test]
fn enrollment_pairs_and_versions_are_strict_and_do_not_inherit_v1_scopes() {
    let original = json!({"schema_version":"edge-execution-service.v2","call_id":"enroll","credential":"a".repeat(64),"command":{"method":"enroll","principal":"app","permissions":[{"endpoint":"notes","action":"notes.create"}]}});
    Request::parse(&serde_json::to_vec(&original).unwrap()).unwrap();
    for command in [
        json!({"method":"enroll","principal":"owner","permissions":[]}),
        json!({"method":"enroll","principal":"app","scope":"control"}),
        json!({"method":"enroll","principal":"app","permissions":[{"endpoint":"notes","action":"notes.create"},{"endpoint":"notes","action":"notes.create"}]}),
        json!({"method":"revoke","principal":"owner"}),
    ] {
        let mut bad = original.clone();
        bad["command"] = command;
        assert!(Request::parse(&serde_json::to_vec(&bad).unwrap()).is_err());
    }
}
