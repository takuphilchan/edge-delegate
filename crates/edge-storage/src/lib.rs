//! Experimental SQLite journal for trusted local embedding. No authentication service.
//! One owner per journal directory. Not a global cross-journal/device ownership lock.

pub mod admission;
use edge_contracts::{MAX_FRAME_BYTES, Result, digest, fingerprint, identifier, parse_json};
use edge_core::{
    Plan,
    execution::{Claim, Journal, Operation, OperationState, Receipt, check_deadline},
};
use fs2::FileExt;
use rusqlite::{Connection, OptionalExtension, Transaction, TransactionBehavior, params};
use std::{
    fs::{self, File, OpenOptions},
    path::{Path, PathBuf},
    sync::Arc,
    time::{Duration, Instant},
};
use uuid::Uuid;

const APPLICATION_ID: i32 = 0x45444732;
pub const APPROVAL_TTL: Duration = Duration::from_secs(60);

fn err(error: impl ToString) -> String {
    error.to_string()
}

/// Hold this handle for the entire authority lifetime. Never open a legacy journal here.
pub struct SqliteJournal {
    connection: Connection,
    _lease: Arc<File>,
    path: PathBuf,
    authority: String,
    session: String,
    started: Instant,
}

fn private_file(path: &Path) -> Result<File> {
    if path
        .symlink_metadata()
        .is_ok_and(|meta| meta.file_type().is_symlink())
    {
        return Err("journal_symlink_forbidden".into());
    }
    let mut options = OpenOptions::new();
    options.read(true).write(true).create(true).truncate(false);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let file = options.open(path).map_err(err)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if file.metadata().map_err(err)?.permissions().mode() & 0o077 != 0 {
            return Err("journal_permissions_too_broad".into());
        }
    }
    Ok(file)
}

fn validate_plan(plan: &Plan, authority: &str) -> Result<()> {
    if plan.schema_version != "edge-plan.v2"
        || plan.authority_id != authority
        || plan.steps.len() != 1
    {
        return Err("invalid_single_operation_plan".into());
    }
    identifier(&plan.request_id)?;
    fingerprint(&plan.request_sha256)?;
    fingerprint(&plan.policy_sha256)?;
    let step = &plan.steps[0];
    step.target.validate()?;
    identifier(&step.step_id)?;
    identifier(&step.action)?;
    if step.target.authority_id != authority
        || !(1..=5000).contains(&step.timeout_ms)
        || step.parameters.len() > 16
    {
        return Err("invalid_plan_step".into());
    }
    for (name, parameter) in &step.parameters {
        identifier(name)?;
        parameter.validate()?;
    }
    Ok(())
}

fn decode(text: &str, authority: &str) -> Result<Operation> {
    let record: Operation = parse_json(text.as_bytes())?;
    identifier(&record.operation_id)?;
    identifier(&record.principal)?;
    validate_plan(&record.plan, authority)?;
    if record.request_id != record.plan.request_id
        || record.request_sha256 != record.plan.request_sha256
    {
        return Err("corrupt_operation_binding".into());
    }
    if let Some(receipt) = &record.receipt {
        receipt.validate()?;
        if record.state != receipt.state() {
            return Err("corrupt_receipt_state".into());
        }
    } else if matches!(
        record.state,
        OperationState::Succeeded | OperationState::Failed
    ) {
        return Err("missing_terminal_receipt".into());
    }
    Ok(record)
}

fn encode(record: &Operation) -> Result<String> {
    let encoded = serde_json::to_string(record).map_err(err)?;
    if encoded.len() > MAX_FRAME_BYTES {
        return Err("operation_record_too_large".into());
    }
    Ok(encoded)
}

fn state_name(state: OperationState) -> &'static str {
    match state {
        OperationState::Prepared => "prepared",
        OperationState::Dispatching => "dispatching",
        OperationState::Succeeded => "succeeded",
        OperationState::Failed => "failed",
        OperationState::Unknown => "unknown",
        OperationState::CancelledBeforeDispatch => "cancelled_before_dispatch",
        OperationState::ExpiredBeforeDispatch => "expired_before_dispatch",
    }
}

