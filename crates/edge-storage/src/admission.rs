//! A second connection under the same journal lease allows durable admission/cancellation
//! without waiting for adapter I/O. Both writers use the same SQLite transaction domain.
use super::*;
use edge_contracts::{
    ControlRequest,
    admission::{Admission, AdmissionState},
};

pub const MAX_ADMISSIONS: i64 = 10_000;

pub struct AdmissionWriter {
    connection: Connection,
    _lease: Arc<File>,
    authority: String,
    session: String,
    started: Instant,
}

impl SqliteJournal {
    pub fn admission_writer(&self) -> Result<AdmissionWriter> {
        let connection = Connection::open(&self.path).map_err(err)?;
        connection
            .execute_batch("PRAGMA synchronous=FULL;")
            .map_err(err)?;
        Ok(AdmissionWriter {
            connection,
            _lease: self._lease.clone(),
            authority: self.authority.clone(),
            session: self.session.clone(),
            started: self.started,
        })
    }
}

fn decode_admission(text: &str, authority: &str) -> Result<Admission> {
    let row: Admission = parse_json(text.as_bytes())?;
    identifier(&row.principal)?;
    identifier(&row.session)?;
    row.request.validate()?;
    validate_plan(&row.plan, authority)?;
    if row.schema_version != "edge-admission.v1"
        || row.request.authority_id != authority
        || row.request.request_id != row.plan.request_id
        || digest(&row.request)? != row.plan.request_sha256
    {
        return Err("corrupt_admission_binding".into());
    }
    Ok(row)
}
fn encode_admission(row: &Admission) -> Result<String> {
    let text = serde_json::to_string(row).map_err(err)?;
    if text.len() > MAX_FRAME_BYTES {
        return Err("admission_too_large".into());
    }
    Ok(text)
}
fn load_admission(
    conn: &Connection,
    principal: &str,
    id: &str,
    authority: &str,
) -> Result<Option<Admission>> {
    let text: Option<String> = conn
        .query_row(
            "SELECT record FROM admissions WHERE principal=?1 AND request_id=?2",
            params![principal, id],
            |r| r.get(0),
        )
        .optional()
        .map_err(err)?;
    text.map(|text| {
        let row = decode_admission(&text, authority)?;
        if row.principal != principal || row.request.request_id != id {
            return Err("corrupt_admission_index".into());
        }
        Ok(row)
    })
    .transpose()
}
fn store(tx: &Transaction<'_>, row: &Admission) -> Result<()> {
    if tx
        .execute(
            "UPDATE admissions SET record=?1 WHERE principal=?2 AND request_id=?3",
            params![
                encode_admission(row)?,
                row.principal,
                row.request.request_id
            ],
        )
        .map_err(err)?
        != 1
    {
        return Err("unknown_admission".into());
    }
    Ok(())
}
pub(crate) fn recover(tx: &Transaction<'_>, authority: &str) -> Result<()> {
    let rows: Vec<(String, String)> = tx
        .prepare("SELECT principal,request_id FROM admissions")
        .map_err(err)?
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))
        .map_err(err)?
        .collect::<std::result::Result<_, _>>()
        .map_err(err)?;
    if rows.len() > MAX_ADMISSIONS as usize {
        return Err("admission_capacity_exceeded".into());
    }
    for (principal, id) in rows {
        let mut row = load_admission(tx, &principal, &id, authority)?.ok_or("unknown_admission")?;
        if row.state == AdmissionState::Accepted {
            row.state = AdmissionState::Interrupted;
            store(tx, &row)?;
        }
    }
    Ok(())
}
pub(crate) fn check_dispatch(
    conn: &Connection,
    principal: &str,
    plan: &Plan,
    session: &str,
    authority: &str,
) -> Result<()> {
    if let Some(row) = load_admission(conn, principal, &plan.request_id, authority)? {
        if row.session != session
            || row.state != AdmissionState::Accepted
            || row.cancellation_requested
        {
            return Err("admission_fenced".into());
        }
        if digest(&row.plan)? != digest(plan)? {
            return Err("admission_plan_changed".into());
        }
    }
    // Direct legacy embedding does not create admissions. Existing behavior is preserved.
    Ok(())
}

