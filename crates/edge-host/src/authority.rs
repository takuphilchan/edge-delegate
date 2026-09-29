//! Experimental in-process software execution authority. Scoped handles are minted by
//! trusted setup, not supplied as client principal strings. No network execution endpoint.
//! Queued acknowledgements follow durable admission. Restart never resumes admitted work.
use crate::{session::SoftwareSession, supervised::SupervisedSimulator};
use edge_contracts::{
    ControlRequest, Parameter, RequestInput, Result,
    admission::{Admission, AdmissionState},
    identifier,
    operation::Operation,
    preview::{Plan, PreviewContext, PreviewDecision},
};
use edge_core::{
    cancellation::{CancelDisposition, DispatchControl},
    execution::{Adapter, Journal, execute_controlled, reconcile},
    preview,
};
use edge_protocol::adapter::SimulatorFault;
use edge_storage::{APPROVAL_TTL, SqliteJournal, admission::AdmissionWriter};
use std::{
    collections::{BTreeMap, BTreeSet, VecDeque},
    path::Path,
    sync::{Arc, Condvar, Mutex, mpsc},
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};
use uuid::Uuid;

pub const MAX_WAITING: usize = 8;
pub const MAX_OFFERS: usize = 128;
pub const MAX_CLIENTS: usize = 64;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum Permission {
    Preview,
    Execute,
    Status,
    Cancel,
    Reconcile,
}
#[derive(Clone)]
pub struct Grant {
    pub principal: String,
    pub actions: BTreeSet<String>,
    pub endpoints: BTreeSet<String>,
    pub permissions: BTreeSet<Permission>,
}
impl Grant {
    fn validate(&self) -> Result<()> {
        identifier(&self.principal)?;
        if self.actions.len() > 128 || self.endpoints.len() > 128 {
            return Err("grant_too_large".into());
        }
        for id in self.actions.iter().chain(self.endpoints.iter()) {
            identifier(id)?;
        }
        Ok(())
    }
}
#[derive(Debug, Clone)]
pub struct Offer {
    pub request_id: String,
    pub plan: Plan,
    pub plan_sha256: String,
}
#[derive(Debug, Clone)]
pub enum TicketStatus {
    Persisting,
    Queued,
    Running,
    CancelledBeforeDispatch,
    ExpiredBeforeDispatch,
    Completed {
        operation: Box<Operation>,
    },
    /// Storage/transport errors after admission must not masquerade as no-effect failure.
    NeedsInspection {
        reason: String,
    },
}
struct Enrolled {
    grant: Grant,
    revoked: bool,
}
struct StoredOffer {
    owner: String,
    request: ControlRequest,
    offer: Offer,
    created: Instant,
    approval: Option<String>,
}
struct Ticket {
    owner: String,
    principal: String,
    status: TicketStatus,
    control: DispatchControl,
}
enum Job {
    Preview {
        client: String,
        percent: i64,
        budget_ms: u32,
        deadline: Instant,
        reply: mpsc::Sender<Result<Offer>>,
    },
    Approve {
        client: String,
        id: String,
        hash: String,
        deadline: Instant,
        reply: mpsc::Sender<Result<()>>,
    },
    Execute {
        client: String,
        id: String,
        deadline: Instant,
    },
    Reconcile {
        client: String,
        id: String,
        deadline: Instant,
        reply: mpsc::Sender<Result<Operation>>,
    },
    Inspect {
        principal: String,
        id: String,
        deadline: Instant,
        reply: mpsc::Sender<Result<Option<Operation>>>,
    },
    Recover {
        principal: String,
        id: String,
        deadline: Instant,
        reply: mpsc::Sender<Result<Operation>>,
    },
    Restart {
        deadline: Instant,
        reply: mpsc::Sender<Result<()>>,
    },
}
struct State {
    clients: BTreeMap<String, Enrolled>,
    offers: BTreeMap<String, StoredOffer>,
    tickets: BTreeMap<String, Ticket>,
    queue: VecDeque<Job>,
    reservations: usize,
    stopping: bool,
}
struct Shared {
    state: Mutex<State>,
    admissions: Mutex<Option<AdmissionWriter>>,
    wake: Condvar,
}
impl Shared {
    fn lock(&self) -> Result<std::sync::MutexGuard<'_, State>> {
        self.state
            .lock()
            .map_err(|_| "authority_state_poisoned".into())
    }
    fn admissions<T>(
        &self,
        deadline: Instant,
        action: impl FnOnce(&mut AdmissionWriter) -> Result<T>,
    ) -> Result<T> {
        loop {
            edge_core::execution::check_deadline(deadline)?;
            match self.admissions.try_lock() {
                Ok(mut writer) => return action(writer.as_mut().ok_or("admission_store_closed")?),
                Err(std::sync::TryLockError::Poisoned(_)) => {
                    return Err("admission_store_poisoned".into());
                }
                Err(std::sync::TryLockError::WouldBlock) => thread::sleep(Duration::from_millis(1)),
            }
        }
    }
}
fn access(state: &State, client: &str, permission: Permission) -> Result<Grant> {
    if state.stopping {
        return Err("authority_stopping".into());
    }
    let entry = state.clients.get(client).ok_or("unknown_client")?;
    if entry.revoked {
        return Err("client_revoked".into());
    }
    if !entry.grant.permissions.contains(&permission) {
        return Err("permission_denied".into());
    }
    Ok(entry.grant.clone())
}
fn room(state: &State) -> Result<()> {
    if state.stopping {
        Err("authority_stopping".into())
    } else if state.queue.len() + state.reservations >= MAX_WAITING {
        Err("authority_overloaded".into())
    } else {
        Ok(())
    }
}
fn budget(ms: u32) -> Result<Instant> {
    if !(1..=5000).contains(&ms) {
        return Err("budget_must_be_1_to_5000_ms".into());
    }
    Ok(Instant::now() + Duration::from_millis(ms.into()))
}
fn receive<T>(receiver: mpsc::Receiver<Result<T>>, deadline: Instant) -> Result<T> {
    receiver
        .recv_timeout(deadline.saturating_duration_since(Instant::now()))
        .map_err(|_| "authority_reply_unavailable".to_string())?
}

