//! Trusted notes authority embedding demonstration; not an authenticated IPC client.
#[cfg(target_os = "linux")]
fn run() -> Result<(), String> {
    use edge_contracts::actions::{Output, Receipt, Request};
    use edge_contracts::{Parameter, digest};
    use edge_core::actions::{Adapter, Permission};
    use edge_host::actions::ActionAuthority;
    use edge_workspace::Workspace;
    use std::io::{self, Write};
    use std::os::unix::fs::DirBuilderExt;
    let root = std::path::PathBuf::from(
        std::env::args()
            .nth(1)
            .ok_or("usage: notes_authority NEW_PRIVATE_DIRECTORY")?,
    );
    // Refuse to reuse a directory: this demo does not implement resume/recovery UI.
    std::fs::DirBuilder::new()
        .mode(0o700)
        .create(&root)
        .map_err(|e| e.to_string())?;
    let store = Workspace::open(&root.join("notes"), "demo-host", "notes")?;
    let target = store.describe()?.binding;
    let owner = ActionAuthority::open(&root.join("journal"), "demo-host", vec![Box::new(store)])?;
    let client = owner.enroll(
        "demo-client",
        ["notes.create", "notes.read", "notes.list"]
            .into_iter()
            .map(|action| Permission {
                endpoint: "notes".into(),
                action: action.into(),
            })
            .collect(),
    )?;
    let request = Request {
        schema_version: "edge-action-request.v1".into(),
        request_id: "session-note".into(),
        target: target.clone(),
        action: "notes.create".into(),
        budget_ms: 2000,
        parameters: [
            (
                "title".into(),
                Parameter::String {
                    value: "SDK session".into(),
                },
            ),
            (
                "body".into(),
                Parameter::String {
                    value: "A note created through the generic authority.".into(),
                },
            ),
        ]
        .into(),
    };
    let offered = client.preview(&request)?;
    println!("Trusted owner embedding; no IPC authentication or native device control.");
    println!(
        "Preview (no action yet): {}",
        serde_json::to_string_pretty(&offered).map_err(|e| e.to_string())?
    );
    print!("Type create to approve this exact note; anything else declines: ");
    io::stdout().flush().map_err(|e| e.to_string())?;
    let mut input = String::new();
    io::stdin()
        .read_line(&mut input)
        .map_err(|e| e.to_string())?;
    if input.trim() != "create" {
        client.cancel(&request.request_id)?;
        println!("Declined; no note created.");
        return Ok(());
    }
    let hash = digest(&offered.plan)?;
    owner.approve(&client, &request.request_id, &hash)?;
    let done = client.execute(&request.request_id, &hash)?;
    let Some(Receipt::Succeeded {
        output:
            Output::Scalar {
                value: Parameter::Resource { value: note_id },
            },
        ..
    }) = done.receipt
    else {
        return Err(format!(
            "Outcome {:?}; preserve {} for inspection. Do not repeat automatically.",
            done.state,
            root.display()
        ));
    };
    let read = Request {
        schema_version: "edge-action-request.v1".into(),
        request_id: "read-session-note".into(),
        target,
        action: "notes.read".into(),
        budget_ms: 2000,
        parameters: [("note_id".into(), Parameter::Resource { value: note_id })].into(),
    };
    let offered = client.preview(&read)?;
    let readback = client.execute(&read.request_id, &digest(&offered.plan)?)?;
    println!(
        "Readback: {}",
        serde_json::to_string_pretty(&readback).map_err(|e| e.to_string())?
    );
    println!(
        "Activity: {}",
        serde_json::to_string_pretty(&client.events(0, 100)?).map_err(|e| e.to_string())?
    );
    Ok(())
}
#[cfg(target_os = "linux")]
fn main() {
    if let Err(e) = run() {
        eprintln!("{e}");
        std::process::exit(1);
    }
}
#[cfg(not(target_os = "linux"))]
fn main() {
    eprintln!("This trusted embedding example currently requires Linux/WSL.");
    std::process::exit(2);
}
