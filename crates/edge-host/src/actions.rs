//! Generic in-process authority for trusted installed adapters. Not an IPC server.
//! Owner-issued client handles carry private principal identity. Native adapter
//! calls must honor their deadline; this embedding does not preempt blocking code.
use edge_contracts::actions::{Capability, Endpoint, Event, Receipt, Record, Request, State};
use edge_contracts::{Result, digest, identifier};
use edge_core::actions::{Adapter, Permission, Policy, compile, discover};
use edge_core::cancellation::{DispatchControl, DispatchDecision};
use edge_core::execution::check_deadline;
use edge_storage::actions::ActionJournal;
use std::{
    collections::BTreeMap,
    path::Path,
    sync::{
        Arc, Mutex, MutexGuard,
        atomic::{AtomicBool, AtomicUsize, Ordering},
    },
    thread,
    time::{Duration, Instant},
};

type Key = (String, String);
fn deadline() -> Instant {
    Instant::now() + Duration::from_secs(2)
}
fn lock<T>(mutex: &Mutex<T>, until: Instant) -> Result<MutexGuard<'_, T>> {
    loop {
        check_deadline(until)?;
        match mutex.try_lock() {
            Ok(guard) => return Ok(guard),
            Err(std::sync::TryLockError::Poisoned(_)) => {
                return Err("authority_lock_poisoned".into());
            }
            Err(std::sync::TryLockError::WouldBlock) => thread::sleep(Duration::from_millis(1)),
        }
    }
}
struct Registry {
    authority: String,
    adapters: BTreeMap<String, Box<dyn Adapter + Send>>,
}
impl Registry {
    fn new(authority: &str, adapters: Vec<Box<dyn Adapter + Send>>) -> Result<Self> {
        if adapters.is_empty() || adapters.len() > 128 {
            return Err("invalid_adapter_count".into());
        }
        let mut entries = BTreeMap::new();
        for adapter in adapters {
            let descriptor = adapter.describe()?;
            descriptor.validate()?;
            if descriptor.binding.authority_id != authority
                || entries
                    .insert(descriptor.binding.endpoint_id.clone(), adapter)
                    .is_some()
            {
                return Err("invalid_adapter_registration".into());
            }
        }
        Ok(Self {
            authority: authority.into(),
            adapters: entries,
        })
    }
    fn describe(&self, until: Instant) -> Result<Vec<Endpoint>> {
        self.adapters
            .iter()
            .map(|(key, adapter)| {
                let descriptor = adapter.describe_until(until)?;
                descriptor.validate()?;
                if descriptor.binding.endpoint_id != *key
                    || descriptor.binding.authority_id != self.authority
                {
                    return Err("adapter_identity_changed".into());
                }
                Ok(descriptor)
            })
            .collect()
    }
}
struct Shared {
    authority: String,
    journal: Mutex<ActionJournal>,
    registry: Mutex<Registry>,
    dispatch_gate: Mutex<()>,
    controls: Mutex<BTreeMap<Key, DispatchControl>>,
    admitted: AtomicUsize,
    stopping: AtomicBool,
}
impl Shared {
    fn ready(&self) -> Result<()> {
        if self.stopping.load(Ordering::SeqCst) {
            Err("authority_stopping_or_fenced".into())
        } else {
            Ok(())
        }
    }
    fn policy(&self, principal: &str, until: Instant) -> Result<Policy> {
        lock(&self.journal, until)?.policy(principal, until)
    }
    fn reserve(&self) -> Result<Reservation<'_>> {
        self.ready()?;
        self.admitted
            .fetch_update(Ordering::SeqCst, Ordering::SeqCst, |n| {
                if n < 9 { Some(n + 1) } else { None }
            })
            .map_err(|_| "authority_overloaded")?;
        Ok(Reservation(&self.admitted))
    }
}
struct Reservation<'a>(&'a AtomicUsize);
impl Drop for Reservation<'_> {
    fn drop(&mut self) {
        self.0.fetch_sub(1, Ordering::SeqCst);
    }
}
struct Active<'a> {
    shared: &'a Shared,
    key: Key,
    control: DispatchControl,
}
impl Drop for Active<'_> {
    fn drop(&mut self) {
        self.control.finish();
        if let Ok(mut controls) = self.shared.controls.lock() {
            controls.remove(&self.key);
        }
    }
}