/// Administrative owner. Dropping it closes admission, cancels work and joins the owner
/// thread. As before, pathological filesystem commits cannot be hard-preempted.
pub struct SoftwareAuthority {
    authority_id: String,
    shared: Arc<Shared>,
    thread: Option<JoinHandle<()>>,
}
#[derive(Clone)]
pub struct ScopedClient {
    shared: Arc<Shared>,
    id: String,
}
impl SoftwareAuthority {
    pub fn start(directory: &Path, executable: &Path, fault: SimulatorFault) -> Result<Self> {
        let shared = Arc::new(Shared {
            state: Mutex::new(State {
                clients: BTreeMap::new(),
                offers: BTreeMap::new(),
                tickets: BTreeMap::new(),
                queue: VecDeque::new(),
                reservations: 0,
                stopping: false,
            }),
            admissions: Mutex::new(None),
            wake: Condvar::new(),
        });
        let (ready, ready_rx) = mpsc::channel();
        let worker_shared = shared.clone();
        let directory = directory.to_path_buf();
        let executable = executable.to_path_buf();
        let thread = thread::Builder::new()
            .name("software-authority".into())
            .spawn(move || {
                let runtime = SoftwareSession::open(&directory, &executable, fault)
                    .map(SoftwareSession::into_runtime);
                match runtime {
                    Ok((adapter, journal)) => {
                        match journal.admission_writer() {
                            Ok(writer) => {
                                *worker_shared
                                    .admissions
                                    .lock()
                                    .expect("new authority mutex") = Some(writer)
                            }
                            Err(error) => {
                                let _ = ready.send(Err(error));
                                return;
                            }
                        }
                        let _ = ready.send(Ok(journal.authority_id().to_owned()));
                        run(worker_shared, adapter, journal);
                    }
                    Err(error) => {
                        let _ = ready.send(Err(error));
                    }
                }
            })
            .map_err(|_| "authority_thread_failed")?;
        let mut authority = Self {
            authority_id: String::new(),
            shared,
            thread: Some(thread),
        };
        authority.authority_id = receive(ready_rx, Instant::now() + Duration::from_secs(7))?;
        Ok(authority)
    }
    pub fn authority_id(&self) -> &str {
        &self.authority_id
    }
    /// Trusted local setup only. This is not remote enrollment or OS app isolation.
    pub fn enroll(&self, grant: Grant) -> Result<ScopedClient> {
        grant.validate()?;
        let mut state = self.shared.lock()?;
        if state.stopping {
            return Err("authority_stopping".into());
        }
        if state.clients.len() >= MAX_CLIENTS {
            return Err("client_capacity_reached".into());
        }
        if state
            .clients
            .values()
            .any(|e| e.grant.principal == grant.principal)
        {
            return Err("principal_already_enrolled".into());
        }
        let id = Uuid::new_v4().to_string();
        state.clients.insert(
            id.clone(),
            Enrolled {
                grant,
                revoked: false,
            },
        );
        Ok(ScopedClient {
            shared: self.shared.clone(),
            id,
        })
    }
    fn own_client(&self, client: &ScopedClient) -> Result<()> {
        if !Arc::ptr_eq(&self.shared, &client.shared) {
            return Err("client_belongs_to_other_authority".into());
        }
        Ok(())
    }
    /// Confirmation is owner-only and binds the requesting client's stored proposal.
    /// The client handle deliberately has no approve method.
    pub fn approve(&self, client: &ScopedClient, offer_id: &str, hash: &str) -> Result<()> {
        identifier(offer_id)?;
        edge_contracts::fingerprint(hash)?;
        self.own_client(client)?;
        let deadline = budget(2000)?;
        let (tx, rx) = mpsc::channel();
        let mut state = self.shared.lock()?;
        access(&state, &client.id, Permission::Execute)?;
        room(&state)?;
        state.queue.push_back(Job::Approve {
            client: client.id.clone(),
            id: offer_id.into(),
            hash: hash.into(),
            deadline,
            reply: tx,
        });
        drop(state);
        self.shared.wake.notify_one();
        receive(rx, deadline)
    }
    pub fn revoke(&self, client: &ScopedClient) -> Result<Vec<(String, CancelDisposition)>> {
        self.own_client(client)?;
        let mut state = self.shared.lock()?;
        state
            .clients
            .get_mut(&client.id)
            .ok_or("unknown_client")?
            .revoked = true;
        let principal = state
            .clients
            .get(&client.id)
            .ok_or("unknown_client")?
            .grant
            .principal
            .clone();
        let cancelled: Vec<_> = state
            .tickets
            .iter()
            .filter(|(_, t)| t.owner == client.id)
            .map(|(id, t)| (id.clone(), t.control.cancel()))
            .collect();
        drop(state);
        let deadline = budget(2000)?;
        for (id, _) in &cancelled {
            self.shared
                .admissions(deadline, |w| w.request_cancel(&principal, id, deadline))?;
        }
        Ok(cancelled)
    }
    pub fn ticket_status(&self, client: &ScopedClient, id: &str) -> Result<TicketStatus> {
        self.own_client(client)?;
        let state = self.shared.lock()?;
        state
            .tickets
            .get(id)
            .filter(|t| t.owner == client.id)
            .map(|t| t.status.clone())
            .ok_or("unknown_ticket".into())
    }
    pub fn inspect(&self, principal: &str, request_id: &str) -> Result<Option<Operation>> {
        identifier(principal)?;
        identifier(request_id)?;
        let deadline = budget(2000)?;
        let (tx, rx) = mpsc::channel();
        let mut state = self.shared.lock()?;
        room(&state)?;
        state.queue.push_back(Job::Inspect {
            principal: principal.into(),
            id: request_id.into(),
            deadline,
            reply: tx,
        });
        drop(state);
        self.shared.wake.notify_one();
        receive(rx, deadline)
    }
    /// Durable admission remains inspectable even when no operation was claimed.
    pub fn inspect_admission(
        &self,
        principal: &str,
        request_id: &str,
    ) -> Result<Option<Admission>> {
        let deadline = budget(2000)?;
        self.shared
            .admissions(deadline, |w| w.inspect(principal, request_id, deadline))
    }
    /// Read durable outcome without queueing behind adapter execution.
    pub fn inspect_operation(
        &self,
        principal: &str,
        request_id: &str,
    ) -> Result<Option<Operation>> {
        let deadline = budget(2000)?;
        self.shared.admissions(deadline, |w| {
            w.inspect_operation(principal, request_id, deadline)
        })
    }
    pub fn restart_adapter(&self) -> Result<()> {
        let deadline = budget(5000)?;
        let (tx, rx) = mpsc::channel();
        let mut state = self.shared.lock()?;
        room(&state)?;
        state.queue.push_back(Job::Restart {
            deadline,
            reply: tx,
        });
        drop(state);
        self.shared.wake.notify_one();
        receive(rx, deadline)
    }
    /// Owner-only recovery of durable records, including after volatile handles and
    /// offers were lost on restart. This queries receipts; it never resumes execution.
    pub fn reconcile_record(&self, principal: &str, request_id: &str) -> Result<Operation> {
        identifier(principal)?;
        identifier(request_id)?;
        let deadline = budget(2000)?;
        let (tx, rx) = mpsc::channel();
        let mut state = self.shared.lock()?;
        room(&state)?;
        state.queue.push_back(Job::Recover {
            principal: principal.into(),
            id: request_id.into(),
            deadline,
            reply: tx,
        });
        drop(state);
        self.shared.wake.notify_one();
        receive(rx, deadline)
    }
}
impl Drop for SoftwareAuthority {
    fn drop(&mut self) {
        if let Ok(mut state) = self.shared.state.lock() {
            state.stopping = true;
            for ticket in state.tickets.values() {
                ticket.control.cancel();
            }
        }
        self.shared.wake.notify_all();
        if let Some(thread) = self.thread.take() {
            let _ = thread.join();
        }
        // Retained client handles must not keep the journal lease alive after shutdown.
        if let Ok(mut writer) = self.shared.admissions.lock() {
            writer.take();
        }
    }
}

