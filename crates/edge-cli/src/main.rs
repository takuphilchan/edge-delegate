//! Saved-context development preview, offline or through the Linux local host.
use std::{fs::File, io::Read, process::ExitCode};

fn read_frame(path: &str) -> Result<Vec<u8>, String> {
    let mut bytes = Vec::new();
    File::open(path)
        .map_err(|e| format!("cannot open {path}: {e}"))?
        .take(edge_contracts::MAX_FRAME_BYTES as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(|e| e.to_string())?;
    if bytes.len() > edge_contracts::MAX_FRAME_BYTES {
        return Err("input exceeds 65536 bytes".into());
    }
    Ok(bytes)
}

fn run(args: &[String]) -> Result<(), String> {
    if args.is_empty() || args == ["--help"] {
        println!(
            "edgectl: experimental local control clients\nUsage: edgectl preview --request FILE --context FILE\n       edgectl capabilities --directory PRIVATE_DIRECTORY\n       edgectl preview --request FILE --directory PRIVATE_DIRECTORY\n       edgectl service --directory PRIVATE_DIRECTORY --credential FILE --command FILE [--save-credential NEW_FILE]\nPreview commands: No model, live authorization, approval or device execution.\nThe separate service command can submit authenticated SOFTWARE operations. Owner approval and client submission are separate calls; no automatic approval."
        );
        return Ok(());
    }
    if args.first().is_some_and(|s| s == "service") {
        return execution_service(&args[1..]);
    }
    if args.len() == 3 && args[0] == "capabilities" && args[1] == "--directory" {
        return local(&args[2], None);
    }
    if args.len() == 5 && args[0] == "preview" && args[1] == "--request" && args[3] == "--directory"
    {
        let request = edge_contracts::ControlRequest::parse(&read_frame(&args[2])?)?;
        return local(&args[4], Some(request));
    }
    if args.len() != 5 || args[0] != "preview" || args[1] != "--request" || args[3] != "--context" {
        return Err("expected: preview --request FILE --context FILE; see --help".into());
    }
    let request = edge_contracts::ControlRequest::parse(&read_frame(&args[2])?)?;
    let context = edge_contracts::parse_json(&read_frame(&args[4])?)?;
    let preview = edge_core::preview(&request, &context)?;
    println!(
        "{}",
        serde_json::to_string_pretty(&preview).map_err(|e| e.to_string())?
    );
    Ok(())
}

#[cfg(target_os = "linux")]
fn local(directory: &str, request: Option<edge_contracts::ControlRequest>) -> Result<(), String> {
    let mut client = edge_client::local::LocalClient::connect(std::path::Path::new(directory))
        .map_err(|e| e.to_string())?;
    let output = match request {
        Some(request) => {
            serde_json::to_string_pretty(&client.preview(&request).map_err(|e| e.to_string())?)
        }
        None => serde_json::to_string_pretty(&client.capabilities().map_err(|e| e.to_string())?),
    }
    .map_err(|e| e.to_string())?;
    client.close();
    println!("{output}");
    Ok(())
}

#[cfg(not(target_os = "linux"))]
fn local(_: &str, _: Option<edge_contracts::ControlRequest>) -> Result<(), String> {
    Err(
        "local client transport currently requires Linux; use offline preview on this platform"
            .into(),
    )
}

fn main() -> ExitCode {
    match run(&std::env::args().skip(1).collect::<Vec<_>>()) {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("error: {error}");
            ExitCode::from(2)
        }
    }
}

#[cfg(target_os = "linux")]
fn execution_service(args: &[String]) -> Result<(), String> {
    use edge_client::execution::{Command, ExecutionClient, Reply, save_credential};
    use std::path::Path;
    if !matches!(args.len(), 6 | 8)
        || args[0] != "--directory"
        || args[2] != "--credential"
        || args[4] != "--command"
        || (args.len() == 8 && args[6] != "--save-credential")
    {
        return Err("expected: service --directory DIR --credential FILE --command FILE [--save-credential NEW_FILE]".into());
    }
    let command: Command = edge_contracts::parse_json(&read_frame(&args[5])?)?;
    if matches!(command, Command::Enroll { .. }) != (args.len() == 8) {
        return Err(
            "enrollment requires --save-credential NEW_FILE; that option is only for enrollment"
                .into(),
        );
    }
    if args.len() == 8 && Path::new(&args[7]).symlink_metadata().is_ok() {
        return Err("credential output already exists; refusing overwrite".into());
    }
    let client = ExecutionClient::connect(Path::new(&args[1]), Path::new(&args[3]))
        .map_err(|e| e.to_string())?;
    let reply = client.call(command).map_err(|e| e.to_string())?;
    if let Reply::Enrolled { credential } = reply {
        save_credential(Path::new(&args[7]), &credential).map_err(|e| e.to_string())?;
        println!(
            "{}",
            serde_json::json!({"enrollment_saved":true,"principal":credential.principal})
        );
    } else {
        println!(
            "{}",
            serde_json::to_string_pretty(&reply).map_err(|e| e.to_string())?
        );
    }
    Ok(())
}
#[cfg(not(target_os = "linux"))]
fn execution_service(_: &[String]) -> Result<(), String> {
    Err("execution service client currently requires Linux/WSL".into())
}
