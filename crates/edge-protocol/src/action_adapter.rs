//! Private host/installed-worker channel, never a client dispatch interface.
use edge_contracts::actions::{Endpoint, Receipt, Request};
use serde::{Deserialize, Serialize};
pub const VERSION: &str = "edge-action-adapter.v1";
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Message {
    pub schema_version: String,
    pub sequence: u64,
    pub command: Command,
}
#[derive(Serialize, Deserialize)]
#[serde(tag = "method", rename_all = "snake_case", deny_unknown_fields)]
pub enum Command {
    Describe {},
    Invoke {
        principal: String,
        operation_id: String,
        request: Request,
        budget_ms: u32,
    },
    Reconcile {
        principal: String,
        operation_id: String,
        request: Request,
        budget_ms: u32,
    },
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Response {
    pub schema_version: String,
    pub sequence: u64,
    pub reply: Reply,
}
#[derive(Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Reply {
    Description { endpoint: Endpoint },
    Receipt { receipt: Receipt },
    Unavailable {},
}