impl ScopedClient {
    pub fn preview_volume(&self, percent: i64, budget_ms: u32) -> Result<Offer> {
        if !(0..=100).contains(&percent) {
            return Err("invalid_percent".into());
        }
        let deadline = budget(budget_ms)?;
        let (tx, rx) = mpsc::channel();
        let mut state = self.shared.lock()?;
        access(&state, &self.id, Permission::Preview)?;
        room(&state)?;
        state.queue.push_back(Job::Preview {
            client: self.id.clone(),
            percent,
            budget_ms,
            deadline,
            reply: tx,
        });
        drop(state);
        self.shared.wake.notify_one();
        receive(rx, deadline)
    }
    /// Queued is returned only after durable admission. Persisting (a concurrent retry)
    /// is not acceptance. Retry the SAME offer; never generate a new ID on uncertain errors.
    pub fn submit(&self, request_id: &str) -> Result<TicketStatus> {
        identifier(request_id)?;
        let mut state = self.shared.lock()?;
        let grant = access(&state, &self.id, Permission::Execute)?;
        let offer = owned_offer(&state, &self.id, request_id)?;
        if let Some(ticket) = state.tickets.get(request_id) {
            return Ok(ticket.status.clone());
        }
        if offer.approval.is_none() {
            return Err("owner_approval_required".into());
        }
        let deadline = budget(offer.request.budget_ms)?;
        let request = offer.request.clone();
        let plan = offer.offer.plan.clone();
        let token = offer.approval.clone().ok_or("owner_approval_required")?;
        room(&state)?;
        state.reservations += 1;
        let control = DispatchControl::default();
        state.tickets.insert(
            request_id.into(),
            Ticket {
                owner: self.id.clone(),
                principal: grant.principal.clone(),
                status: TicketStatus::Persisting,
                control: control.clone(),
            },
        );
        drop(state);
        let admission = self.shared.admissions(deadline, |w| {
            w.admit(&grant.principal, &request, &plan, &token, deadline)
        });
        let mut state = self.shared.lock()?;
        state.reservations -= 1;
        let failure = match admission {
            Ok(row) if row.state == AdmissionState::Accepted && !row.cancellation_requested => None,
            Ok(_) => Some("admission_fenced".to_string()),
            Err(error) => Some(error),
        };
        if let Some(reason) = failure {
            control.cancel();
            control.finish();
            state
                .tickets
                .get_mut(request_id)
                .ok_or("unknown_ticket")?
                .status = TicketStatus::NeedsInspection {
                reason: reason.clone(),
            };
            drop(state);
            // A commit may have succeeded just before the budget elapsed. Fence that
            // durable admission when possible; never enqueue after an uncertain reply.
            let cleanup = Instant::now() + Duration::from_secs(2);
            let _ = self.shared.admissions(cleanup, |w| {
                w.stop(
                    &grant.principal,
                    request_id,
                    AdmissionState::Interrupted,
                    cleanup,
                )
            });
            return Err(reason);
        }
        if state.stopping || control.cancelled() || Instant::now() >= deadline {
            let cancelled = state.stopping || control.cancelled();
            control.cancel();
            control.finish();
            let status = if cancelled {
                TicketStatus::CancelledBeforeDispatch
            } else {
                TicketStatus::ExpiredBeforeDispatch
            };
            state
                .tickets
                .get_mut(request_id)
                .ok_or("unknown_ticket")?
                .status = status.clone();
            drop(state);
            let cleanup = budget(2000)?;
            self.shared.admissions(cleanup, |w| {
                w.stop(
                    &grant.principal,
                    request_id,
                    if cancelled {
                        AdmissionState::CancelledBeforeDispatch
                    } else {
                        AdmissionState::ExpiredBeforeDispatch
                    },
                    cleanup,
                )
            })?;
            return Ok(status);
        }
        state
            .tickets
            .get_mut(request_id)
            .ok_or("unknown_ticket")?
            .status = TicketStatus::Queued;
        state.queue.push_back(Job::Execute {
            client: self.id.clone(),
            id: request_id.into(),
            deadline,
        });
        drop(state);
        self.shared.wake.notify_one();
        Ok(TicketStatus::Queued)
    }
    pub fn status(&self, id: &str) -> Result<TicketStatus> {
        let state = self.shared.lock()?;
        access(&state, &self.id, Permission::Status)?;
        let ticket = state
            .tickets
            .get(id)
            .filter(|t| t.owner == self.id)
            .ok_or("unknown_ticket")?;
        Ok(ticket.status.clone())
    }
    /// Does not queue behind execution. Disposition is a dispatch fence, NOT a receipt
    /// or a claim that an already submitted device operation was undone.
    pub fn cancel(&self, id: &str) -> Result<CancelDisposition> {
        let state = self.shared.lock()?;
        access(&state, &self.id, Permission::Cancel)?;
        let ticket = state
            .tickets
            .get(id)
            .filter(|t| t.owner == self.id)
            .ok_or("unknown_ticket")?;
        let disposition = ticket.control.cancel();
        let principal = ticket.principal.clone();
        drop(state);
        let deadline = budget(2000)?;
        self.shared
            .admissions(deadline, |w| w.request_cancel(&principal, id, deadline))?;
        Ok(disposition)
    }
    pub fn reconcile(&self, id: &str) -> Result<Operation> {
        identifier(id)?;
        let deadline = budget(2000)?;
        let (tx, rx) = mpsc::channel();
        let mut state = self.shared.lock()?;
        access(&state, &self.id, Permission::Reconcile)?;
        // Durable lookup is bound to this principal, even when restart lost the offer.
        room(&state)?;
        state.queue.push_back(Job::Reconcile {
            client: self.id.clone(),
            id: id.into(),
            deadline,
            reply: tx,
        });
        drop(state);
        self.shared.wake.notify_one();
        receive(rx, deadline)
    }
}
fn owned_offer<'a>(state: &'a State, client: &str, id: &str) -> Result<&'a StoredOffer> {
    state
        .offers
        .get(id)
        .filter(|o| o.owner == client)
        .ok_or("unknown_offer".into())
}
fn restricted(mut context: PreviewContext, grant: &Grant) -> PreviewContext {
    context
        .policy
        .allowed_actions
        .retain(|id| grant.actions.contains(id));
    context
        .policy
        .allowed_endpoints
        .retain(|id| grant.endpoints.contains(id));
    context
}
struct ScopedAdapter<'a> {
    adapter: &'a mut SupervisedSimulator,
    grant: &'a Grant,
}
impl Adapter for ScopedAdapter<'_> {
    fn observe(&mut self, deadline: Instant) -> Result<PreviewContext> {
        self.adapter
            .observe(deadline)
            .map(|c| restricted(c, self.grant))
    }
    fn invoke(
        &mut self,
        id: &str,
        step: &edge_contracts::preview::PlanStep,
        deadline: Instant,
    ) -> Result<edge_contracts::operation::Receipt> {
        self.adapter.invoke(id, step, deadline)
    }
    fn reconcile(
        &mut self,
        id: &str,
        deadline: Instant,
    ) -> Result<edge_contracts::operation::Receipt> {
        self.adapter.reconcile(id, deadline)
    }
}

