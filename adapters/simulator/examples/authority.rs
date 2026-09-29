//! Scoped admission/cancellation diagnostic. Fixture approval is not human consent evidence.
#[cfg(target_os = "linux")]
fn run() -> Result<(), Box<dyn std::error::Error>> {
    use edge_contracts::operation::OperationState;
    use edge_core::cancellation::CancelDisposition;
    use edge_host::authority::{Grant, Permission, ScopedClient, SoftwareAuthority, TicketStatus};
    use edge_protocol::adapter::SimulatorFault;
    use rusqlite::{Connection, OpenFlags};
    use std::{
        collections::BTreeSet,
        fs,
        os::unix::fs::DirBuilderExt,
        path::PathBuf,
        thread,
        time::{Duration, Instant},
    };

    fn wait(client: &ScopedClient, id: &str) -> Result<TicketStatus, String> {
        let limit = Instant::now() + Duration::from_secs(5);
        loop {
            let status = client.status(id)?;
            if !matches!(status, TicketStatus::Queued | TicketStatus::Running) {
                return Ok(status);
            }
            if Instant::now() >= limit {
                return Err("diagnostic_wait_expired".into());
            }
            thread::sleep(Duration::from_millis(5));
        }
    }
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    if args.len() != 2 {
        return Err("expected NEW_DIRECTORY WORKER_EXECUTABLE".into());
    }
    let root = PathBuf::from(&args[0]);
    let worker = PathBuf::from(&args[1]);
    fs::DirBuilder::new().mode(0o700).create(&root)?;
    println!(
        "SOFTWARE ONLY: scoped Rust handles, fixture confirmations, no model or native audio changes."
    );
    let owner = SoftwareAuthority::start(&root, &worker, SimulatorFault::HangAfterEffect)?;
    let client = owner.enroll(Grant {
        principal: "diagnostic-client".into(),
        actions: BTreeSet::from(["audio.volume.set".into()]),
        endpoints: BTreeSet::from(["output".into()]),
        permissions: BTreeSet::from([
            Permission::Preview,
            Permission::Execute,
            Permission::Status,
            Permission::Cancel,
            Permission::Reconcile,
        ]),
    })?;
    let first = client.preview_volume(40, 5000)?;
    let queued = client.preview_volume(40, 5000)?;
    assert_eq!(
        client.submit(&first.request_id).unwrap_err(),
        "owner_approval_required"
    );
    println!("PASS: client cannot execute without separate owner confirmation.");
    owner.approve(&client, &first.request_id, &first.plan_sha256)?;
    owner.approve(&client, &queued.request_id, &queued.plan_sha256)?;
    client.submit(&first.request_id)?;
    let db =
        Connection::open_with_flags(root.join("device.sqlite"), OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    let writes = || db.query_row("SELECT writes FROM state", [], |r| r.get::<_, i64>(0));
    let limit = Instant::now() + Duration::from_secs(2);
    while writes()? != 1 {
        if Instant::now() >= limit {
            return Err("diagnostic_effect_not_seen".into());
        }
        thread::sleep(Duration::from_millis(2));
    }
    client.submit(&queued.request_id)?;
    assert_eq!(
        client.cancel(&queued.request_id)?,
        CancelDisposition::PreventedDispatch
    );
    assert_eq!(
        client.cancel(&first.request_id)?,
        CancelDisposition::PossiblyDispatched
    );
    let TicketStatus::Completed { operation: before } = wait(&client, &first.request_id)? else {
        return Err("expected durable unknown operation".into());
    };
    assert_eq!(before.state, OperationState::Unknown);
    assert!(matches!(
        wait(&client, &queued.request_id)?,
        TicketStatus::CancelledBeforeDispatch
    ));
    println!(
        "PASS: queued cancellation prevents dispatch; in-flight cancellation preserves UNKNOWN."
    );
    assert_eq!(writes()?, 1);
    drop(owner);
    let owner = SoftwareAuthority::start(&root, &worker, SimulatorFault::None)?;
    assert!(
        owner
            .inspect("diagnostic-client", &queued.request_id)?
            .is_none()
    );
    let recovered = owner.reconcile_record("diagnostic-client", &first.request_id)?;
    assert_eq!(recovered.state, OperationState::Succeeded);
    assert_eq!(writes()?, 1);
    println!(
        "PASS: authority restart does not resume the queue; receipt recovery finds one software write."
    );
    let report = serde_json::json!({
        "schema_version": "edge-authority-diagnostic.v1",
        "software_only": true, "human_approval_evaluated": false,
        "durable_admission": true, "execution_rpc": false,
        "before_reconciliation": before, "after_reconciliation": recovered,
        "queued_request": queued.request_id, "queued_invocations": 0,
        "queued_admission": owner.inspect_admission("diagnostic-client", &queued.request_id)?,
        "simulator_write_count": writes()?
    });
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
        eprintln!("authority diagnostic requires Linux/WSL");
        std::process::exit(2);
    }
}
