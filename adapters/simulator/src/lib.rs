//! SQLite-backed software volume device. No native audio or hardware calls.
use edge_contracts::{
    ControlRequest, Evidence, Parameter, RequestInput, Result, TargetBinding, digest, parse_json,
};
use edge_core::{
    ActionDefinition, Effect, Endpoint, ParameterRule, PlanStep, PreviewContext, PreviewPolicy,
    execution::{Adapter, Receipt, check_deadline},
};
use fs2::FileExt;
use rusqlite::{Connection, OptionalExtension, TransactionBehavior, params};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs::{File, OpenOptions},
    path::Path,
    time::{Duration, Instant},
};
use uuid::Uuid;

#[derive(Debug, Clone, Copy, Default)]
pub enum Fault {
    #[default]
    None,
    RejectBeforeEffect,
    LostAcknowledgement,
    EffectWithoutReceipt,
    MalformedReceipt,
    Delay(Duration),
}

pub struct Simulator {
    connection: Connection,
    _lease: File,
    authority: String,
    pub fault: Fault,
    pub invoke_calls: u64,
}

fn err(error: impl ToString) -> String {
    error.to_string()
}

impl Simulator {
    pub fn open(path: &Path) -> Result<Self> {
        if path
            .symlink_metadata()
            .is_ok_and(|m| m.file_type().is_symlink())
        {
            return Err("simulator_symlink_forbidden".into());
        }
        let mut options = OpenOptions::new();
        options.read(true).write(true).create(true).truncate(false);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        // Lock a sidecar, not the SQLite file: mandatory Windows file locks would
        // otherwise conflict with SQLite's separate database handle.
        let lock_path = path.with_extension("lock");
        if lock_path
            .symlink_metadata()
            .is_ok_and(|m| m.file_type().is_symlink())
        {
            return Err("simulator_lock_symlink_forbidden".into());
        }
        let lease = options.open(lock_path).map_err(err)?;
        lease
            .try_lock_exclusive()
            .map_err(|_| "simulator_already_owned".to_string())?;
        drop(options.open(path).map_err(err)?);
        let mut connection = Connection::open(path).map_err(err)?;
        connection
            .busy_timeout(Duration::from_millis(250))
            .map_err(err)?;
        let version: i32 = connection
            .query_row("PRAGMA user_version", [], |r| r.get(0))
            .map_err(err)?;
        let app_id: i32 = connection
            .query_row("PRAGMA application_id", [], |r| r.get(0))
            .map_err(err)?;
        let tables: i64 = connection
            .query_row(
                "SELECT count(*) FROM sqlite_master WHERE type='table'",
                [],
                |r| r.get(0),
            )
            .map_err(err)?;
        const APP: i32 = 0x45445332;
        if !((version == 0 && app_id == 0 && tables == 0) || (version == 1 && app_id == APP)) {
            return Err("not_a_simulator_database".into());
        }
        connection
            .execute_batch("PRAGMA synchronous=FULL; PRAGMA journal_mode=DELETE;")
            .map_err(err)?;
        let tx = connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(err)?;
        if version == 0 {
            tx.execute_batch("CREATE TABLE state(authority TEXT NOT NULL, volume INTEGER NOT NULL,
                generation INTEGER NOT NULL, writes INTEGER NOT NULL);
                CREATE TABLE receipts(operation_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, receipt TEXT);").map_err(err)?;
            tx.execute(
                "INSERT INTO state VALUES (?1,20,1,0)",
                [format!("simulator-{}", Uuid::new_v4())],
            )
            .map_err(err)?;
            tx.pragma_update(None, "application_id", APP).map_err(err)?;
            tx.pragma_update(None, "user_version", 1).map_err(err)?;
        }
        let authority = tx
            .query_row("SELECT authority FROM state", [], |r| r.get(0))
            .map_err(err)?;
        tx.commit().map_err(err)?;
        Ok(Self {
            connection,
            _lease: lease,
            authority,
            fault: Fault::None,
            invoke_calls: 0,
        })
    }

    pub fn authority_id(&self) -> &str {
        &self.authority
    }
    pub fn volume(&self) -> Result<i64> {
        self.connection
            .query_row("SELECT volume FROM state", [], |r| r.get(0))
            .map_err(err)
    }
    pub fn writes(&self) -> Result<i64> {
        self.connection
            .query_row("SELECT writes FROM state", [], |r| r.get(0))
            .map_err(err)
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

    pub fn request(
        &mut self,
        request_id: &str,
        percent: i64,
        deadline: Instant,
    ) -> Result<ControlRequest> {
        let target = self.observe(deadline)?.endpoints.remove(0).binding;
        let request = ControlRequest {
            schema_version: "edge-control-request.v2".into(),
            request_id: request_id.into(),
            authority_id: self.authority.clone(),
            budget_ms: 2000,
            input: RequestInput::Action {
                target,
                action: "audio.volume.set".into(),
                parameters: BTreeMap::from([(
                    "percent".into(),
                    Parameter::Integer { value: percent },
                )]),
            },
        };
        request.validate()?;
        Ok(request)
    }
}

impl Adapter for Simulator {
    fn observe(&mut self, deadline: Instant) -> Result<PreviewContext> {
        self.budget(deadline)?;
        let generation = self
            .connection
            .query_row("SELECT generation FROM state", [], |r| r.get(0))
            .map_err(err)?;
        let actions = vec![
            ActionDefinition {
                action: "audio.volume.get".into(),
                effect: Effect::Read,
                parameters: BTreeMap::new(),
                max_duration_ms: 1000,
                expected_evidence: Evidence::DurableReceipt,
            },
            ActionDefinition {
                action: "audio.volume.set".into(),
                effect: Effect::Write,
                parameters: BTreeMap::from([(
                    "percent".into(),
                    ParameterRule::Integer {
                        minimum: 0,
                        maximum: 100,
                    },
                )]),
                max_duration_ms: 1000,
                expected_evidence: Evidence::DurableReceipt,
            },
        ];
        check_deadline(deadline)?;
        Ok(PreviewContext {
            schema_version: "edge-preview-context.v1".into(),
            authority_id: self.authority.clone(),
            policy: PreviewPolicy {
                version: "simulator-policy.v1".into(),
                allowed_endpoints: BTreeSet::from(["output".into()]),
                allowed_actions: actions.iter().map(|a| a.action.clone()).collect(),
            },
            endpoints: vec![Endpoint {
                binding: TargetBinding {
                    authority_id: self.authority.clone(),
                    endpoint_id: "output".into(),
                    registration_generation: 1,
                    observation_generation: generation,
                    catalog_sha256: digest(&actions)?,
                },
                actions,
            }],
        })
    }

