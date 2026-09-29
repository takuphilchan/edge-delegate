//! Explicit software-only execution and lost-acknowledgement recovery.
//! Uses a new directory; never overwrites or deletes an existing journal.
use edge_core::{
    PreviewDecision,
    execution::{Adapter, OperationState, execute, reconcile},
    preview,
};
use edge_simulator::{Fault, Simulator};
use edge_storage::SqliteJournal;
use std::{
    path::PathBuf,
    time::{Duration, Instant},
};

fn deadline() -> Instant {
    Instant::now() + Duration::from_secs(5)
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    if args.len() != 1 {
        return Err(
            "usage: cargo run -p edge-simulator --example recovery -- NEW_DIRECTORY".into(),
        );
    }
    let root = PathBuf::from(&args[0]);
    // Fail if it exists: don't reuse user evidence or silently repeat this scenario.
    let mut builder = std::fs::DirBuilder::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        builder.mode(0o700);
    }
    builder.create(&root)?;
    println!(
        "SOFTWARE ONLY: no physical audio changes, model, network or user-authentication service."
    );
    println!("The example program acts as the trusted test operator issuing approval.");
    let mut device = Simulator::open(&root.join("device.sqlite"))?;
    let mut journal = SqliteJournal::open(&root.join("journal"), device.authority_id())?;
    let request = device.request("lost-ack-example", 40, deadline())?;
    let proposed = preview(&request, &device.observe(deadline())?)?;
    let PreviewDecision::Proposed { plan, .. } = proposed.decision else {
        return Err("unexpected preview".into());
    };
    let token = journal.approve("test-operator", &plan, deadline())?;
    device.fault = Fault::LostAcknowledgement;
    let first = execute(
        &mut journal,
        &mut device,
        "test-operator",
        &request,
        Some(&token),
        deadline(),
    )?;
    assert_eq!(first.state, OperationState::Unknown);
    println!(
        "After lost acknowledgement: {:?}; software writes: {}",
        first.state,
        device.writes()?
    );
    drop(journal);
    drop(device);
    let mut device = Simulator::open(&root.join("device.sqlite"))?;
    let mut journal = SqliteJournal::open(&root.join("journal"), device.authority_id())?;
    let retry = execute(
        &mut journal,
        &mut device,
        "test-operator",
        &request,
        None,
        deadline(),
    )?;
    assert_eq!(retry.state, OperationState::Unknown);
    assert_eq!(device.invoke_calls, 0);
    println!(
        "After restart and retry: {:?}; adapter invocations since restart: {}",
        retry.state, device.invoke_calls
    );
    let recovered = reconcile(
        &mut journal,
        &mut device,
        "test-operator",
        &request.request_id,
        deadline(),
    )?;
    assert_eq!(recovered.state, OperationState::Succeeded);
    assert_eq!(device.writes()?, 1);
    println!(
        "After receipt reconciliation: {:?}; total software writes: {}",
        recovered.state,
        device.writes()?
    );
    println!("Journal and device evidence retained in {}", root.display());
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("error: {error}");
        std::process::exit(1);
    }
}
