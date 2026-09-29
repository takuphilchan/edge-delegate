//! Automated software-only approval/timeout/reconciliation diagnostic, not human review.
#[cfg(target_os = "linux")]
fn run() -> Result<(), Box<dyn std::error::Error>> {
    use edge_contracts::operation::OperationState;
    use edge_host::session::SoftwareSession;
    use edge_protocol::adapter::SimulatorFault;
    use rusqlite::Connection;
    use std::{fs, os::unix::fs::DirBuilderExt, path::PathBuf};
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    if args.len() != 2 {
        return Err("expected NEW_DIRECTORY WORKER_EXECUTABLE".into());
    }
    let root = PathBuf::from(&args[0]);
    let worker = PathBuf::from(&args[1]);
    fs::DirBuilder::new().mode(0o700).create(&root)?; // refuse to reuse any evidence
    println!(
        "SOFTWARE ONLY. The test program confirms its own fixture; this is not independent human approval.\nNo model, native audio, physical devices or external service."
    );
    let mut session = SoftwareSession::open(&root, &worker, SimulatorFault::HangAfterEffect)?;
    let preview = session.preview_volume(40)?;
    assert!(session.execute().is_err());
    println!("PASS: unapproved execution rejected.");
    session.approve(&preview.plan_sha256)?;
    let outcome = session.execute()?;
    assert_eq!(outcome.state, OperationState::Unknown);
    assert!(!session.worker_healthy());
    println!(
        "PASS: adapter hung after its software write; supervisor stopped waiting and retained UNKNOWN."
    );
    let retry = session.execute()?;
    assert_eq!(retry.operation_id, outcome.operation_id);
    assert_eq!(retry.state, OperationState::Unknown);
    session.restart_adapter()?;
    let recovered = session.reconcile(&preview.plan.request_id)?;
    assert_eq!(recovered.state, OperationState::Succeeded);
    let db = Connection::open(root.join("device.sqlite"))?;
    let (volume, writes): (i64, i64) =
        db.query_row("SELECT volume,writes FROM state", [], |r| {
            Ok((r.get(0)?, r.get(1)?))
        })?;
    assert_eq!((volume, writes), (40, 1));
    println!(
        "PASS: explicit adapter restart and receipt reconciliation; simulated volume 40, exactly one recorded software write."
    );
    let report = serde_json::json!({"schema_version":"edge-supervision-diagnostic.v1", "software_only":true, "human_approval_evaluated":false,
        "before_reconciliation":outcome, "after_reconciliation":recovered, "simulator_volume":volume, "simulator_write_count":writes});
    fs::write(
        root.join("report.json"),
        serde_json::to_vec_pretty(&report)?,
    )?;
    println!("Report and journals retained: {}", root.display());
    Ok(())
}
fn main() {
    #[cfg(target_os = "linux")]
    if let Err(error) = run() {
        eprintln!("error: {error}");
        std::process::exit(1);
    }
    #[cfg(not(target_os = "linux"))]
    {
        eprintln!("supervised software example requires Linux/WSL");
        std::process::exit(2);
    }
}
