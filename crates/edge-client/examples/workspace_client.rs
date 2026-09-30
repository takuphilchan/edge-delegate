//! Developer tutorial: owner setup and ordinary client calls are deliberately separate.
#[cfg(target_os = "linux")]
fn run() -> Result<(), String> {
    use edge_client::actions::{Command, GatewayClient, Permission, Reply};
    use edge_contracts::{
        Parameter,
        actions::{Output, Receipt, Request, State},
        digest,
    };
    use std::{
        io::{self, Write},
        path::Path,
    };
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.len() != 3 {
        return Err("usage: workspace_client SERVICE_DIRECTORY OWNER_CREDENTIAL REQUEST_ID".into());
    }
    edge_contracts::identifier(&args[2])?;
    let owner = GatewayClient::connect(Path::new(&args[0]), Path::new(&args[1]))
        .map_err(|e| e.to_string())?;
    let Reply::Enrolled { credential } = owner
        .call(Command::Enroll {
            principal: "sdk-example".into(),
            permissions: ["notes.create", "notes.read", "notes.list"]
                .into_iter()
                .map(|action| Permission {
                    endpoint: "notes".into(),
                    action: action.into(),
                })
                .collect(),
        })
        .map_err(|e| e.to_string())?
    else {
        return Err("invalid_enrollment_response".into());
    };
    // A real adopter gives only this credential to its application, never the owner's.
    let mut client = GatewayClient::with_credential(Path::new(&args[0]), credential)
        .map_err(|e| e.to_string())?;
    let (capabilities, _) = client.capabilities(None, 20).map_err(|e| e.to_string())?;
    let target = capabilities
        .into_iter()
        .find(|c| c.definition.action == "notes.create")
        .ok_or("notes_unavailable")?
        .target;
    let request = Request {
        schema_version: "edge-action-request.v1".into(),
        request_id: args[2].clone(),
        target: target.clone(),
        action: "notes.create".into(),
        budget_ms: 2000,
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
                    value: "Created through the public authenticated Rust client.".into(),
                },
            ),
        ]
        .into(),
    };
    let preview = client.preview(request).map_err(|e| e.to_string())?;
    println!(
        "Authenticated v2 notes example. This creates a real app-owned note, not a simulation."
    );
    println!(
        "Request: {}\nPreview: {}",
        args[2],
        serde_json::to_string_pretty(&preview).map_err(|e| e.to_string())?
    );
    let hash = digest(&preview.plan)?;
    if preview.state == State::Offered {
        print!("Owner: type create to approve this exact note; anything else declines: ");
        io::stdout().flush().map_err(|e| e.to_string())?;
        let mut input = String::new();
        io::stdin()
            .read_line(&mut input)
            .map_err(|e| e.to_string())?;
        if input.trim() != "create" {
            client.cancel(&args[2]).map_err(|e| e.to_string())?;
            println!("Declined; no note created.");
            return Ok(());
        }
        owner
            .approve("sdk-example", &args[2], &hash)
            .map_err(|e| e.to_string())?;
    }
    let done = client.execute(&args[2], &hash).map_err(|e| {
        format!(
            "{e}; inspect original request {} before taking another action",
            args[2]
        )
    })?;
    let Some(Receipt::Succeeded {
        output:
            Output::Scalar {
                value: Parameter::Resource { value: note_id },
            },
        ..
    }) = done.receipt
    else {
        return Err(format!(
            "Outcome {:?}; preserve the journal and inspect request {}. Do not automatically create a replacement.",
            done.state, args[2]
        ));
    };
    let read = Request {
        schema_version: "edge-action-request.v1".into(),
        request_id: format!("read-{}", args[2]),
        target,
        action: "notes.read".into(),
        budget_ms: 2000,
        parameters: [(
            "note_id".into(),
            Parameter::Resource {
                value: note_id.clone(),
            },
        )]
        .into(),
    };
    let offer = client.preview(read.clone()).map_err(|e| e.to_string())?;
    let readback = client
        .execute(&read.request_id, &digest(&offer.plan)?)
        .map_err(|e| e.to_string())?;
    println!(
        "Created or recovered note: {note_id}\nReadback: {}",
        serde_json::to_string_pretty(&readback).map_err(|e| e.to_string())?
    );
    println!(
        "Activity: {}",
        serde_json::to_string_pretty(&client.events(0, 100).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?
    );
    client.close();
    Ok(())
}
fn main() {
    #[cfg(target_os = "linux")]
    if let Err(e) = run() {
        eprintln!("{e}");
        std::process::exit(2);
    }
    #[cfg(not(target_os = "linux"))]
    {
        eprintln!("This example currently requires Linux/WSL.");
        std::process::exit(2);
    }
}