/// Owner administration. Do not expose this object to ordinary application code.
pub struct ActionAuthority {
    shared: Arc<Shared>,
}
/// Scoped application handle. No owner approval, policy update or impersonation API.
#[derive(Clone)]
pub struct ActionClient {
    shared: Arc<Shared>,
    principal: String,
}
impl ActionAuthority {
    pub fn open(
        directory: &Path,
        authority: &str,
        adapters: Vec<Box<dyn Adapter + Send>>,
    ) -> Result<Self> {
        identifier(authority)?;
        let registry = Registry::new(authority, adapters)?;
        let journal = ActionJournal::open(directory, authority)?;
        Ok(Self {
            shared: Arc::new(Shared {
                authority: authority.into(),
                journal: Mutex::new(journal),
                registry: Mutex::new(registry),
                dispatch_gate: Mutex::new(()),
                controls: Mutex::new(BTreeMap::new()),
                admitted: AtomicUsize::new(0),
                stopping: AtomicBool::new(false),
            }),
        })
    }
    /// Trusted owner explicitly creates/replaces a principal's exact permissions.
    /// Updating permissions invalidates previews compiled against older revisions.
    pub fn enroll(&self, principal: &str, permissions: Vec<Permission>) -> Result<ActionClient> {
        self.shared.ready()?;
        identifier(principal)?;
        let until = deadline();
        let _gate = lock(&self.shared.dispatch_gate, until)?;
        let mut journal = lock(&self.shared.journal, until)?;
        let revision = match journal.policy(principal, until) {
            Ok(old) => old
                .revision
                .checked_add(1)
                .ok_or("policy_revision_exhausted")?,
            Err(e) if e == "unknown_principal" => 1,
            Err(e) => return Err(e),
        };
        let policy = Policy {
            authority_id: self.shared.authority.clone(),
            principal: principal.into(),
            revision,
            permissions,
        };
        policy.validate()?;
        if let Err(error) = journal.set_policy(&policy, until) {
            self.shared.stopping.store(true, Ordering::SeqCst);
            return Err(error);
        }
        Ok(ActionClient {
            shared: self.shared.clone(),
            principal: principal.into(),
        })
    }
    /// Issue a fresh in-process handle after the owner authenticates its caller.
    /// This does not grant permissions or resurrect revoked permissions.
    pub fn client(&self, principal: &str) -> Result<ActionClient> {
        self.shared.ready()?;
        self.shared.policy(principal, deadline())?;
        Ok(ActionClient {
            shared: self.shared.clone(),
            principal: principal.into(),
        })
    }
    pub fn approve(&self, client: &ActionClient, id: &str, plan_hash: &str) -> Result<()> {
        self.same_authority(client)?;
        self.shared.ready()?;
        let until = deadline();
        let _gate = lock(&self.shared.dispatch_gate, until)?;
        lock(&self.shared.journal, until)?.approve(&client.principal, id, plan_hash, until)
    }
    pub fn revoke(&self, client: &ActionClient) -> Result<()> {
        self.same_authority(client)?;
        self.enroll(&client.principal, vec![])?;
        Ok(())
    }
    fn same_authority(&self, client: &ActionClient) -> Result<()> {
        if !Arc::ptr_eq(&self.shared, &client.shared) {
            return Err("foreign_client_handle".into());
        }
        Ok(())
    }
    pub fn close(&self) {
        // Serialize shutdown against the last authorization/dispatch decision.
        let _gate = self
            .shared
            .dispatch_gate
            .lock()
            .unwrap_or_else(|e| e.into_inner());
        self.shared.stopping.store(true, Ordering::SeqCst);
        if let Ok(controls) = self.shared.controls.lock() {
            for control in controls.values() {
                control.cancel();
            }
        }
    }
}
impl Drop for ActionAuthority {
    fn drop(&mut self) {
        self.close();
    }
}

