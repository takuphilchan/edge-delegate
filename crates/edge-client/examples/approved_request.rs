//! Runnable onboarding example using only the public client. Software volume only.
#[cfg(target_os = "linux")]
fn run(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    use edge_client::execution::{Command, ExecutionClient, Reply, Scope};
    use edge_contracts::operation::OperationState;
    use std::{
        io::{self, Write},
        path::Path,
        thread,
        time::{Duration, Instant},
    };

    let [directory] = args else {
        return Err("usage: approved_request PRIVATE_SERVICE_DIRECTORY".into());
    };
    let directory = Path::new(directory);
    let owner = ExecutionClient::connect(directory, &directory.join("owner.json"))?;
    // This owner-run example holds both roles. Ordinary clients must not get owner.json.
    let Reply::Enrolled { credential } = owner.call(Command::Enroll {
        principal: "sdk-example".into(),
        scope: Scope::Control,
    })?
    else {
        return Err("unexpected enrollment reply".into());
    };
    let client = ExecutionClient::with_credential(directory, credential)?;
    let Reply::Preview {
        request_id,
        plan,
        plan_sha256,
    } = client.call(Command::PreviewVolume {
        percent: 40,
        budget_ms: 2000,
    })?
    else {
        return Err("unexpected preview reply".into());
    };
    println!("SOFTWARE ONLY: your computer's volume will not change.");
    println!("Request: {request_id}");
    println!(
        "Preview (no action executed):\n{}",
        serde_json::to_string_pretty(&plan)?
    );
    print!(
        "Type approve to set the simulated output to 40%, or press Enter to leave it unchanged: "
    );
    io::stdout().flush()?;
    let mut answer = String::new();
    // Bound input and accept only the exact confirmation text.
    use std::io::{BufRead, Read};
    io::stdin().lock().take(64).read_line(&mut answer)?;
    if answer.trim_end_matches(['\r', '\n']) != "approve" {
        println!("Not submitted. No device action was requested.");
        return Ok(());
    }
    owner.call(Command::Approve {
        principal: "sdk-example".into(),
        request_id: request_id.clone(),
        plan_sha256,
    })?;
    // Keep this identifier visible even if submission or polling loses its response.
    println!(
        "Submitting {request_id}. If interrupted, inspect this ID; do not start a replacement request."
    );
    let result = (|| -> Result<(), Box<dyn std::error::Error>> {
        let submission = client.call(Command::Submit {
            request_id: request_id.clone(),
        })?;
        println!("Submission: {}", serde_json::to_string(&submission)?);
        let until = Instant::now() + Duration::from_secs(5);
        loop {
            let Reply::Status { operation, .. } = client.call(Command::Status {
                request_id: request_id.clone(),
            })?
            else {
                return Err("unexpected status reply".into());
            };
            if let Some(operation) = operation
                && !matches!(
                    operation.state,
                    OperationState::Prepared | OperationState::Dispatching
                )
            {
                println!("Operation: {}", serde_json::to_string_pretty(&operation)?);
                if operation.state == OperationState::Succeeded {
                    println!("Succeeded: simulated output is 40%; receipt recorded.");
                    return Ok(());
                }
                return Err("operation did not report success; inspect the existing record".into());
            }
            if Instant::now() >= until {
                return Err("stopped waiting; this does not cancel execution".into());
            }
            thread::sleep(Duration::from_millis(50));
        }
    })();
    if result.is_err() {
        eprintln!(
            "Preserve request ID {request_id}. Use owner inspect for principal sdk-example. Do not delete the journal or blindly repeat this example."
        );
    }
    result
}

#[cfg(not(target_os = "linux"))]
fn run(_: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    Err("This example requires Linux/WSL; native transports are not implemented here.".into())
}

fn main() -> std::process::ExitCode {
    match run(&std::env::args().skip(1).collect::<Vec<_>>()) {
        Ok(()) => std::process::ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("error: {error}");
            std::process::ExitCode::FAILURE
        }
    }
}
