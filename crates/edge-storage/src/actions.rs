//! Dedicated generic action journal. Trusted host API, not a client API.
//! State changes and their metadata events commit in one SQLite transaction.
use edge_contracts::actions::{Event, Plan, Receipt, Record, State};
use edge_contracts::preview::Effect;
use edge_contracts::{Result, digest, identifier, parse_json};
use edge_core::actions::Policy;
use edge_core::execution::check_deadline;
use fs2::FileExt;
use rusqlite::{Connection, OptionalExtension, Transaction, TransactionBehavior, params};
use std::{
    fs::{self, File},
    os::unix::fs::{DirBuilderExt, MetadataExt},
    path::Path,
    time::{Duration, Instant},
};
use uuid::Uuid;

const APP: i32 = 0x45444131;
const MAX_RECORDS: i64 = 10_000;
const MAX_EVENTS: i64 = 100_000;
const TTL: Duration = Duration::from_secs(60);
pub struct ActionJournal {
    db: Connection,
    _lease: File,
    authority: String,
    session: String,
    started: Instant,
}
fn err(error: impl ToString) -> String {
    error.to_string()
}
fn private(path: &Path) -> Result<File> {
    let file = super::private_file(path)?;
    let meta = file.metadata().map_err(err)?;
    if !meta.is_file() || meta.nlink() != 1 || meta.uid() != nix::unistd::geteuid().as_raw() {
        return Err("unsafe_action_file".into());
    }
    Ok(file)
}
fn event(tx: &Transaction<'_>, principal: &str, id: Option<&str>, kind: &str) -> Result<()> {
    let count: i64 = tx
        .query_row("SELECT count(*) FROM action_events", [], |r| r.get(0))
        .map_err(err)?;
    if count >= MAX_EVENTS {
        return Err("event_capacity".into());
    }
    tx.execute(
        "INSERT INTO action_events(principal,request_id,kind) VALUES (?1,?2,?3)",
        params![principal, id, kind],
    )
    .map_err(err)?;
    Ok(())
}
fn encode(record: &Record) -> Result<String> {
    record.validate()?;
    let json = serde_json::to_string(record).map_err(err)?;
    if json.len() > edge_contracts::MAX_FRAME_BYTES {
        return Err("action_record_too_large".into());
    }
    Ok(json)
}
fn load(db: &Connection, authority: &str, principal: &str, id: &str) -> Result<Option<Record>> {
    let row:Option<(String,String,String,String,i64)>=db.query_row("SELECT operation_id,endpoint,state,record,mutation FROM action_records WHERE principal=?1 AND request_id=?2",params![principal,id],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?))).optional().map_err(err)?;
    row.map(|(operation, endpoint, state, json, mutation)| {
        let record: Record = parse_json(json.as_bytes())?;
        record.validate()?;
        if record.principal != principal
            || record.plan.request.request_id != id
            || record.plan.request.target.authority_id != authority
            || record.operation_id != operation
            || record.plan.request.target.endpoint_id != endpoint
            || state != state_name(record.state)
            || mutation != i64::from(matches!(record.plan.definition.effect, Effect::Write))
        {
            return Err("corrupt_action_index".into());
        }
        Ok(record)
    })
    .transpose()
}
fn state_name(state: State) -> &'static str {
    match state {
        State::Offered => "offered",
        State::Prepared => "prepared",
        State::Dispatching => "dispatching",
        State::Succeeded => "succeeded",
        State::HandedOff => "handed_off",
        State::Failed => "failed",
        State::Unknown => "unknown",
        State::CancelledBeforeDispatch => "cancelled_before_dispatch",
        State::ExpiredBeforeDispatch => "expired_before_dispatch",
    }
}
fn save(tx: &Transaction<'_>, record: &Record, kind: &str) -> Result<()> {
    let changed = tx
        .execute(
            "UPDATE action_records SET state=?1,record=?2 WHERE principal=?3 AND request_id=?4",
            params![
                state_name(record.state),
                encode(record)?,
                record.principal,
                record.plan.request.request_id
            ],
        )
        .map_err(err)?;
    if changed != 1 {
        return Err("missing_action_record".into());
    }
    event(
        tx,
        &record.principal,
        Some(&record.plan.request.request_id),
        kind,
    )
}
fn policy(db: &Connection, authority: &str, principal: &str) -> Result<Policy> {
    let (revision, json): (u32, String) = db
        .query_row(
            "SELECT revision,record FROM action_policies WHERE principal=?1",
            [principal],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()
        .map_err(err)?
        .ok_or("unknown_principal")?;
    let policy: Policy = parse_json(json.as_bytes())?;
    policy.validate()?;
    if policy.authority_id != authority
        || policy.principal != principal
        || policy.revision != revision
    {
        return Err("corrupt_action_policy".into());
    }
    Ok(policy)
}
fn authorized(db: &Connection, authority: &str, record: &Record) -> Result<()> {
    let policy = policy(db, authority, &record.principal)?;
    if digest(&policy)? != record.plan.policy_sha256
        || !policy.allows(
            &record.plan.request.target.endpoint_id,
            &record.plan.request.action,
        )
    {
        return Err("policy_changed_or_revoked".into());
    }
    Ok(())
}
impl ActionJournal {
    pub fn open(directory: &Path, authority: &str) -> Result<Self> {
        identifier(authority)?;
        let fresh = match fs::DirBuilder::new().mode(0o700).create(directory) {
            Ok(()) => true,
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => false,
            Err(e) => return Err(err(e)),
        };
        let meta = fs::symlink_metadata(directory).map_err(err)?;
        if !meta.is_dir()
            || meta.file_type().is_symlink()
            || meta.mode() & 0o077 != 0
            || meta.uid() != nix::unistd::geteuid().as_raw()
        {
            return Err("unsafe_action_directory".into());
        }
        let lease = private(&directory.join("actions.lock"))?;
        lease
            .try_lock_exclusive()
            .map_err(|_| "action_journal_already_owned")?;
        let path = directory.join("actions.sqlite");
        if !fresh && !path.exists() {
            return Err("action_journal_missing".into());
        }
        for name in [
            "actions.sqlite-journal",
            "actions.sqlite-wal",
            "actions.sqlite-shm",
        ] {
            if fs::symlink_metadata(directory.join(name)).is_ok() {
                private(&directory.join(name))?;
            }
        }
        let file = private(&path)?;
        let mut db = Connection::open(path).map_err(err)?;
        db.busy_timeout(Duration::from_millis(250)).map_err(err)?;
        let app: i32 = db
            .query_row("PRAGMA application_id", [], |r| r.get(0))
            .map_err(err)?;
        let version: i32 = db
            .query_row("PRAGMA user_version", [], |r| r.get(0))
            .map_err(err)?;
        if (fresh && (app != 0 || version != 0)) || (!fresh && (app != APP || version != 1)) {
            return Err("incompatible_action_storage".into());
        }
        db.execute_batch("PRAGMA synchronous=FULL; PRAGMA journal_mode=DELETE;")
            .map_err(err)?;
        if fresh {
            let tx = db
                .transaction_with_behavior(TransactionBehavior::Immediate)
                .map_err(err)?;
            tx.execute_batch("CREATE TABLE action_identity(authority TEXT PRIMARY KEY);
                CREATE TABLE action_policies(principal TEXT PRIMARY KEY,revision INTEGER NOT NULL,record TEXT NOT NULL);
                CREATE TABLE action_records(principal TEXT NOT NULL,request_id TEXT NOT NULL,operation_id TEXT UNIQUE NOT NULL,endpoint TEXT NOT NULL,state TEXT NOT NULL,record TEXT NOT NULL,session TEXT NOT NULL,offered_ms INTEGER NOT NULL,approved_until INTEGER,mutation INTEGER NOT NULL,PRIMARY KEY(principal,request_id));
                CREATE INDEX action_fences ON action_records(endpoint,state,mutation);
                CREATE TABLE action_events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,principal TEXT NOT NULL,request_id TEXT,kind TEXT NOT NULL);
                CREATE INDEX action_event_owner ON action_events(principal,sequence);").map_err(err)?;
            tx.execute("INSERT INTO action_identity VALUES (?1)", [authority])
                .map_err(err)?;
            tx.pragma_update(None, "application_id", APP).map_err(err)?;
            tx.pragma_update(None, "user_version", 1).map_err(err)?;
            tx.commit().map_err(err)?;
            file.sync_all().map_err(err)?;
            File::open(directory)
                .map_err(err)?
                .sync_all()
                .map_err(err)?;
        }
        let identity: String = db
            .query_row("SELECT authority FROM action_identity", [], |r| r.get(0))
            .map_err(err)?;
        let count: i64 = db
            .query_row("SELECT count(*) FROM action_identity", [], |r| r.get(0))
            .map_err(err)?;
        if count != 1 || identity != authority {
            return Err("action_authority_mismatch".into());
        }
        let mut journal = Self {
            db,
            _lease: lease,
            authority: authority.into(),
            session: Uuid::new_v4().to_string(),
            started: Instant::now(),
        };
        journal.restart()?;
        Ok(journal)
    }
    fn now(&self) -> i64 {
        self.started.elapsed().as_millis().min(i64::MAX as u128) as i64
    }
    fn budget(&self, deadline: Instant) -> Result<()> {
        check_deadline(deadline)?;
        self.db
            .busy_timeout(deadline.saturating_duration_since(Instant::now()))
            .map_err(err)
    }
    fn restart(&mut self) -> Result<()> {
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(err)?;
        let ids: Vec<(String, String)> = tx
            .prepare("SELECT principal,request_id FROM action_records")
            .map_err(err)?
            .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))
            .map_err(err)?
            .collect::<std::result::Result<_, _>>()
            .map_err(err)?;
        if ids.len() > MAX_RECORDS as usize {
            return Err("action_capacity".into());
        }
        // Validate before transition; the transaction rolls back all changes on corruption.
        for (principal, id) in ids {
            let mut record =
                load(&tx, &self.authority, &principal, &id)?.ok_or("missing_action_record")?;
            match record.state {
                State::Offered => record.state = State::ExpiredBeforeDispatch,
                State::Prepared => record.state = State::CancelledBeforeDispatch,
                State::Dispatching => {
                    record.state = State::Unknown;
                    record.receipt = Some(Receipt::Unknown {
                        reason: "restart_after_intent".into(),
                    });
                }
                _ => continue,
            }
            save(&tx, &record, "restart_fenced")?;
        }
        tx.execute("UPDATE action_records SET approved_until=NULL", [])
            .map_err(err)?;
        tx.commit().map_err(err)
    }
    pub fn policy(&self, principal: &str, deadline: Instant) -> Result<Policy> {
        identifier(principal)?;
        self.budget(deadline)?;
        policy(&self.db, &self.authority, principal)
    }
    /// Owner-only entry point. Caller must serialize updates with its dispatch gate.
    pub fn set_policy(&mut self, updated: &Policy, deadline: Instant) -> Result<()> {
        updated.validate()?;
        if updated.authority_id != self.authority {
            return Err("wrong_authority".into());
        }
        self.budget(deadline)?;
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(err)?;
        let previous: Option<u32> = tx
            .query_row(
                "SELECT revision FROM action_policies WHERE principal=?1",
                [&updated.principal],
                |r| r.get(0),
            )
            .optional()
            .map_err(err)?;
        if previous.is_none() {
            let count: i64 = tx
                .query_row("SELECT count(*) FROM action_policies", [], |r| r.get(0))
                .map_err(err)?;
            if count >= 64 {
                return Err("principal_capacity".into());
            }
        }
        if updated.revision
            != previous
                .unwrap_or(0)
                .checked_add(1)
                .ok_or("policy_revision_exhausted")?
        {
            return Err("invalid_policy_revision".into());
        }
        tx.execute("INSERT INTO action_policies VALUES (?1,?2,?3) ON CONFLICT(principal) DO UPDATE SET revision=excluded.revision,record=excluded.record",params![updated.principal,updated.revision,serde_json::to_string(updated).map_err(err)?]).map_err(err)?;
        event(&tx, &updated.principal, None, "policy_updated")?;
        check_deadline(deadline)?;
        tx.commit().map_err(err)?;
        check_deadline(deadline)
    }
    pub fn lookup(&self, principal: &str, id: &str, deadline: Instant) -> Result<Option<Record>> {
        identifier(principal)?;
        identifier(id)?;
        self.budget(deadline)?;
        load(&self.db, &self.authority, principal, id)
    }
    pub fn offer(&mut self, principal: &str, plan: &Plan, deadline: Instant) -> Result<Record> {
        identifier(principal)?;
        plan.validate()?;
        if plan.request.target.authority_id != self.authority {
            return Err("wrong_authority".into());
        }
        self.budget(deadline)?;
        let now = self.now();
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(err)?;
        if let Some(existing) = load(&tx, &self.authority, principal, &plan.request.request_id)? {
            if digest(&existing.plan)? != digest(plan)? {
                return Err("request_identity_conflict".into());
            }
            return Ok(existing);
        }
        let expired:Vec<(String,String)>=tx.prepare("SELECT principal,request_id FROM action_records WHERE state='offered' AND (session!=?1 OR offered_ms<=?2)").map_err(err)?.query_map(params![self.session,now-TTL.as_millis()as i64],|r|Ok((r.get(0)?,r.get(1)?))).map_err(err)?.collect::<std::result::Result<_,_>>().map_err(err)?;
        for (owner, id) in expired {
            let mut record =
                load(&tx, &self.authority, &owner, &id)?.ok_or("missing_action_record")?;
            record.state = State::ExpiredBeforeDispatch;
            save(&tx, &record, "preview_expired")?;
        }
        let live: i64 = tx
            .query_row(
                "SELECT count(*) FROM action_records WHERE state='offered'",
                [],
                |r| r.get(0),
            )
            .map_err(err)?;
        let all: i64 = tx
            .query_row("SELECT count(*) FROM action_records", [], |r| r.get(0))
            .map_err(err)?;
        if live >= 128 || all >= MAX_RECORDS {
            return Err("action_capacity".into());
        }
        let record = Record {
            schema_version: "edge-action-record.v1".into(),
            principal: principal.into(),
            operation_id: Uuid::new_v4().to_string(),
            plan: plan.clone(),
            state: State::Offered,
            receipt: None,
        };
        authorized(&tx, &self.authority, &record)?;
        tx.execute(
            "INSERT INTO action_records VALUES (?1,?2,?3,?4,?5,?6,?7,?8,NULL,?9)",
            params![
                principal,
                plan.request.request_id,
                record.operation_id,
                plan.request.target.endpoint_id,
                "offered",
                encode(&record)?,
                self.session,
                now,
                i64::from(matches!(plan.definition.effect, Effect::Write))
            ],
        )
        .map_err(err)?;
        event(&tx, principal, Some(&plan.request.request_id), "previewed")?;
        check_deadline(deadline)?;
        tx.commit().map_err(err)?;
        check_deadline(deadline)?;
        Ok(record)
    }
    pub fn approve(
        &mut self,
        principal: &str,
        id: &str,
        hash: &str,
        deadline: Instant,
    ) -> Result<()> {
        self.budget(deadline)?;
        let now = self.now();
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(err)?;
        let record = load(&tx, &self.authority, principal, id)?.ok_or("unknown_request")?;
        authorized(&tx, &self.authority, &record)?;
        if record.state != State::Offered || digest(&record.plan)? != hash {
            return Err("invalid_confirmation".into());
        }
        let changed=tx.execute("UPDATE action_records SET approved_until=offered_ms+?1 WHERE principal=?2 AND request_id=?3 AND session=?4 AND offered_ms>?5 AND approved_until IS NULL",params![TTL.as_millis()as i64,principal,id,self.session,now-TTL.as_millis()as i64]).map_err(err)?;
        if changed == 0 {
            return Err("expired_or_already_approved".into());
        }
        event(&tx, principal, Some(id), "approved")?;
        check_deadline(deadline)?;
        tx.commit().map_err(err)?;
        check_deadline(deadline)
    }
    /// Atomic acceptance; duplicate accepted requests never enter execution twice.
    pub fn admit(
        &mut self,
        principal: &str,
        id: &str,
        hash: &str,
        deadline: Instant,
    ) -> Result<(Record, bool)> {
        self.budget(deadline)?;
        let now = self.now();
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(err)?;
        let mut record = load(&tx, &self.authority, principal, id)?.ok_or("unknown_request")?;
        if digest(&record.plan)? != hash {
            return Err("request_identity_conflict".into());
        }
        if record.state != State::Offered {
            return Ok((record, false));
        }
        authorized(&tx, &self.authority, &record)?;
        consent(&tx, &record, &self.session, now)?;
        record.state = State::Prepared;
        save(&tx, &record, "accepted")?;
        check_deadline(deadline)?;
        tx.commit().map_err(err)?;
        check_deadline(deadline)?;
        Ok((record, true))
    }
    /// Must execute under the host's authorization/dispatch gate.
    pub fn dispatch(&mut self, principal: &str, id: &str, deadline: Instant) -> Result<Record> {
        self.budget(deadline)?;
        let now = self.now();
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(err)?;
        let mut record = load(&tx, &self.authority, principal, id)?.ok_or("unknown_request")?;
        if record.state != State::Prepared {
            return Err("request_not_prepared".into());
        }
        authorized(&tx, &self.authority, &record)?;
        consent(&tx, &record, &self.session, now)?;
        if matches!(record.plan.definition.effect, Effect::Write) {
            let fenced:bool=tx.query_row("SELECT EXISTS(SELECT 1 FROM action_records WHERE endpoint=?1 AND mutation=1 AND state IN ('dispatching','unknown'))",[&record.plan.request.target.endpoint_id],|r|r.get(0)).map_err(err)?;
            if fenced {
                return Err("target_fenced_by_uncertainty".into());
            }
        }
        record.state = State::Dispatching;
        save(&tx, &record, "dispatch_intent")?;
        check_deadline(deadline)?;
        tx.commit().map_err(err)?;
        check_deadline(deadline)?;
        Ok(record)
    }
    pub fn finish(
        &mut self,
        principal: &str,
        id: &str,
        receipt: Receipt,
        deadline: Instant,
    ) -> Result<Record> {
        self.budget(deadline)?;
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(err)?;
        let mut record = load(&tx, &self.authority, principal, id)?.ok_or("unknown_request")?;
        if !matches!(record.state, State::Dispatching | State::Unknown) {
            return Ok(record);
        }
        receipt.validate(&record.plan.definition)?;
        record.state = State::from_receipt(&receipt);
        record.receipt = Some(receipt);
        save(&tx, &record, "receipt_recorded")?;
        check_deadline(deadline)?;
        tx.commit().map_err(err)?;
        Ok(record)
    }
    /// Host proof that invoke has NOT begun. Not a public cancellation primitive.
    pub fn stop_before_dispatch(
        &mut self,
        principal: &str,
        id: &str,
        expired: bool,
        deadline: Instant,
    ) -> Result<Record> {
        self.budget(deadline)?;
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(err)?;
        let mut record = load(&tx, &self.authority, principal, id)?.ok_or("unknown_request")?;
        if matches!(
            record.state,
            State::Offered | State::Prepared | State::Dispatching | State::Unknown
        ) {
            record.state = if expired {
                State::ExpiredBeforeDispatch
            } else {
                State::CancelledBeforeDispatch
            };
            record.receipt = None;
            save(&tx, &record, "stopped_before_dispatch")?;
        }
        check_deadline(deadline)?;
        tx.commit().map_err(err)?;
        Ok(record)
    }
    pub fn cancel(&mut self, principal: &str, id: &str, deadline: Instant) -> Result<Record> {
        self.budget(deadline)?;
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(err)?;
        let mut record = load(&tx, &self.authority, principal, id)?.ok_or("unknown_request")?;
        match record.state {
            State::Offered | State::Prepared => {
                record.state = State::CancelledBeforeDispatch;
                record.receipt = None;
            }
            State::Dispatching => {
                record.state = State::Unknown;
                record.receipt = Some(Receipt::Unknown {
                    reason: "cancel_after_intent".into(),
                });
            }
            _ => return Ok(record),
        }
        save(&tx, &record, "cancelled")?;
        check_deadline(deadline)?;
        tx.commit().map_err(err)?;
        Ok(record)
    }
    pub fn events(
        &self,
        principal: &str,
        after: u64,
        limit: u32,
        deadline: Instant,
    ) -> Result<Vec<Event>> {
        identifier(principal)?;
        if after > edge_contracts::MAX_SAFE_INTEGER as u64 || !(1..=100).contains(&limit) {
            return Err("invalid_event_page".into());
        }
        self.budget(deadline)?;
        let mut stmt=self.db.prepare("SELECT sequence,request_id,kind FROM action_events WHERE principal=?1 AND sequence>?2 ORDER BY sequence LIMIT ?3").map_err(err)?;
        let rows = stmt
            .query_map(params![principal, after, limit], |r| {
                Ok(Event {
                    sequence: r.get(0)?,
                    principal: principal.into(),
                    request_id: r.get(1)?,
                    kind: r.get(2)?,
                })
            })
            .map_err(err)?
            .collect::<std::result::Result<Vec<_>, _>>()
            .map_err(err)?;
        for row in &rows {
            identifier(&row.kind)?;
            if let Some(id) = &row.request_id {
                identifier(id)?;
            }
        }
        Ok(rows)
    }
}
fn consent(db: &Connection, record: &Record, session: &str, now: i64) -> Result<()> {
    let (stored,offered,approved):(String,i64,Option<i64>)=db.query_row("SELECT session,offered_ms,approved_until FROM action_records WHERE principal=?1 AND request_id=?2",params![record.principal,record.plan.request.request_id],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?))).map_err(err)?;
    if stored != session || now - offered >= TTL.as_millis() as i64 {
        return Err("preview_expired".into());
    }
    if matches!(record.plan.definition.effect, Effect::Write)
        && approved.is_none_or(|until| until <= now)
    {
        return Err("approval_required".into());
    }
    Ok(())
}
