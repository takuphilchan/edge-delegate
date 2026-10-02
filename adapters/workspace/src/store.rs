use super::*;
use edge_contracts::actions::{Output, Receipt, Request, validate_fields};
use edge_contracts::{identifier, parse_json};
use edge_core::actions::Adapter;
use edge_core::execution::check_deadline;
use fs2::FileExt;
use nix::unistd::geteuid;
use rusqlite::{Connection, OptionalExtension, Transaction, TransactionBehavior, params};
use std::{
    fs::{self, File, OpenOptions},
    os::unix::fs::{DirBuilderExt, MetadataExt, OpenOptionsExt},
    path::Path,
    time::Instant,
};
use uuid::Uuid;

const APP_ID: i32 = 0x45444e31;
const MAX_RECEIPTS: i64 = 10_000;
pub struct Workspace {
    // Fields drop in declaration order: close SQLite before releasing ownership.
    db: Connection,
    _lease: WorkspaceLease,
    endpoint: Endpoint,
}

// Keep an acquired lock until the actual owner has finished, not until every
// incidental descriptor inherited by an unrelated child has been closed.
struct WorkspaceLease {
    file: File,
    owner_process: u32,
}

impl WorkspaceLease {
    fn acquire(path: &Path) -> Result<Self> {
        let file = private_file(path)?;
        file.try_lock_exclusive()
            .map_err(|_| "workspace_already_owned")?;
        Ok(Self {
            file,
            owner_process: std::process::id(),
        })
    }
}

impl Drop for WorkspaceLease {
    fn drop(&mut self) {
        // A forked copy must not unlock the still-live parent's authority.
        // Workspace/SQLite objects themselves are not supported across fork.
        if self.owner_process == std::process::id() {
            let _ = FileExt::unlock(&self.file);
        }
        // Closing the owned file remains the non-panicking fallback on error.
    }
}

fn error(e: impl ToString) -> String {
    e.to_string()
}

