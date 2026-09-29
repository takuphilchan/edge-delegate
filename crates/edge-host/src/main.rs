use std::process::ExitCode;

#[cfg(target_os = "linux")]
fn run(args: &[String]) -> Result<(), String> {
    use std::{fs::File, io::Read, path::Path, sync::atomic::AtomicBool};
    if args.len() == 3 && args[0] == "serve-software" && args[1] == "--directory" {
        let executable = std::env::current_exe().map_err(|e| e.to_string())?;
        let worker = executable
            .parent()
            .ok_or("missing executable directory")?
            .join("edge-delegate-simulator-worker");
        let server = edge_host::execution_service::ExecutionServer::bind(
            Path::new(&args[2]),
            &worker,
            edge_protocol::adapter::SimulatorFault::None,
        )
        .map_err(|e| e.to_string())?;
        println!(
            "READY: authenticated SOFTWARE execution service. No native device actions or model.\nOwner credential: {}/owner.json\nEnroll clients, preview as a client, approve as owner, then submit as client. Keep credentials private. Ctrl-C stops the host; restart never resumes work.",
            args[2]
        );
        return server
            .serve_until(&AtomicBool::new(false))
            .map_err(|e| e.to_string());
    }
    if args.len() == 3 && args[0] == "software-session" && args[1] == "--directory" {
        return edge_host::console::run(Path::new(&args[2]));
    }
    if args.len() != 5
        || args[0] != "serve-preview"
        || args[1] != "--directory"
        || args[3] != "--context"
    {
        return Err("expected: serve-preview --directory PRIVATE_DIRECTORY --context FILE".into());
    }
    let mut bytes = Vec::new();
    File::open(&args[4])
        .map_err(|e| e.to_string())?
        .take(edge_contracts::MAX_FRAME_BYTES as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(|e| e.to_string())?;
    let context = edge_contracts::parse_json(&bytes)?;
    let server = edge_host::local::PreviewServer::bind(Path::new(&args[2]), context)
        .map_err(|e| e.to_string())?;
    println!(
        "READY: Linux saved-context preview service. No approval, execution, model or native device access.\nOwner-only client credential: {}/client.json\nKeep this terminal running; use edgectl from another terminal. Ctrl-C stops the host.",
        args[2]
    );
    server
        .serve_until(&AtomicBool::new(false))
        .map_err(|e| e.to_string())
}

#[cfg(not(target_os = "linux"))]
fn run(_: &[String]) -> Result<(), String> {
    Err("local host transport currently requires Linux (WSL supported for development); other native transports are not implemented".into())
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.is_empty() || args == ["--help"] {
        println!(
            "edge-delegate-host: experimental Linux host foundations\nUsage: edge-delegate-host serve-preview --directory PRIVATE_DIRECTORY --context FILE\n       edge-delegate-host software-session --directory NEW_SOFTWARE_DIRECTORY\n       edge-delegate-host serve-software --directory PRIVATE_SERVICE_DIRECTORY\nserve-preview remains non-executing. serve-software admits authenticated software execution after separate owner confirmation. No native device control. Keep service, preview, software-session and legacy journal directories separate."
        );
        return ExitCode::SUCCESS;
    }
    match run(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("error: {error}");
            ExitCode::from(2)
        }
    }
}
