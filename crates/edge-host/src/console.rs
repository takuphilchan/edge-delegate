use crate::session::SoftwareSession;
use edge_contracts::Result;
use edge_protocol::adapter::SimulatorFault;
use std::{
    io::{self, BufRead, Write},
    path::Path,
};

pub fn run(directory: &Path) -> Result<()> {
    let executable = std::env::current_exe()
        .map_err(|_| "host_path_unavailable")?
        .with_file_name("edge-delegate-simulator-worker");
    println!("Starting supervised SOFTWARE adapter; no native device access...");
    let mut session = SoftwareSession::open(directory, &executable, SimulatorFault::None)?;
    println!(
        "READY: supervised SOFTWARE session {}. No native audio or physical devices.\nCommands: preview PERCENT | approve PLAN_SHA256 | execute | status REQUEST_ID | cancel REQUEST_ID | reconcile REQUEST_ID | restart-adapter | quit\nPreview and approve do not execute. Each write requires its exact preview fingerprint.\nExecution is synchronous; this console does not accept cancellation while execute is running.",
        session.authority_id()
    );
    let mut input = io::stdin().lock();
    loop {
        print!("software> ");
        io::stdout().flush().map_err(|_| "console_closed")?;
        let mut bytes = Vec::new();
        // Bound console input without accumulating an arbitrarily long line.
        use std::io::Read;
        let count = (&mut input)
            .take(4097)
            .read_until(b'\n', &mut bytes)
            .map_err(|_| "console_read_failed")?;
        if count == 0 {
            return Ok(());
        }
        if bytes.len() > 4096 {
            return Err("console_input_too_long".into());
        }
        let line = std::str::from_utf8(&bytes).map_err(|_| "invalid_console_utf8")?;
        let parts: Vec<_> = line.split_whitespace().collect();
        let result: Result<String> = match parts.as_slice() {
            [] => continue,
            ["quit"] => return Ok(()),
            ["preview", value] => {
                let preview = value.parse::<i64>().map_err(|_| "invalid_percent".into())
                    .and_then(|value| session.preview_volume(value));
                render(preview)
            }
            ["approve", hash] => session.approve(hash).map(|_| "Approved exact preview for at most 60 seconds; no action executed.".into()),
            ["execute"] => render(session.execute()),
            ["status", id] => render(session.status(id)),
            ["reconcile", id] => render(session.reconcile(id)),
            ["cancel", id] => render(session.cancel(id)),
            ["restart-adapter"] => session.restart_adapter().map(|_| "Adapter restarted. No operations replayed; reconcile uncertain requests explicitly.".into()),
            _ => Err("unknown_command_or_invalid_arguments".into()),
        };
        match result {
            Ok(output) => println!("{output}"),
            Err(error) => {
                eprintln!("error: {error}");
                if let Some(id) = session.pending_request_id() {
                    eprintln!(
                        "Inspect status {id}; an error after submission does not prove no effect. Do not change the ID to retry uncertain work."
                    );
                }
            }
        }
    }
}

fn render<T: serde::Serialize>(result: Result<T>) -> Result<String> {
    serde_json::to_string_pretty(&result?).map_err(|_| "encoding_failed".into())
}
