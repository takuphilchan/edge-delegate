//! Durable acceptance is separate from proof of execution or physical completion.
use crate::{ControlRequest, preview::Plan};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AdmissionState {
    Accepted,
    Finished,
    CancelledBeforeDispatch,
    ExpiredBeforeDispatch,
    Interrupted,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Admission {
    pub schema_version: String,
    pub principal: String,
    pub request: ControlRequest,
    pub plan: Plan,
    pub session: String,
    pub state: AdmissionState,
    pub cancellation_requested: bool,
}