fn run(shared: Arc<Shared>, mut adapter: SupervisedSimulator, mut journal: SqliteJournal) {
    loop {
        let job = {
            let Ok(mut state) = shared.lock() else {
                break;
            };
            while state.queue.is_empty() && !state.stopping {
                let Ok(next) = shared.wake.wait(state) else {
                    return;
                };
                state = next;
            }
            if state.stopping {
                let pending: Vec<_> = state
                    .tickets
                    .iter()
                    .filter(|(_, t)| matches!(t.status, TicketStatus::Queued))
                    .map(|(id, _)| id.clone())
                    .collect();
                for ticket in state.tickets.values_mut() {
                    if matches!(ticket.status, TicketStatus::Queued) {
                        ticket.status = TicketStatus::CancelledBeforeDispatch;
                        ticket.control.finish();
                    }
                }
                state.queue.clear();
                drop(state);
                for id in pending {
                    persist_ticket(&shared, &id);
                }
                break;
            }
            state.queue.pop_front().expect("nonempty queue")
        };
        match job {
            Job::Preview {
                client,
                percent,
                budget_ms,
                deadline,
                reply,
            } => {
                let _ = reply.send(make_offer(
                    &shared,
                    &mut adapter,
                    &journal,
                    &client,
                    percent,
                    budget_ms,
                    deadline,
                ));
            }
            Job::Approve {
                client,
                id,
                hash,
                deadline,
                reply,
            } => {
                let _ = reply.send(approve(
                    &shared,
                    &mut adapter,
                    &mut journal,
                    &client,
                    &id,
                    &hash,
                    deadline,
                ));
            }
            Job::Execute {
                client,
                id,
                deadline,
            } => perform(&shared, &mut adapter, &mut journal, &client, &id, deadline),
            Job::Inspect {
                principal,
                id,
                deadline,
                reply,
            } => {
                let _ = reply.send(journal.lookup(&principal, &id, deadline));
            }
            Job::Recover {
                principal,
                id,
                deadline,
                reply,
            } => {
                let result = reconcile(&mut journal, &mut adapter, &principal, &id, deadline);
                if let Ok(operation) = &result
                    && let Ok(mut state) = shared.lock()
                    && let Some(ticket) = state.tickets.get_mut(&id)
                {
                    ticket.status = TicketStatus::Completed {
                        operation: Box::new(operation.clone()),
                    };
                }
                let _ = reply.send(result);
            }
            Job::Restart { deadline, reply } => {
                let result = adapter
                    .restart(SimulatorFault::None, deadline)
                    .and_then(|_| adapter.observe(deadline))
                    .and_then(|c| {
                        if c.authority_id == journal.authority_id() {
                            Ok(())
                        } else {
                            Err("device_identity_changed".into())
                        }
                    });
                let _ = reply.send(result);
            }
            Job::Reconcile {
                client,
                id,
                deadline,
                reply,
            } => {
                let result = shared
                    .lock()
                    .and_then(|s| access(&s, &client, Permission::Reconcile))
                    .and_then(|grant| {
                        reconcile(
                            &mut journal,
                            &mut ScopedAdapter {
                                adapter: &mut adapter,
                                grant: &grant,
                            },
                            &grant.principal,
                            &id,
                            deadline,
                        )
                    });
                if let Ok(operation) = &result
                    && let Ok(mut state) = shared.lock()
                    && let Some(ticket) = state.tickets.get_mut(&id)
                {
                    ticket.status = TicketStatus::Completed {
                        operation: Box::new(operation.clone()),
                    };
                }
                let _ = reply.send(result);
            }
        }
    }
}