fn private_file(path: &Path) -> Result<File> {
    if let Ok(meta) = fs::symlink_metadata(path)
        && (!meta.is_file()
            || meta.file_type().is_symlink()
            || meta.nlink() != 1
            || meta.uid() != geteuid().as_raw()
            || meta.mode() & 0o077 != 0)
    {
        return Err("unsafe_workspace_file".into());
    }
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .open(path)
        .map_err(error)?;
    let before = fs::symlink_metadata(path).map_err(error)?;
    let after = file.metadata().map_err(error)?;
    if before.file_type().is_symlink()
        || before.ino() != after.ino()
        || before.dev() != after.dev()
        || after.nlink() != 1
        || after.mode() & 0o077 != 0
        || after.uid() != geteuid().as_raw()
    {
        return Err("workspace_file_changed".into());
    }
    Ok(file)
}
impl Workspace {
    /// Dedicated directory only; never adopts existing legacy storage. A new
    /// directory interrupted before initialization requires inspection, not reset.
    pub fn open(directory: &Path, authority: &str, endpoint: &str) -> Result<Self> {
        let endpoint = catalog(authority, endpoint)?;
        let fresh = match fs::DirBuilder::new().mode(0o700).create(directory) {
            Ok(()) => true,
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => false,
            Err(e) => return Err(error(e)),
        };
        let metadata = fs::symlink_metadata(directory).map_err(error)?;
        if !metadata.is_dir()
            || metadata.file_type().is_symlink()
            || metadata.uid() != geteuid().as_raw()
            || metadata.mode() & 0o077 != 0
        {
            return Err("unsafe_workspace_directory".into());
        }
        // Create before SQLite so error paths also close the database first.
        let lease = WorkspaceLease::acquire(&directory.join("workspace.lock"))?;
        let path = directory.join("notes.sqlite");
        if !fresh && !path.exists() {
            return Err("workspace_storage_missing".into());
        }
        // Never let SQLite follow substituted journal/WAL sidecars.
        for name in [
            "notes.sqlite-journal",
            "notes.sqlite-wal",
            "notes.sqlite-shm",
        ] {
            if fs::symlink_metadata(directory.join(name)).is_ok() {
                private_file(&directory.join(name))?;
            }
        }
        let file = private_file(&path)?;
        let mut db = Connection::open(&path).map_err(error)?;
        db.busy_timeout(std::time::Duration::from_millis(250))
            .map_err(error)?;
        let app: i32 = db
            .query_row("PRAGMA application_id", [], |r| r.get(0))
            .map_err(error)?;
        let version: i32 = db
            .query_row("PRAGMA user_version", [], |r| r.get(0))
            .map_err(error)?;
        if (!fresh && (app != APP_ID || version != 1)) || (fresh && (app != 0 || version != 0)) {
            return Err("incompatible_workspace_storage".into());
        }
        db.execute_batch("PRAGMA synchronous=FULL; PRAGMA journal_mode=DELETE;")
            .map_err(error)?;
        if fresh {
            let tx = db
                .transaction_with_behavior(TransactionBehavior::Immediate)
                .map_err(error)?;
            tx.execute_batch("CREATE TABLE deployment(authority TEXT NOT NULL, endpoint TEXT NOT NULL, catalog TEXT NOT NULL);
                CREATE TABLE notes(sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, principal TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL);
                CREATE INDEX notes_owner ON notes(principal, sequence);
                CREATE TABLE receipts(operation_id TEXT PRIMARY KEY, principal TEXT NOT NULL, request_id TEXT NOT NULL, request_hash TEXT NOT NULL, receipt TEXT NOT NULL, UNIQUE(principal,request_id));").map_err(error)?;
            tx.execute(
                "INSERT INTO deployment VALUES (?1,?2,?3)",
                params![
                    authority,
                    endpoint.binding.endpoint_id,
                    endpoint.binding.catalog_sha256
                ],
            )
            .map_err(error)?;
            tx.pragma_update(None, "application_id", APP_ID)
                .map_err(error)?;
            tx.pragma_update(None, "user_version", 1).map_err(error)?;
            tx.commit().map_err(error)?;
            file.sync_all().map_err(error)?;
            File::open(directory)
                .map_err(error)?
                .sync_all()
                .map_err(error)?;
        }
        let binding: (String, String, String) = db
            .query_row(
                "SELECT authority,endpoint,catalog FROM deployment",
                [],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
            )
            .map_err(error)?;
        if binding
            != (
                authority.into(),
                endpoint.binding.endpoint_id.clone(),
                endpoint.binding.catalog_sha256.clone(),
            )
        {
            return Err("workspace_deployment_mismatch".into());
        }
        Ok(Self {
            db,
            _lease: lease,
            endpoint,
        })
    }
    fn prepare(
        &mut self,
        principal: &str,
        operation_id: &str,
        request: &Request,
        deadline: Instant,
    ) -> Result<Action> {
        check_deadline(deadline)?;
        identifier(principal)?;
        identifier(operation_id)?;
        request.validate()?;
        if request.target != self.endpoint.binding {
            return Err("workspace_target_mismatch".into());
        }
        let action = self
            .endpoint
            .actions
            .iter()
            .find(|a| a.action == request.action)
            .ok_or("unsupported_action")?
            .clone();
        validate_fields(&request.parameters, &action.parameters)?;
        self.db
            .busy_timeout(deadline.saturating_duration_since(Instant::now()))
            .map_err(error)?;
        Ok(action)
    }
}

fn load(
    db: &Connection,
    principal: &str,
    operation_id: &str,
    request: &Request,
    action: &Action,
) -> Result<Option<Receipt>> {
    let row: Option<(String, String, String)> = db
        .query_row(
            "SELECT principal,request_hash,receipt FROM receipts WHERE operation_id=?1",
            [operation_id],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .optional()
        .map_err(error)?;
    row.map(|(owner, hash, payload)| {
        if owner != principal || hash != digest(request)? {
            return Err("operation_identity_conflict".into());
        }
        let receipt: Receipt = parse_json(payload.as_bytes())?;
        receipt.validate(action)?;
        Ok(receipt)
    })
    .transpose()
}
fn get_string<'a>(request: &'a Request, name: &str) -> Result<&'a str> {
    match request.parameters.get(name) {
        Some(Parameter::String { value } | Parameter::Resource { value }) => Ok(value),
        _ => Err("invalid_parameter".into()),
    }
}
fn perform(tx: &Transaction<'_>, principal: &str, request: &Request) -> Result<Receipt> {
    let output = match request.action.as_str() {
        "notes.create" => {
            let id = format!("note-{}", Uuid::new_v4());
            tx.execute(
                "INSERT INTO notes(id,principal,title,body) VALUES (?1,?2,?3,?4)",
                params![
                    id,
                    principal,
                    get_string(request, "title")?,
                    get_string(request, "body")?
                ],
            )
            .map_err(error)?;
            Output::Scalar {
                value: Parameter::Resource { value: id },
            }
        }
        "notes.read" => {
            let id = get_string(request, "note_id")?;
            let row: Option<(String, String)> = tx
                .query_row(
                    "SELECT title,body FROM notes WHERE id=?1 AND principal=?2",
                    params![id, principal],
                    |r| Ok((r.get(0)?, r.get(1)?)),
                )
                .optional()
                .map_err(error)?;
            let Some((title, body)) = row else {
                return Ok(Receipt::Failed {
                    reason: "note_not_found".into(),
                });
            };
            Output::Record {
                fields: [
                    ("note_id".into(), Parameter::Resource { value: id.into() }),
                    ("title".into(), text(&title)),
                    ("body".into(), text(&body)),
                ]
                .into(),
            }
        }
        "notes.list" => {
            let after = get_string(request, "after")?;
            let sequence: i64 = if after.is_empty() {
                0
            } else {
                identifier(after)?;
                let found = tx
                    .query_row(
                        "SELECT sequence FROM notes WHERE id=?1 AND principal=?2",
                        params![after, principal],
                        |r| r.get(0),
                    )
                    .optional()
                    .map_err(error)?;
                let Some(sequence) = found else {
                    return Ok(Receipt::Failed {
                        reason: "invalid_cursor".into(),
                    });
                };
                sequence
            };
            let Some(Parameter::Integer { value: limit }) = request.parameters.get("limit") else {
                return Err("invalid_limit".into());
            };
            let mut statement = tx.prepare("SELECT id,title FROM notes WHERE principal=?1 AND sequence>?2 ORDER BY sequence LIMIT ?3").map_err(error)?;
            let rows: Vec<(String, String)> = statement
                .query_map(params![principal, sequence, limit + 1], |r| {
                    Ok((r.get(0)?, r.get(1)?))
                })
                .map_err(error)?
                .collect::<std::result::Result<_, _>>()
                .map_err(error)?;
            let total = rows.len();
            let mut items = Vec::new();
            let mut last_id = None;
            // Escaped titles can be six times their UTF-8 size. Return a smaller
            // page, never skip records or fail a valid list solely due to escaping.
            for (id, title) in rows.into_iter().take(*limit as usize) {
                let item = [
                    ("note_id".into(), Parameter::Resource { value: id.clone() }),
                    ("title".into(), text(&title)),
                ]
                .into();
                items.push(item);
                let candidate = Output::Page {
                    items: items.clone(),
                    next_cursor: Some(id.clone()),
                };
                if edge_contracts::canonical_bytes(&candidate)?.len() > 32_000 {
                    items.pop();
                    break;
                }
                last_id = Some(id);
            }
            let next_cursor = if total > items.len() { last_id } else { None };
            Output::Page { items, next_cursor }
        }
        _ => return Err("unsupported_action".into()),
    };
    Ok(Receipt::Succeeded {
        output,
        evidence: Evidence::DurableReceipt,
    })
}
impl Adapter for Workspace {
    fn describe(&self) -> Result<Endpoint> {
        Ok(self.endpoint.clone())
    }
    fn invoke(
        &mut self,
        principal: &str,
        operation_id: &str,
        request: &Request,
        deadline: Instant,
    ) -> Result<Receipt> {
        let deadline = deadline.min(
            Instant::now() + std::time::Duration::from_millis(request.budget_ms.min(2000).into()),
        );
        let action = self.prepare(principal, operation_id, request, deadline)?;
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(error)?;
        check_deadline(deadline)?;
        if let Some(receipt) = load(&tx, principal, operation_id, request, &action)? {
            return Ok(receipt);
        }
        let existing: bool = tx
            .query_row(
                "SELECT EXISTS(SELECT 1 FROM receipts WHERE principal=?1 AND request_id=?2)",
                params![principal, request.request_id],
                |r| r.get(0),
            )
            .map_err(error)?;
        if existing {
            return Err("request_operation_identity_conflict".into());
        }
        let count: i64 = tx
            .query_row("SELECT count(*) FROM receipts", [], |r| r.get(0))
            .map_err(error)?;
        if count >= MAX_RECEIPTS {
            return Err("workspace_capacity".into());
        }
        let receipt = perform(&tx, principal, request)?;
        receipt.validate(&action)?;
        tx.execute(
            "INSERT INTO receipts VALUES (?1,?2,?3,?4,?5)",
            params![
                operation_id,
                principal,
                request.request_id,
                digest(request)?,
                serde_json::to_string(&receipt).map_err(error)?
            ],
        )
        .map_err(error)?;
        check_deadline(deadline)?;
        tx.commit().map_err(error)?;
        Ok(receipt)
    }
    fn reconcile(
        &mut self,
        principal: &str,
        operation_id: &str,
        request: &Request,
        deadline: Instant,
    ) -> Result<Receipt> {
        let deadline = deadline.min(
            Instant::now() + std::time::Duration::from_millis(request.budget_ms.min(2000).into()),
        );
        let action = self.prepare(principal, operation_id, request, deadline)?;
        let receipt = load(&self.db, principal, operation_id, request, &action)?.unwrap_or(
            Receipt::Unknown {
                reason: "receipt_not_found".into(),
            },
        );
        check_deadline(deadline)?;
        Ok(receipt)
    }
}

