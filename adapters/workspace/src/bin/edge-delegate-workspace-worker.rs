//! Installed notes worker. stdin/stdout are a private inherited socket, not a service.
#[cfg(target_os = "linux")]
fn run() -> Result<(), String> {
    use edge_core::actions::Adapter;
    use edge_protocol::{action_adapter as wire, read_frame, write_frame};
    use std::time::{Duration, Instant};
    let args: Vec<String> = std::env::args().skip(1).collect();
    let mut values = std::collections::BTreeMap::new();
    if !args.len().is_multiple_of(2) {
        return Err("invalid_worker_arguments".into());
    }
    for pair in args.chunks_exact(2) {
        if values.insert(pair[0].as_str(), pair[1].as_str()).is_some() {
            return Err("duplicate_argument".into());
        }
    }
    if values.keys().any(|key| {
        ![
            "--directory",
            "--authority",
            "--endpoint",
            "--parent-pid",
            "--fault",
        ]
        .contains(key)
    }) {
        return Err("unknown_argument".into());
    }
    let parent: i32 = values
        .get("--parent-pid")
        .ok_or("missing_parent")?
        .parse()
        .map_err(|_| "invalid_parent")?;
    nix::sys::prctl::set_pdeathsig(Some(nix::sys::signal::Signal::SIGKILL))
        .map_err(|_| "parent_fence_failed")?;
    if parent <= 1 || nix::unistd::getppid().as_raw() != parent {
        return Err("parent_changed".into());
    }
    let fault = values.get("--fault").copied().unwrap_or("none");
    if !["none", "hang", "lost-ack", "malformed", "crash"].contains(&fault) {
        return Err("invalid_fault".into());
    }
    let mut store = edge_workspace::Workspace::open(
        std::path::Path::new(values.get("--directory").ok_or("missing_directory")?),
        values.get("--authority").ok_or("missing_authority")?,
        values.get("--endpoint").ok_or("missing_endpoint")?,
    )?;
    let mut input = std::io::stdin().lock();
    let mut output = std::io::stdout().lock();
    let mut previous = 0;
    while let Some(message) =
        read_frame::<wire::Message>(&mut input).map_err(|_| "invalid_worker_frame")?
    {
        if message.schema_version != wire::VERSION || message.sequence <= previous {
            return Err("invalid_worker_sequence".into());
        }
        previous = message.sequence;
        let reply = match message.command {
            wire::Command::Describe {} => wire::Reply::Description {
                endpoint: store.describe()?,
            },
            command => {
                let (principal, operation_id, request, budget_ms, invoke) = match command {
                    wire::Command::Invoke {
                        principal,
                        operation_id,
                        request,
                        budget_ms,
                    } => (principal, operation_id, request, budget_ms, true),
                    wire::Command::Reconcile {
                        principal,
                        operation_id,
                        request,
                        budget_ms,
                    } => (principal, operation_id, request, budget_ms, false),
                    _ => unreachable!(),
                };
                request.validate()?;
                edge_contracts::identifier(&principal)?;
                edge_contracts::identifier(&operation_id)?;
                if !(1..=5000).contains(&budget_ms) {
                    return Err("invalid_budget".into());
                }
                let deadline = Instant::now() + Duration::from_millis(budget_ms.into());
                if invoke && fault == "crash" {
                    std::process::exit(73);
                }
                if invoke && fault == "hang" {
                    loop {
                        std::thread::park();
                    }
                }
                let result = if invoke {
                    store.invoke(&principal, &operation_id, &request, deadline)
                } else {
                    store.reconcile(&principal, &operation_id, &request, deadline)
                };
                if invoke && fault == "lost-ack" {
                    std::process::exit(74);
                }
                if invoke && fault == "malformed" {
                    use std::io::Write;
                    output
                        .write_all(&[0, 0, 0, 1, b'{'])
                        .map_err(|_| "write_failed")?;
                    return Ok(());
                }
                match result {
                    Ok(receipt) => wire::Reply::Receipt { receipt },
                    Err(_) => wire::Reply::Unavailable {},
                }
            }
        };
        write_frame(
            &mut output,
            &wire::Response {
                schema_version: wire::VERSION.into(),
                sequence: message.sequence,
                reply,
            },
        )
        .map_err(|_| "worker_write_failed")?;
        // Stdout is buffered even when backed by the private socket. Flush each
        // response, otherwise small durable receipts can wait until host timeout.
        std::io::Write::flush(&mut output).map_err(|_| "worker_write_failed")?;
    }
    Ok(())
}
fn main() {
    #[cfg(target_os = "linux")]
    if run().is_err() {
        std::process::exit(2);
    }
    #[cfg(not(target_os = "linux"))]
    {
        eprintln!("Workspace worker currently requires Linux/WSL.");
        std::process::exit(2);
    }
}