fn make_offer(
    shared: &Shared,
    adapter: &mut SupervisedSimulator,
    journal: &SqliteJournal,
    client: &str,
    percent: i64,
    budget_ms: u32,
    deadline: Instant,
) -> Result<Offer> {
    edge_core::execution::check_deadline(deadline)?;
    let grant = {
        let state = shared.lock()?;
        access(&state, client, Permission::Preview)?
    };
    let context = restricted(adapter.observe(deadline)?, &grant);
    if context.authority_id != journal.authority_id() {
        return Err("device_identity_changed".into());
    }
    let request = ControlRequest {
        schema_version: "edge-control-request.v2".into(),
        request_id: Uuid::new_v4().to_string(),
        authority_id: context.authority_id.clone(),
        budget_ms,
        input: RequestInput::Action {
            target: context
                .endpoints
                .first()
                .ok_or("no_endpoint")?
                .binding
                .clone(),
            action: "audio.volume.set".into(),
            parameters: BTreeMap::from([("percent".into(), Parameter::Integer { value: percent })]),
        },
    };
    let PreviewDecision::Proposed {
        plan, plan_sha256, ..
    } = preview(&request, &context)?.decision
    else {
        return Err("scope_or_preview_rejected".into());
    };
    let offer = Offer {
        request_id: request.request_id.clone(),
        plan,
        plan_sha256,
    };
    let mut state = shared.lock()?;
    access(&state, client, Permission::Preview)?;
    edge_core::execution::check_deadline(deadline)?;
    if state.offers.len() >= MAX_OFFERS {
        return Err("offer_capacity_reached".into());
    }
    state.offers.insert(
        request.request_id.clone(),
        StoredOffer {
            owner: client.into(),
            request,
            offer: offer.clone(),
            created: Instant::now(),
            approval: None,
        },
    );
    Ok(offer)
}
fn approve(
    shared: &Shared,
    adapter: &mut SupervisedSimulator,
    journal: &mut SqliteJournal,
    client: &str,
    id: &str,
    hash: &str,
    deadline: Instant,
) -> Result<()> {
    let (grant, request, expected) = {
        let state = shared.lock()?;
        let grant = access(&state, client, Permission::Execute)?;
        let offer = owned_offer(&state, client, id)?;
        if offer.offer.plan_sha256 != hash || offer.created.elapsed() >= APPROVAL_TTL {
            return Err("invalid_or_expired_confirmation".into());
        }
        if offer.approval.is_some() {
            return Ok(());
        }
        (
            grant,
            offer.request.clone(),
            offer.offer.plan_sha256.clone(),
        )
    };
    let context = restricted(adapter.observe(deadline)?, &grant);
    let PreviewDecision::Proposed {
        plan, plan_sha256, ..
    } = preview(&request, &context)?.decision
    else {
        return Err("repreview_required".into());
    };
    if expected != plan_sha256 {
        return Err("repreview_required".into());
    }
    let token = journal.approve(&grant.principal, &plan, deadline)?;
    let mut state = shared.lock()?;
    access(&state, client, Permission::Execute)?;
    state.offers.get_mut(id).ok_or("unknown_offer")?.approval = Some(token);
    Ok(())
}
fn perform(
    shared: &Shared,
    adapter: &mut SupervisedSimulator,
    journal: &mut SqliteJournal,
    client: &str,
    id: &str,
    deadline: Instant,
) {
    let prepared = (|| {
        let mut state = shared.lock()?;
        let ticket = state.tickets.get_mut(id).ok_or("unknown_ticket")?;
        if ticket.control.cancelled() {
            ticket.status = TicketStatus::CancelledBeforeDispatch;
            ticket.control.finish();
            return Ok(None);
        }
        if Instant::now() >= deadline {
            ticket.status = TicketStatus::ExpiredBeforeDispatch;
            ticket.control.finish();
            return Ok(None);
        }
        let control = ticket.control.clone();
        let grant = access(&state, client, Permission::Execute)?;
        let offer = owned_offer(&state, client, id)?;
        let request = offer.request.clone();
        let token = offer.approval.clone().ok_or("owner_approval_required")?;
        let ticket = state.tickets.get_mut(id).ok_or("unknown_ticket")?;
        ticket.status = TicketStatus::Running;
        Ok(Some((grant, request, token, control)))
    })();
    let outcome: Result<Option<(Operation, DispatchControl)>> = match prepared {
        Ok(Some((grant, request, token, control))) => {
            adapter.set_cancellation(Some(control.clone()));
            let result = execute_controlled(
                journal,
                &mut ScopedAdapter {
                    adapter,
                    grant: &grant,
                },
                &grant.principal,
                &request,
                Some(&token),
                deadline,
                &control,
            );
            adapter.set_cancellation(None);
            control.finish();
            result.map(|operation| Some((operation, control)))
        }
        Ok(None) => {
            persist_ticket(shared, id);
            return;
        }
        Err(error) => Err(error),
    };
    if let Ok(mut state) = shared.lock()
        && let Some(ticket) = state.tickets.get_mut(id)
    {
        ticket.control.finish();
        ticket.status = match outcome {
            Ok(Some((operation, _))) => TicketStatus::Completed {
                operation: Box::new(operation),
            },
            Err(reason) => TicketStatus::NeedsInspection { reason },
            Ok(None) => unreachable!(),
        };
    }
    persist_ticket(shared, id);
}