fn update(tx: &Transaction<'_>, record: &Operation) -> Result<()> {
    if tx
        .execute(
            "UPDATE operations SET state=?1, record=?2 WHERE operation_id=?3",
            params![
                state_name(record.state),
                encode(record)?,
                record.operation_id
            ],
        )
        .map_err(err)?
        != 1
    {
        return Err("unknown_operation".into());
    }
    Ok(())
}

fn load(conn: &Connection, id: &str, authority: &str) -> Result<Operation> {
    let text: String = conn
        .query_row(
            "SELECT record FROM operations WHERE operation_id=?1",
            [id],
            |r| r.get(0),
        )
        .map_err(err)?;
    let record = decode(&text, authority)?;
    verify_indexes(conn, &record)?;
    Ok(record)
}

fn verify_indexes(conn: &Connection, record: &Operation) -> Result<()> {
    let matches: bool = conn
        .query_row(
            "SELECT EXISTS(SELECT 1 FROM operations WHERE operation_id=?1
        AND principal=?2 AND request_id=?3 AND endpoint=?4 AND state=?5)",
            params![
                record.operation_id,
                record.principal,
                record.request_id,
                record.plan.steps[0].target.endpoint_id,
                state_name(record.state)
            ],
            |r| r.get(0),
        )
        .map_err(err)?;
    if !matches {
        return Err("corrupt_operation_index".into());
    }
    Ok(())
}

/// Read the serialized record and its indexed columns in one SQLite snapshot.
/// A second query can observe a later commit and falsely report corruption.
fn lookup_operation(
    conn: &Connection,
    principal: &str,
    request_id: &str,
    authority: &str,
) -> Result<Option<Operation>> {
    struct Row {
        record: String,
        operation_id: String,
        principal: String,
        request_id: String,
        endpoint: String,
        state: String,
    }
    let row = conn
        .query_row(
            "SELECT record,operation_id,principal,request_id,endpoint,state FROM operations
             WHERE principal=?1 AND request_id=?2",
            params![principal, request_id],
            |r| {
                Ok(Row {
                    record: r.get(0)?,
                    operation_id: r.get(1)?,
                    principal: r.get(2)?,
                    request_id: r.get(3)?,
                    endpoint: r.get(4)?,
                    state: r.get(5)?,
                })
            },
        )
        .optional()
        .map_err(err)?;
    row.map(|row| {
        let record = decode(&row.record, authority)?;
        if record.operation_id != row.operation_id
            || record.principal != row.principal
            || record.request_id != row.request_id
            || record.plan.steps[0].target.endpoint_id != row.endpoint
            || state_name(record.state) != row.state
        {
            return Err("corrupt_operation_index".into());
        }
        Ok(record)
    })
    .transpose()
}