#[cfg(test)]
mod lease_tests {
    use super::*;

    #[test]
    fn owner_teardown_releases_lease_with_live_handle_alias() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("notes");
        let store = Workspace::open(&path, "host", "notes").unwrap();
        let alias = store._lease.file.try_clone().unwrap();
        assert_eq!(
            Workspace::open(&path, "host", "notes").err().unwrap(),
            "workspace_already_owned"
        );
        drop(store);
        let reopened = Workspace::open(&path, "host", "notes")
            .expect("an incidental handle must not retain ownership after teardown");
        assert_eq!(
            Workspace::open(&path, "host", "notes").err().unwrap(),
            "workspace_already_owned"
        );
        drop(alias);
        drop(reopened);
    }

    #[test]
    fn initialization_error_releases_acquired_lease_with_live_alias() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("workspace.lock");
        let mut alias = None;
        let result: Result<()> = (|| {
            let lease = WorkspaceLease::acquire(&path)?;
            alias = Some(lease.file.try_clone().unwrap());
            // Exercise unwinding through an early Result error, without a
            // production fault flag or altering the error returned to callers.
            Err("injected_initialization_failure".into())
        })();
        assert_eq!(result.unwrap_err(), "injected_initialization_failure");
        let reopened = WorkspaceLease::acquire(&path).unwrap();
        assert!(WorkspaceLease::acquire(&path).is_err());
        drop(alias);
        drop(reopened);
    }

    #[test]
    fn foreign_process_guard_does_not_release_original_owner() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("workspace.lock");
        let lease = WorkspaceLease::acquire(&path).unwrap();
        // Exercise the PID fence with a real descriptor alias, without unsafe
        // fork in the multithreaded Rust test harness. Zero is not a userspace PID.
        let inherited = WorkspaceLease {
            file: lease.file.try_clone().unwrap(),
            owner_process: 0,
        };
        drop(inherited);
        assert!(WorkspaceLease::acquire(&path).is_err());
        drop(lease);
        assert!(WorkspaceLease::acquire(&path).is_ok());
    }
}