    fn invoke(
        &mut self,
        operation_id: &str,
        step: &PlanStep,
        deadline: Instant,
    ) -> Result<Receipt> {
        self.invoke_calls += 1;
        self.budget(deadline)?;
        let fingerprint = digest(step)?;
        let tx = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(err)?;
        let existing: Option<(String, Option<String>)> = tx
            .query_row(
                "SELECT fingerprint,receipt FROM receipts WHERE operation_id=?1",
                [operation_id],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()
            .map_err(err)?;
        if let Some((previous, receipt)) = existing {
            if previous != fingerprint {
                return Err("device_operation_identity_conflict".into());
            }
            return receipt
                .map(|text| parse_json(text.as_bytes()))
                .unwrap_or(Ok(Receipt::Unknown {
                    reason: "device_intent_without_receipt".into(),
                }));
        }
        tx.execute(
            "INSERT INTO receipts VALUES (?1,?2,NULL)",
            params![operation_id, fingerprint],
        )
        .map_err(err)?;
        check_deadline(deadline)?;
        tx.commit().map_err(err)?;
        if let Fault::Delay(delay) = self.fault {
            std::thread::sleep(delay.min(deadline.saturating_duration_since(Instant::now())));
        }
        self.budget(deadline)?;
        let current = self.observe(deadline)?;
        if step.target != current.endpoints[0].binding {
            return Ok(Receipt::Unknown {
                reason: "device_target_changed".into(),
            });
        }
        let tx = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(err)?;
        let receipt = if matches!(self.fault, Fault::RejectBeforeEffect) {
            Receipt::Failed {
                reason: "simulated_device_rejection".into(),
            }
        } else {
            let value = match step.action.as_str() {
                "audio.volume.get" if step.parameters.is_empty() => tx
                    .query_row("SELECT volume FROM state", [], |r| r.get(0))
                    .map_err(err)?,
                "audio.volume.set" if step.parameters.len() == 1 => {
                    let Some(Parameter::Integer { value }) = step.parameters.get("percent") else {
                        return Err("invalid_device_parameter".into());
                    };
                    if !(0..=100).contains(value) {
                        return Err("device_value_out_of_range".into());
                    }
                    check_deadline(deadline)?;
                    tx.execute(
                        "UPDATE state SET volume=?1, generation=generation+1, writes=writes+1",
                        [value],
                    )
                    .map_err(err)?;
                    *value
                }
                _ => return Err("unsupported_device_action".into()),
            };
            Receipt::Succeeded {
                value: Parameter::Integer { value },
                evidence: Evidence::DurableReceipt,
            }
        };
        if !matches!(self.fault, Fault::EffectWithoutReceipt) {
            tx.execute(
                "UPDATE receipts SET receipt=?1 WHERE operation_id=?2",
                params![serde_json::to_string(&receipt).map_err(err)?, operation_id],
            )
            .map_err(err)?;
        }
        check_deadline(deadline)?;
        tx.commit().map_err(err)?;
        if matches!(
            self.fault,
            Fault::LostAcknowledgement | Fault::EffectWithoutReceipt
        ) {
            return Err("simulated_disconnect_after_effect".into());
        }
        check_deadline(deadline)?;
        if matches!(self.fault, Fault::MalformedReceipt) {
            return Ok(Receipt::Succeeded {
                value: Parameter::String {
                    value: "invalid\0value".into(),
                },
                evidence: Evidence::DurableReceipt,
            });
        }
        Ok(receipt)
    }

    fn reconcile(&mut self, operation_id: &str, deadline: Instant) -> Result<Receipt> {
        self.budget(deadline)?;
        let text: Option<Option<String>> = self
            .connection
            .query_row(
                "SELECT receipt FROM receipts WHERE operation_id=?1",
                [operation_id],
                |r| r.get(0),
            )
            .optional()
            .map_err(err)?;
        check_deadline(deadline)?;
        text.flatten()
            .map(|text| parse_json(text.as_bytes()))
            .unwrap_or(Ok(Receipt::Unknown {
                reason: "no_confirmed_device_receipt".into(),
            }))
    }
}