impl SqliteJournal {
    pub fn open(directory: &Path, authority: &str) -> Result<Self> {
        identifier(authority)?;
        if directory
            .symlink_metadata()
            .is_ok_and(|meta| meta.file_type().is_symlink())
        {
            return Err("journal_directory_symlink_forbidden".into());
        }
        if !directory.exists() {
            let builder = fs::DirBuilder::new();
            #[cfg(unix)]
            let mut builder = builder;
            #[cfg(unix)]
            {
                use std::os::unix::fs::DirBuilderExt;
                builder.mode(0o700);
            }
            builder.create(directory).map_err(err)?;
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            if directory.metadata().map_err(err)?.permissions().mode() & 0o077 != 0 {
                return Err("journal_directory_permissions_too_broad".into());
            }
        }
        let lease = private_file(&directory.join("journal.lock"))?;
        lease
            .try_lock_exclusive()
            .map_err(|_| "journal_already_owned".to_string())?;
        let path = directory.join("journal-v2.sqlite");
        drop(private_file(&path)?);
        let mut connection = Connection::open(&path).map_err(err)?;
        connection
            .busy_timeout(Duration::from_millis(250))
            .map_err(err)?;
        let app_id: i32 = connection
            .query_row("PRAGMA application_id", [], |r| r.get(0))
            .map_err(err)?;
        let version: i32 = connection
            .query_row("PRAGMA user_version", [], |r| r.get(0))
            .map_err(err)?;
        let tables: i64 = connection
            .query_row(
                "SELECT count(*) FROM sqlite_master WHERE type='table'",
                [],
                |r| r.get(0),
            )
            .map_err(err)?;
        if !((app_id == 0 && version == 0 && tables == 0)
            || (app_id == APPLICATION_ID && matches!(version, 1 | 2)))
        {
            return Err("unsupported_or_legacy_database".into());
        }
        connection
            .execute_batch("PRAGMA synchronous=FULL; PRAGMA journal_mode=DELETE;")
            .map_err(err)?;
        if version == 1 {
            let stored: String = connection
                .query_row("SELECT authority FROM metadata", [], |r| r.get(0))
                .map_err(err)?;
            if stored != authority {
                return Err("journal_authority_mismatch".into());
            }
            // SQLite creates a consistent snapshot, including live WAL content if present.
            // Retain the backup even if migration fails. Never overwrite earlier evidence.
            let backup = directory.join(format!("before-schema-2-{}.sqlite", Uuid::new_v4()));
            let file = private_file(&backup)?;
            connection
                .execute(
                    "VACUUM INTO ?1",
                    [backup.to_str().ok_or("invalid_backup_path")?],
                )
                .map_err(err)?;
            file.sync_all().map_err(err)?;
            #[cfg(unix)]
            File::open(directory)
                .map_err(err)?
                .sync_all()
                .map_err(err)?;
        }
        let tx = connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(err)?;
        if version == 0 {
            tx.execute_batch("CREATE TABLE metadata(authority TEXT NOT NULL);
                CREATE TABLE operations(operation_id TEXT PRIMARY KEY, principal TEXT NOT NULL,
                    request_id TEXT NOT NULL, endpoint TEXT NOT NULL, state TEXT NOT NULL, record TEXT NOT NULL, approval_hash TEXT,
                    UNIQUE(principal,request_id));
                CREATE INDEX target_fence ON operations(endpoint,state);
                CREATE TABLE approvals(token_hash TEXT PRIMARY KEY, principal TEXT NOT NULL, request_id TEXT NOT NULL,
                    plan_hash TEXT NOT NULL, session TEXT NOT NULL, expires_ms INTEGER NOT NULL, consumed INTEGER NOT NULL);").map_err(err)?;
            tx.execute("INSERT INTO metadata VALUES (?1)", [authority])
                .map_err(err)?;
            tx.pragma_update(None, "application_id", APPLICATION_ID)
                .map_err(err)?;
        }
        if version < 2 {
            tx.execute_batch(
                "CREATE TABLE admissions(principal TEXT NOT NULL, request_id TEXT NOT NULL,
                record TEXT NOT NULL, PRIMARY KEY(principal,request_id));",
            )
            .map_err(err)?;
            tx.pragma_update(None, "user_version", 2).map_err(err)?;
        }
        let stored: String = tx
            .query_row("SELECT authority FROM metadata", [], |r| r.get(0))
            .map_err(err)?;
        if stored != authority {
            return Err("journal_authority_mismatch".into());
        }
        // Validate all records before applying restart transitions. Corruption fails closed.
        let records: Vec<String> = tx
            .prepare("SELECT record FROM operations")
            .map_err(err)?
            .query_map([], |r| r.get(0))
            .map_err(err)?
            .collect::<std::result::Result<_, _>>()
            .map_err(err)?;
        for text in records {
            let mut record = decode(&text, authority)?;
            verify_indexes(&tx, &record)?;
            match record.state {
                OperationState::Prepared => {
                    record.state = OperationState::CancelledBeforeDispatch;
                    update(&tx, &record)?;
                }
                OperationState::Dispatching => {
                    record.state = OperationState::Unknown;
                    record.receipt = Some(Receipt::Unknown {
                        reason: "restart_after_dispatch_intent".into(),
                    });
                    update(&tx, &record)?;
                }
                _ => (),
            }
        }
        admission::recover(&tx, authority)?;
        tx.commit().map_err(err)?;
        Ok(Self {
            connection,
            _lease: Arc::new(lease),
            path,
            authority: authority.into(),
            session: Uuid::new_v4().to_string(),
            started: Instant::now(),
        })
    }

    fn budget(&self, deadline: Instant) -> Result<()> {
        check_deadline(deadline)?;
        self.connection
            .busy_timeout(
                deadline
                    .saturating_duration_since(Instant::now())
                    .min(Duration::from_millis(250)),
            )
            .map_err(err)
    }