fn persist_ticket(shared: &Shared, id: &str) {
    let selected = shared.lock().and_then(|state| {
        let ticket = state.tickets.get(id).ok_or("unknown_ticket")?;
        let phase = match &ticket.status {
            TicketStatus::CancelledBeforeDispatch => AdmissionState::CancelledBeforeDispatch,
            TicketStatus::ExpiredBeforeDispatch => AdmissionState::ExpiredBeforeDispatch,
            TicketStatus::Completed { operation } => match operation.state {
                edge_contracts::operation::OperationState::CancelledBeforeDispatch => {
                    AdmissionState::CancelledBeforeDispatch
                }
                edge_contracts::operation::OperationState::ExpiredBeforeDispatch => {
                    AdmissionState::ExpiredBeforeDispatch
                }
                _ => AdmissionState::Finished,
            },
            TicketStatus::NeedsInspection { .. } => AdmissionState::Interrupted,
            _ => return Err("admission_attempt_still_active".into()),
        };
        Ok((ticket.principal.clone(), phase))
    });
    let result = selected.and_then(|(principal, phase)| {
        let deadline = Instant::now() + Duration::from_secs(2);
        shared.admissions(deadline, |w| w.stop(&principal, id, phase, deadline))
    });
    if let Err(reason) = result
        && let Ok(mut state) = shared.lock()
        && let Some(ticket) = state.tickets.get_mut(id)
    {
        ticket.status = TicketStatus::NeedsInspection { reason };
    }
}
