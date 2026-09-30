//! Owner-run adapter demonstration, not an authenticated SDK/service example.
#[cfg(target_os = "linux")]
fn run() -> Result<(), Box<dyn std::error::Error>> {
    use edge_contracts::{
        Parameter,
        actions::{Output, Receipt, Request},
    };
    use edge_core::actions::{Adapter, Permission, Policy, compile};
    use edge_workspace::Workspace;
    use std::{
        io::{self, BufRead, Read, Write},
        path::PathBuf,
        time::{Duration, Instant},
    };
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    let [directory] = args.as_slice() else {
        return Err("usage: notes NEW_PRIVATE_DIRECTORY".into());
    };
    let mut notes = Workspace::open(&PathBuf::from(directory), "workspace-example", "notes")?;
    let id = uuid::Uuid::new_v4().to_string();
    let mut request = Request {
        schema_version: "edge-action-request.v1".into(),
        request_id: id.clone(),
        target: notes.describe()?.binding,
        action: "notes.create".into(),
        parameters: [
            (
                "title".into(),
                Parameter::String {
                    value: "Workspace session".into(),
                },
            ),
            (
                "body".into(),
                Parameter::String {
                    value: "A real note stored by the workspace adapter.".into(),
                },
            ),
        ]
        .into(),
        budget_ms: 2000,
    };
    let policy = Policy {
        authority_id: "workspace-example".into(),
        principal: "example-owner".into(),
        revision: 1,
        permissions: vec![
            Permission {
                endpoint: "notes".into(),
                action: "notes.create".into(),
            },
            Permission {
                endpoint: "notes".into(),
                action: "notes.read".into(),
            },
        ],
    };
    let plan = compile(&request, &[notes.describe()?], &policy)?;
    println!("Trusted adapter example only. No authenticated v2 service or native controls.");
    println!(
        "Operation ID: {id}\n{}",
        serde_json::to_string_pretty(&plan)?
    );
    print!("Type create to persist this note, or Enter to decline: ");
    io::stdout().flush()?;
    let mut answer = String::new();
    io::stdin().lock().take(64).read_line(&mut answer)?;
    if answer.trim_end_matches(['\r', '\n']) != "create" {
        println!("Declined; no note created.");
        return Ok(());
    }
    let receipt = notes.invoke(
        "example-owner",
        &id,
        &request,
        Instant::now() + Duration::from_secs(2),
    )?;
    let Receipt::Succeeded {
        output:
            Output::Scalar {
                value: Parameter::Resource { value: note_id },
            },
        ..
    } = receipt
    else {
        return Err("note creation not confirmed; preserve state and operation ID".into());
    };
    println!("Created note: {note_id}");
    request.request_id = format!("read-{id}");
    request.action = "notes.read".into();
    request.parameters = [("note_id".into(), Parameter::Resource { value: note_id })].into();
    compile(&request, &[notes.describe()?], &policy)?;
    println!(
        "{}",
        serde_json::to_string_pretty(&notes.invoke(
            "example-owner",
            &request.request_id,
            &request,
            Instant::now() + Duration::from_secs(2)
        )?)?
    );
    println!(
        "State retained. Each new invocation creates a different request; do not blindly rerun after uncertainty."
    );
    Ok(())
}
#[cfg(not(target_os = "linux"))]
fn run() -> Result<(), Box<dyn std::error::Error>> {
    Err("Notes storage currently requires Linux/WSL; Windows ACL support is pending.".into())
}
fn main() -> std::process::ExitCode {
    match run() {
        Ok(()) => std::process::ExitCode::SUCCESS,
        Err(error) => {
            eprintln!(
                "error: {error}. Preserve storage; do not reset or blindly repeat uncertain work."
            );
            std::process::ExitCode::FAILURE
        }
    }
}