impl ActionClient {
    pub fn capabilities(&self) -> Result<Vec<Capability>> {
        self.shared.ready()?;
        let until = deadline();
        let policy = self.shared.policy(&self.principal, until)?;
        let descriptors = lock(&self.shared.registry, until)?.describe(until)?;
        check_deadline(until)?;
        discover(&descriptors, &policy)
    }
    pub fn preview(&self, request: &Request) -> Result<Record> {
        self.shared.ready()?;
        let until = deadline();
        let policy = self.shared.policy(&self.principal, until)?;
        let descriptors = lock(&self.shared.registry, until)?.describe(until)?;
        let plan = compile(request, &descriptors, &policy)?;
        lock(&self.shared.journal, until)?.offer(&self.principal, &plan, until)
    }
    pub fn status(&self, id: &str) -> Result<Option<Record>> {
        let until = deadline();
        lock(&self.shared.journal, until)?.lookup(&self.principal, id, until)
    }
    pub fn events(&self, after: u64, limit: u32) -> Result<Vec<Event>> {
        let until = deadline();
        lock(&self.shared.journal, until)?.events(&self.principal, after, limit, until)
    }
    pub fn cancel(&self, id: &str) -> Result<Record> {
        let until = deadline();
        let _gate = lock(&self.shared.dispatch_gate, until)?;
        if let Some(control) =
            lock(&self.shared.controls, until)?.get(&(self.principal.clone(), id.into()))
        {
            control.cancel();
        }
        lock(&self.shared.journal, until)?.cancel(&self.principal, id, until)
    }
    /// Synchronous call; concurrent callers are bounded to one active adapter and
    /// eight waiters. Acceptance persists before waiting for adapter ownership.
    pub fn execute(&self, id: &str, plan_hash: &str) -> Result<Record> {
        self.shared.ready()?;
        let observed = self.status(id)?.ok_or("unknown_request")?;
        if digest(&observed.plan)? != plan_hash {
            return Err("request_identity_conflict".into());
        }
        if observed.state != State::Offered {
            return Ok(observed);
        }
        let until = Instant::now() + Duration::from_millis(observed.plan.request.budget_ms.into());
        let _reservation = self.shared.reserve()?;
        let (record, control) = {
            let _gate = lock(&self.shared.dispatch_gate, until)?;
            self.shared.ready()?;
            let mut controls = lock(&self.shared.controls, until)?;
            let (record, new) =
                lock(&self.shared.journal, until)?.admit(&self.principal, id, plan_hash, until)?;
            if !new {
                return Ok(record);
            }
            let control = DispatchControl::default();
            controls.insert((self.principal.clone(), id.into()), control.clone());
            (record, control)
        };
        let _active = Active {
            shared: &self.shared,
            key: (self.principal.clone(), id.into()),
            control: control.clone(),
        };
        // No invocation can have happened on any error in this preparation block.
        let preparation: Result<MutexGuard<'_, Registry>> = (|| {
            let registry = lock(&self.shared.registry, until)?;
            let gate = lock(&self.shared.dispatch_gate, until)?;
            self.shared.ready()?;
            if control.cancelled() {
                return Err("cancelled_before_dispatch".into());
            }
            let policy = self.shared.policy(&self.principal, until)?;
            let fresh = compile(&record.plan.request, &registry.describe(until)?, &policy)?;
            if digest(&fresh)? != plan_hash {
                return Err("repreview_required".into());
            }
            lock(&self.shared.journal, until)?.dispatch(&self.principal, id, until)?;
            match control.begin_dispatch(until) {
                DispatchDecision::Proceed => (),
                DispatchDecision::Cancelled => return Err("cancelled_before_dispatch".into()),
                DispatchDecision::Expired => return Err("deadline_expired".into()),
            }
            drop(gate);
            Ok(registry)
        })();
        let mut registry = match preparation {
            Ok(registry) => registry,
            Err(_reason) => {
                let cleanup = deadline();
                return lock(&self.shared.journal, cleanup)?.stop_before_dispatch(
                    &self.principal,
                    id,
                    Instant::now() >= until,
                    cleanup,
                );
            }
        };
        let invocation_until =
            until.min(Instant::now() + Duration::from_millis(record.plan.timeout_ms.into()));
        let target = &record.plan.request.target.endpoint_id;
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            registry
                .adapters
                .get_mut(target)
                .ok_or("adapter_unavailable".to_string())?
                .invoke(
                    &self.principal,
                    &record.operation_id,
                    &record.plan.request,
                    invocation_until,
                )
        }));
        let receipt = match result {
            Ok(Ok(receipt))
                if receipt.validate(&record.plan.definition).is_ok()
                    && Instant::now() < invocation_until
                    && !control.cancelled() =>
            {
                receipt
            }
            Err(_) => {
                registry.adapters.remove(target);
                Receipt::Unknown {
                    reason: "adapter_panicked".into(),
                }
            }
            _ => Receipt::Unknown {
                reason: "interrupted_or_invalid_adapter_result".into(),
            },
        };
        drop(registry);
        let cleanup = deadline();
        lock(&self.shared.journal, cleanup)?.finish(&self.principal, id, receipt, cleanup)
    }
    pub fn reconcile(&self, id: &str) -> Result<Record> {
        self.shared.ready()?;
        let until = deadline();
        let record = self.status(id)?.ok_or("unknown_request")?;
        // Active execution still owns its result. Reconciliation cannot race it.
        if lock(&self.shared.controls, until)?.contains_key(&(self.principal.clone(), id.into())) {
            return Err("operation_still_active".into());
        }
        if !matches!(record.state, State::Unknown | State::Dispatching) {
            return Ok(record);
        }
        let mut registry = lock(&self.shared.registry, until)?;
        let gate = lock(&self.shared.dispatch_gate, until)?;
        self.shared.ready()?;
        let policy = self.shared.policy(&self.principal, until)?;
        if !policy.allows(
            &record.plan.request.target.endpoint_id,
            &record.plan.request.action,
        ) {
            return Err("policy_denied".into());
        }
        let target = &record.plan.request.target;
        let adapter = registry
            .adapters
            .get_mut(&target.endpoint_id)
            .ok_or("adapter_unavailable")?;
        let current = adapter.describe_until(until)?;
        current.validate()?;
        if current.binding.authority_id != target.authority_id
            || current.binding.endpoint_id != target.endpoint_id
            || current.binding.registration_generation != target.registration_generation
            || current.binding.catalog_sha256 != target.catalog_sha256
        {
            return Err("adapter_identity_changed".into());
        }
        drop(gate);
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            adapter.reconcile(
                &self.principal,
                &record.operation_id,
                &record.plan.request,
                until,
            )
        }));
        let receipt = match result {
            Ok(Ok(receipt))
                if receipt.validate(&record.plan.definition).is_ok() && Instant::now() < until =>
            {
                receipt
            }
            Err(_) => {
                registry.adapters.remove(&target.endpoint_id);
                Receipt::Unknown {
                    reason: "adapter_panicked".into(),
                }
            }
            _ => Receipt::Unknown {
                reason: "reconciliation_unavailable".into(),
            },
        };
        drop(registry);
        let cleanup = deadline();
        lock(&self.shared.journal, cleanup)?.finish(&self.principal, id, receipt, cleanup)
    }
}