impl AdmissionWriter {
    pub fn inspect_operation(
        &self,
        principal: &str,
        id: &str,
        deadline: Instant,
    ) -> Result<Option<Operation>> {
        identifier(principal)?;
        identifier(id)?;
        self.budget(deadline)?;
        let operation = lookup_operation(&self.connection, principal, id, &self.authority)?;
        check_deadline(deadline)?;
        Ok(operation)
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
    pub fn inspect(
        &self,
        principal: &str,
        id: &str,
        deadline: Instant,
    ) -> Result<Option<Admission>> {
        identifier(principal)?;
        identifier(id)?;
        self.budget(deadline)?;
        let row = load_admission(&self.connection, principal, id, &self.authority)?;
        check_deadline(deadline)?;
        Ok(row)
    }
    /// Durable acceptance binds the exact owner-approved plan. Does not consume the
    /// approval or authorize dispatch; the coordinator must still check it freshly.
    pub fn admit(
        &mut self,
        principal: &str,
        request: &ControlRequest,
        plan: &Plan,
        token: &str,
        deadline: Instant,
    ) -> Result<Admission> {
        identifier(principal)?;
        request.validate()?;
        validate_plan(plan, &self.authority)?;
        if token.len() > 128
            || request.authority_id != self.authority
            || request.request_id != plan.request_id
            || digest(request)? != plan.request_sha256
        {
            return Err("invalid_admission_binding".into());
        }
        self.budget(deadline)?;
        let tx = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(err)?;
        if let Some(row) = load_admission(&tx, principal, &request.request_id, &self.authority)? {
            if digest(&row.request)? != digest(request)? || digest(&row.plan)? != digest(plan)? {
                return Err("request_identity_conflict".into());
            }
            return Ok(row);
        }
        let count: i64 = tx
            .query_row("SELECT count(*) FROM admissions", [], |r| r.get(0))
            .map_err(err)?;
        if count >= MAX_ADMISSIONS {
            return Err("admission_capacity_reached".into());
        }
        let authorized: bool = tx.query_row("SELECT EXISTS(SELECT 1 FROM approvals WHERE token_hash=?1 AND principal=?2 AND request_id=?3 AND plan_hash=?4 AND session=?5 AND expires_ms>?6 AND consumed=0)",
            params![digest(&token)?, principal, request.request_id, digest(plan)?, self.session, self.started.elapsed().as_millis() as i64], |r| r.get(0)).map_err(err)?;
        if !authorized {
            return Err("invalid_expired_or_consumed_approval".into());
        }
        let row = Admission {
            schema_version: "edge-admission.v1".into(),
            principal: principal.into(),
            request: request.clone(),
            plan: plan.clone(),
            session: self.session.clone(),
            state: AdmissionState::Accepted,
            cancellation_requested: false,
        };
        tx.execute(
            "INSERT INTO admissions VALUES (?1,?2,?3)",
            params![principal, request.request_id, encode_admission(&row)?],
        )
        .map_err(err)?;
        check_deadline(deadline)?;
        tx.commit().map_err(err)?;
        check_deadline(deadline)?;
        Ok(row)
    }
    /// Records intent to cancel, not proof of no physical effect. Returns false if
    /// admission has not committed yet; the host must retain its in-memory fence.
    pub fn request_cancel(&mut self, principal: &str, id: &str, deadline: Instant) -> Result<bool> {
        identifier(principal)?;
        identifier(id)?;
        self.budget(deadline)?;
        let tx = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(err)?;
        let Some(mut row) = load_admission(&tx, principal, id, &self.authority)? else {
            return Ok(false);
        };
        row.cancellation_requested = true;
        store(&tx, &row)?;
        check_deadline(deadline)?;
        tx.commit().map_err(err)?;
        check_deadline(deadline)?;
        Ok(true)
    }
    /// Coordinator-only completion. Finished describes the attempt; consult the
    /// operation journal for success, failure or an unknown physical outcome.
    pub fn stop(
        &mut self,
        principal: &str,
        id: &str,
        state: AdmissionState,
        deadline: Instant,
    ) -> Result<()> {
        identifier(principal)?;
        identifier(id)?;
        if !matches!(
            state,
            AdmissionState::Finished
                | AdmissionState::CancelledBeforeDispatch
                | AdmissionState::ExpiredBeforeDispatch
                | AdmissionState::Interrupted
        ) {
            return Err("invalid_admission_transition".into());
        }
        self.budget(deadline)?;
        let tx = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(err)?;
        let mut row =
            load_admission(&tx, principal, id, &self.authority)?.ok_or("unknown_admission")?;
        if row.session != self.session {
            return Err("admission_session_expired".into());
        }
        if row.state == AdmissionState::Accepted {
            row.state = state;
            store(&tx, &row)?;
        }
        check_deadline(deadline)?;
        tx.commit().map_err(err)?;
        check_deadline(deadline)
    }
}
