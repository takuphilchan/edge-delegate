use std::{path::PathBuf, process::Command};

#[test]
fn preview_fixture_is_nonexecuting() {
    let root =
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../conformance/contracts/preview-v2");
    let output = Command::new(env!("CARGO_BIN_EXE_edgectl"))
        .arg("preview")
        .arg("--request")
        .arg(root.join("request.json"))
        .arg("--context")
        .arg(root.join("context.json"))
        .output()
        .unwrap();
    assert!(output.status.success(), "{:?}", output);
    let result: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(result["execution_attempted"], false);
    assert_eq!(result["decision"]["requires_approval"], true);
}

#[test]
fn execute_and_unknown_flags_are_not_supported() {
    for args in [vec!["execute"], vec!["preview", "--execute"]] {
        let output = Command::new(env!("CARGO_BIN_EXE_edgectl"))
            .args(args)
            .output()
            .unwrap();
        assert_eq!(output.status.code(), Some(2));
        assert!(output.stdout.is_empty());
    }
}

#[test]
fn help_states_the_boundary() {
    let output = Command::new(env!("CARGO_BIN_EXE_edgectl"))
        .arg("--help")
        .output()
        .unwrap();
    assert!(output.status.success());
    assert!(
        String::from_utf8(output.stdout)
            .unwrap()
            .contains("No model, live authorization")
    );
}
