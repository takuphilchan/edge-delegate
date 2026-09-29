//! Trusted software adapter. Framed stdin/stdout are inherited from the supervisor.
//! This process separation is NOT a sandbox against malicious installed code.
#[cfg(target_os = "linux")]
use edge_core::execution::Adapter;
#[cfg(target_os = "linux")]
use edge_protocol::{
    adapter::{
        ADAPTER_VERSION, AdapterCommand, AdapterReply, AdapterRequest, AdapterResponse,
        SimulatorFault,
    },
    read_frame, write_frame,
};
#[cfg(target_os = "linux")]
use edge_simulator::{Fault, Simulator};
use std::process::ExitCode;
#[cfg(target_os = "linux")]
use std::{
    io::{self, Write},
    path::Path,
    time::{Duration, Instant},
};

#[cfg(target_os = "linux")]
fn run(args: &[String]) -> Result<(), String> {
    if args.len() != 6
        || args[0] != "--database"
        || args[2] != "--fault"
        || args[4] != "--parent-pid"
    {
        return Err(
            "expected inherited adapter channel and fixed database/fault configuration".into(),
        );
    }
    #[cfg(target_os = "linux")]
    {
        use nix::{
            sys::{prctl::set_pdeathsig, signal::Signal},
            unistd::getppid,
        };
        set_pdeathsig(Some(Signal::SIGKILL)).map_err(|_| "parent_death_fence_failed")?;
        let parent: i32 = args[5].parse().map_err(|_| "invalid_parent")?;
        if getppid().as_raw() != parent {
            return Err("parent_already_exited".into());
        }
    }
    let fault = SimulatorFault::parse(&args[3])?;
    let mut device = Simulator::open(Path::new(&args[1]))?;
    if matches!(fault, SimulatorFault::LostAcknowledgement) {
        device.fault = Fault::LostAcknowledgement;
    }
    let mut input = io::stdin().lock();
    let mut output = io::stdout().lock();
    while let Some(request) =
        read_frame::<AdapterRequest>(&mut input).map_err(|_| "invalid_adapter_frame")?
    {
        request.validate()?;
        let deadline = Instant::now() + Duration::from_millis(request.budget_ms.into());
        let reply = match request.command {
            AdapterCommand::Observe {} => device
                .observe(deadline)
                .map(|context| AdapterReply::Context { context }),
            AdapterCommand::Reconcile { operation_id } => device
                .reconcile(&operation_id, deadline)
                .map(|receipt| AdapterReply::Receipt { receipt }),
            AdapterCommand::Invoke { operation_id, step } => {
                if matches!(fault, SimulatorFault::HangBeforeEffect) {
                    loop {
                        std::thread::park();
                    }
                }
                let result = device.invoke(&operation_id, &step, deadline);
                if matches!(fault, SimulatorFault::HangAfterEffect) {
                    loop {
                        std::thread::park();
                    }
                }
                if matches!(fault, SimulatorFault::CrashAfterEffect) {
                    std::process::exit(91);
                }
                if matches!(fault, SimulatorFault::MalformedResponse) {
                    output
                        .write_all(&[0, 0, 0, 1, b'{'])
                        .map_err(|_| "channel_closed")?;
                    output.flush().map_err(|_| "channel_closed")?;
                    return Ok(());
                }
                result.map(|receipt| AdapterReply::Receipt { receipt })
            }
        }
        .unwrap_or(AdapterReply::Unavailable {});
        write_frame(
            &mut output,
            &AdapterResponse {
                schema_version: ADAPTER_VERSION.into(),
                call_id: request.call_id,
                reply,
            },
        )
        .map_err(|_| "channel_closed")?;
        output.flush().map_err(|_| "channel_closed")?;
    }
    Ok(())
}
#[cfg(not(target_os = "linux"))]
fn run(_: &[String]) -> Result<(), String> {
    Err("supervised simulator currently requires Linux".into())
}
fn main() -> ExitCode {
    match run(&std::env::args().skip(1).collect::<Vec<_>>()) {
        Ok(()) => ExitCode::SUCCESS,
        Err(_) => ExitCode::from(2), // no raw requests, paths or adapter values in diagnostics
    }
}