    /// Trusted operator API only. A remote client must not be allowed to call this
    /// without authenticated approval authority. No client-provided approval boolean.
    pub fn approve(&mut self, principal: &str, plan: &Plan, deadline: Instant) -> Result<String> {
        identifier(principal)?;
        validate_plan(plan, &self.authority)?;
        self.budget(deadline)?;
        let token = Uuid::new_v4().to_string();
        let tx = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(err)?;
        tx.execute(
            "INSERT INTO approvals VALUES (?1,?2,?3,?4,?5,?6,0)",
            params![
                digest(&token)?,
                principal,
                plan.request_id,
                digest(plan)?,
                self.session,
                (self.started.elapsed() + APPROVAL_TTL).as_millis() as i64
            ],
        )
        .map_err(err)?;
        check_deadline(deadline)?;
        tx.commit().map_err(err)?;
        check_deadline(deadline)?;
        Ok(token)
    }

    pub fn revoke(&mut self, token: &str, deadline: Instant) -> Result<()> {
        self.budget(deadline)?;
        self.connection
            .execute(
                "DELETE FROM approvals WHERE token_hash=?1",
                [digest(&token)?],
            )
            .map_err(err)?;
        check_deadline(deadline)
    }

    /// No rollback guarantee: a dispatched operation remains unknown until reconciliation.
    pub fn cancel(
        &mut self,
        principal: &str,
        request_id: &str,
        deadline: Instant,
    ) -> Result<Operation> {
        let record = self
            .lookup(principal, request_id, deadline)?
            .ok_or("unknown_request")?;
        match record.state {
            OperationState::Prepared => {
                self.stop_before_dispatch(&record.operation_id, false, deadline)
            }
            OperationState::Dispatching | OperationState::Unknown => self.finish(
                &record.operation_id,
                Receipt::Unknown {
                    reason: "cancellation_after_dispatch".into(),
                },
                deadline,
            ),
            _ => Ok(record),
        }
    }
}

impl Journal for SqliteJournal {
    fn authority_id(&self) -> &str {
        &self.authority
    }

    fn lookup(
        &mut self,
        principal: &str,
        request_id: &str,
        deadline: Instant,
    ) -> Result<Option<Operation>> {
        identifier(principal)?;
        identifier(request_id)?;
        self.budget(deadline)?;
        let operation = lookup_operation(&self.connection, principal, request_id, &self.authority)?;
        check_deadline(deadline)?;
        Ok(operation)
    }

