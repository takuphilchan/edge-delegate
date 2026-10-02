use std::{path::PathBuf, process::Command};

struct EmptyDirectory(PathBuf);

impl EmptyDirectory {
    fn new() -> Self {
        use std::sync::atomic::{AtomicUsize, Ordering};
        static NEXT: AtomicUsize = AtomicUsize::new(0);
        loop {
            let path = std::env::temp_dir().join(format!(
                "edge-cli-help-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
            match std::fs::create_dir(&path) {
                Ok(()) => return Self(path),
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
                Err(error) => panic!("cannot create help test directory: {error}"),
            }
        }
    }
}

impl Drop for EmptyDirectory {
    fn drop(&mut self) {
        // Remove only our empty directory; never recursively delete unexpected files.
        let _ = std::fs::remove_dir(&self.0);
    }
}

fn command_help(command: &str, expected: &[&str]) {
    let directory = EmptyDirectory::new();
    let output = Command::new(env!("CARGO_BIN_EXE_edgectl"))
        .args([command, "--help"])
        .current_dir(&directory.0)
        .output()
        .unwrap();
    assert!(output.status.success(), "{command}: {output:?}");
    assert!(output.stderr.is_empty(), "{command}: {output:?}");
    assert_eq!(std::fs::read_dir(&directory.0).unwrap().count(), 0);
    let text = String::from_utf8(output.stdout).unwrap();
    for fragment in expected {
        assert!(
            text.contains(fragment),
            "{command} missing {fragment:?}: {text}"
        );
    }
    assert!(text.contains("Example:"));
    assert!(text.contains("flag order shown"));
    assert!(text.contains("Linux/WSL"));
}

#[test]
fn preview_help_explains_both_nonexecuting_forms() {
    command_help(
        "preview",
        &[
            "edgectl preview --request FILE --context FILE",
            "edgectl preview --request FILE --directory PRIVATE_DIRECTORY",
            "Offline preview",
            "does not authorize or execute",
            "request.json --context context.json",
        ],
    );
}

#[test]
fn capabilities_help_identifies_saved_context_service() {
    command_help(
        "capabilities",
        &[
            "edgectl capabilities --directory PRIVATE_DIRECTORY",
            "saved-context preview service",
            "does not authorize or execute",
            "not v2 execution discovery",
            "edgectl capabilities --directory /tmp/edge-preview",
        ],
    );
}

#[test]
fn service_help_explains_v1_approval_and_enrollment() {
    command_help(
        "service",
        &[
            "edgectl service --directory PRIVATE_DIRECTORY --credential FILE --command FILE [--save-credential NEW_FILE]",
            "v1 simulated volume",
            "Owner approval and client submission are separate",
            "JSON file",
            "required only for enrollment",
            "no native audio",
            "edgectl service --directory /tmp/edge-v1 --credential client.json --command status.json",
        ],
    );
}

#[test]
fn workspace_help_explains_v2_notes_and_credential_separation() {
    command_help(
        "workspace-service",
        &[
            "edgectl workspace-service --directory PRIVATE_V2_DIRECTORY --credential FILE --command FILE [--save-credential NEW_FILE]",
            "v2 real app-owned notes",
            "Owner approval and client submission are separate",
            "JSON file",
            "required only for enrollment",
            "no native audio",
            "credentials and state directory are separate from v1",
            "edgectl workspace-service --directory /tmp/edge-v2 --credential client-v2.json --command status.json",
        ],
    );
}

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
    for args in [
        vec!["execute"],
        vec!["preview", "--execute"],
        vec!["unknown", "--help"],
        vec!["preview", "--help", "extra"],
        vec!["capabilities", "--help", "extra"],
        vec!["service", "--help", "extra"],
        vec!["workspace-service", "--help", "extra"],
    ] {
        let output = Command::new(env!("CARGO_BIN_EXE_edgectl"))
            .args(args)
            .output()
            .unwrap();
        assert_eq!(output.status.code(), Some(2));
        assert!(output.stdout.is_empty());
        assert!(!output.stderr.is_empty());
    }
}

#[test]
fn help_states_the_boundary() {
    let output = Command::new(env!("CARGO_BIN_EXE_edgectl"))
        .arg("--help")
        .output()
        .unwrap();
    assert!(output.status.success());
    assert!(output.stderr.is_empty());
    let no_arguments = Command::new(env!("CARGO_BIN_EXE_edgectl"))
        .output()
        .unwrap();
    assert!(no_arguments.status.success());
    assert!(no_arguments.stderr.is_empty());
    assert_eq!(no_arguments.stdout, output.stdout);
    assert!(
        String::from_utf8(output.stdout)
            .unwrap()
            .contains("No model, live authorization")
    );
}