    fn claim(
        &mut self,
        principal: &str,
        plan: &Plan,
        approval: Option<&str>,
        requires_approval: bool,
        deadline: Instant,
    ) -> Result<Claim> {
        identifier(principal)?;
        validate_plan(plan, &self.authority)?;
        self.budget(deadline)?;
        let plan_hash = digest(plan)?;
        let tx = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(err)?;
        let existing: Option<String> = tx
            .query_row(
                "SELECT record FROM operations WHERE principal=?1 AND request_id=?2",
                params![principal, plan.request_id],
                |r| r.get(0),
            )
            .optional()
            .map_err(err)?;
        if let Some(text) = existing {
            let record = decode(&text, &self.authority)?;
            verify_indexes(&tx, &record)?;
            if digest(&record.plan)? != plan_hash {
                return Err("request_identity_conflict".into());
            }
            return Ok(Claim::Existing(record));
        }
        admission::check_dispatch(&tx, principal, plan, &self.session, &self.authority)?;
        let endpoint = &plan.steps[0].target.endpoint_id;
        let fenced: bool = tx.query_row("SELECT EXISTS(SELECT 1 FROM operations WHERE endpoint=?1 AND state IN ('prepared','dispatching','unknown'))",
            [endpoint], |r| r.get(0)).map_err(err)?;
        if fenced {
            return Err("target_fenced_by_unresolved_operation".into());
        }
        if requires_approval {
            let token = approval.ok_or("approval_required")?;
            if token.len() > 128 {
                return Err("invalid_approval".into());
            }
            let changed = tx.execute("UPDATE approvals SET consumed=1 WHERE token_hash=?1 AND principal=?2 AND request_id=?3
                AND plan_hash=?4 AND session=?5 AND expires_ms>?6 AND consumed=0", params![digest(&token)?, principal,
                    plan.request_id, plan_hash, self.session, self.started.elapsed().as_millis() as i64]).map_err(err)?;
            if changed != 1 {
                return Err("invalid_expired_or_consumed_approval".into());
            }
        }
        let record = Operation {
            operation_id: Uuid::new_v4().to_string(),
            principal: principal.into(),
            request_id: plan.request_id.clone(),
            request_sha256: plan.request_sha256.clone(),
            plan: plan.clone(),
            state: OperationState::Prepared,
            receipt: None,
        };
        tx.execute(
            "INSERT INTO operations VALUES (?1,?2,?3,?4,?5,?6,?7)",
            params![
                record.operation_id,
                principal,
                plan.request_id,
                endpoint,
                state_name(record.state),
                encode(&record)?,
                if requires_approval {
                    approval.map(|token| digest(&token)).transpose()?
                } else {
                    None
                }
            ],
        )
        .map_err(err)?;
        check_deadline(deadline)?;
        tx.commit().map_err(err)?;
        check_deadline(deadline)?;
        Ok(Claim::New(record))
    }

    fn dispatch_intent(&mut self, id: &str, deadline: Instant) -> Result<Operation> {
        self.budget(deadline)?;
        let tx = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(err)?;
        let mut record = load(&tx, id, &self.authority)?;
        if record.state == OperationState::Prepared {
            let approval_hash: Option<String> = tx
                .query_row(
                    "SELECT approval_hash FROM operations WHERE operation_id=?1",
                    [id],
                    |r| r.get(0),
                )
                .map_err(err)?;
            let valid = if let Some(hash) = approval_hash {
                tx.query_row(
                    "SELECT EXISTS(SELECT 1 FROM approvals WHERE token_hash=?1 AND session=?2
                    AND expires_ms>?3 AND consumed=1)",
                    params![
                        hash,
                        self.session,
                        self.started.elapsed().as_millis() as i64
                    ],
                    |r| r.get::<_, bool>(0),
                )
                .map_err(err)?
            } else {
                true
            };
            let valid = valid
                && admission::check_dispatch(
                    &tx,
                    &record.principal,
                    &record.plan,
                    &self.session,
                    &self.authority,
                )
                .is_ok();
            record.state = if valid {
                OperationState::Dispatching
            } else {
                OperationState::CancelledBeforeDispatch
            };
            update(&tx, &record)?;
        }
        check_deadline(deadline)?;
        tx.commit().map_err(err)?;
        check_deadline(deadline)?;
        Ok(record)
    }

    fn stop_before_dispatch(
        &mut self,
        id: &str,
        expired: bool,
        deadline: Instant,
    ) -> Result<Operation> {
        self.budget(deadline)?;
        let tx = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(err)?;
        let mut record = load(&tx, id, &self.authority)?;
        // Only a trusted coordinator that has NOT invoked may use this transition.
        // Public cancellation of dispatched work still uses cancel() -> Unknown.
        if matches!(
            record.state,
            OperationState::Prepared | OperationState::Dispatching
        ) {
            record.state = if expired {
                OperationState::ExpiredBeforeDispatch
            } else {
                OperationState::CancelledBeforeDispatch
            };
            update(&tx, &record)?;
        }
        check_deadline(deadline)?;
        tx.commit().map_err(err)?;
        check_deadline(deadline)?;
        Ok(record)
    }

    fn finish(&mut self, id: &str, receipt: Receipt, deadline: Instant) -> Result<Operation> {
        receipt.validate()?;
        self.budget(deadline)?;
        let tx = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(err)?;
        let mut record = load(&tx, id, &self.authority)?;
        if !matches!(
            record.state,
            OperationState::Dispatching | OperationState::Unknown
        ) {
            return Err("terminal_or_undispatched_operation_is_immutable".into());
        }
        record.state = receipt.state();
        record.receipt = Some(receipt);
        update(&tx, &record)?;
        check_deadline(deadline)?;
        tx.commit().map_err(err)?;
        check_deadline(deadline)?;
        Ok(record)
    }
}
