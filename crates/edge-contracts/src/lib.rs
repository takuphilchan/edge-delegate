//! Data-only cross-platform contracts. Parsing is bounded and rejects duplicate keys.
//! A validated request or preview is never an authorization to dispatch.

pub mod admission;
pub mod operation;
pub mod preview;
mod strict_json;

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;

pub use strict_json::parse_json;
pub const MAX_FRAME_BYTES: usize = 65_536;
pub const MAX_TEXT_BYTES: usize = 4_096;
pub const MAX_SAFE_INTEGER: i64 = 9_007_199_254_740_991;

pub type Result<T> = std::result::Result<T, String>;

pub fn identifier(value: &str) -> Result<()> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"._:-".contains(&b))
    {
        return Err(
            "identifier must contain 1..128 ASCII letters, digits, '.', '_', ':', or '-'".into(),
        );
    }
    Ok(())
}

pub fn fingerprint(value: &str) -> Result<()> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err("fingerprint must be 64 lowercase hexadecimal characters".into());
    }
    Ok(())
}

/// Exact decimal wire form: no exponent, plus sign, leading/trailing zero, or negative zero.
pub fn decimal(value: &str) -> Result<()> {
    let body = value.strip_prefix('-').unwrap_or(value);
    let (whole, fraction) = body
        .split_once('.')
        .map_or((body, None), |(a, b)| (a, Some(b)));
    if value.len() > 32
        || whole.is_empty()
        || !whole.bytes().all(|b| b.is_ascii_digit())
        || (whole.len() > 1 && whole.starts_with('0'))
        || value == "-0"
        || fraction.is_some_and(|part| {
            part.is_empty() || part.ends_with('0') || !part.bytes().all(|b| b.is_ascii_digit())
        })
    {
        return Err("noncanonical decimal parameter".into());
    }
    Ok(())
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "type", deny_unknown_fields)]
pub enum Parameter {
    #[serde(rename = "boolean")]
    Boolean { value: bool },
    #[serde(rename = "integer")]
    Integer { value: i64 },
    #[serde(rename = "string")]
    String { value: String },
    #[serde(rename = "enum")]
    Enum { value: String },
    #[serde(rename = "resource")]
    Resource { value: String },
    #[serde(rename = "decimal")]
    Decimal { value: String, unit: String },
}

impl Parameter {
    pub fn validate(&self) -> Result<()> {
        match self {
            Self::Boolean { .. } => Ok(()),
            Self::Integer { value } if (-MAX_SAFE_INTEGER..=MAX_SAFE_INTEGER).contains(value) => {
                Ok(())
            }
            Self::Integer { .. } => Err("integer exceeds cross-language safe range".into()),
            Self::String { value } if value.len() <= MAX_TEXT_BYTES && !value.contains('\0') => {
                Ok(())
            }
            Self::String { .. } => Err("string exceeds limit or contains NUL".into()),
            Self::Enum { value } | Self::Resource { value } => identifier(value),
            Self::Decimal { value, unit } => {
                decimal(value)?;
                identifier(unit)
            }
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TargetBinding {
    pub authority_id: String,
    pub endpoint_id: String,
    pub registration_generation: u32,
    pub observation_generation: u32,
    pub catalog_sha256: String,
}

impl TargetBinding {
    pub fn validate(&self) -> Result<()> {
        identifier(&self.authority_id)?;
        identifier(&self.endpoint_id)?;
        fingerprint(&self.catalog_sha256)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", deny_unknown_fields)]
pub enum RequestInput {
    #[serde(rename = "action")]
    Action {
        target: TargetBinding,
        action: String,
        parameters: BTreeMap<String, Parameter>,
    },
    #[serde(rename = "text")]
    Text { text: String },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ControlRequest {
    pub schema_version: String,
    pub request_id: String,
    pub authority_id: String,
    pub budget_ms: u32,
    pub input: RequestInput,
}

impl ControlRequest {
    pub fn parse(bytes: &[u8]) -> Result<Self> {
        let request: Self = parse_json(bytes)?;
        request.validate()?;
        Ok(request)
    }

    pub fn validate(&self) -> Result<()> {
        if self.schema_version != "edge-control-request.v2" {
            return Err("unsupported control request version".into());
        }
        identifier(&self.request_id)?;
        identifier(&self.authority_id)?;
        if !(1..=5_000).contains(&self.budget_ms) {
            return Err("immediate request budget must be 1..5000 ms".into());
        }
        match &self.input {
            RequestInput::Text { text } => {
                if text.trim().is_empty() || text.len() > MAX_TEXT_BYTES || text.contains('\0') {
                    return Err(
                        "text must be nonempty, NUL-free and at most 4096 UTF-8 bytes".into(),
                    );
                }
            }
            RequestInput::Action {
                target,
                action,
                parameters,
            } => {
                target.validate()?;
                if target.authority_id != self.authority_id {
                    return Err("target authority differs from request".into());
                }
                identifier(action)?;
                if parameters.len() > 16 {
                    return Err("too many parameters".into());
                }
                for (name, parameter) in parameters {
                    identifier(name)?;
                    parameter.validate()?;
                }
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Outcome {
    Rejected,
    ClarificationRequired,
    AwaitingApproval,
    Queued,
    Running,
    Succeeded,
    Failed,
    CancelledBeforeDispatch,
    ExpiredBeforeDispatch,
    HandedOff,
    Unknown,
    PartiallyCompleted,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Evidence {
    ApiAcknowledgement,
    DurableReceipt,
    StateReadback,
    IndependentObservation,
}

/// edge-canonical-json.v1: UTF-8, lexicographically sorted ASCII object keys,
/// compact JSON, no floats, and only JS-safe integers. Not general RFC 8785.
/// Exact decimals travel as tagged strings. Used only on validated typed data.
pub fn canonical_bytes<T: Serialize>(value: &T) -> Result<Vec<u8>> {
    fn check(value: &serde_json::Value) -> Result<()> {
        match value {
            serde_json::Value::Number(n) => {
                if !n
                    .as_i64()
                    .is_some_and(|n| (-MAX_SAFE_INTEGER..=MAX_SAFE_INTEGER).contains(&n))
                {
                    return Err("canonical JSON forbids floats and unsafe integers".into());
                }
            }
            serde_json::Value::Object(map) => {
                for (key, value) in map {
                    if !key.is_ascii() {
                        return Err("canonical object keys must be ASCII".into());
                    }
                    check(value)?;
                }
            }
            serde_json::Value::Array(values) => {
                for value in values {
                    check(value)?;
                }
            }
            _ => (),
        }
        Ok(())
    }
    let value = serde_json::to_value(value).map_err(|e| e.to_string())?;
    check(&value)?;
    // Sort explicitly: another workspace crate may enable serde_json/preserve_order.
    // Cargo feature unification must never change a plan fingerprint.
    fn emit(value: &serde_json::Value, output: &mut Vec<u8>) -> Result<()> {
        match value {
            serde_json::Value::Object(map) => {
                output.push(b'{');
                let sorted: BTreeMap<_, _> = map.iter().collect();
                for (index, (key, value)) in sorted.into_iter().enumerate() {
                    if index != 0 {
                        output.push(b',');
                    }
                    serde_json::to_writer(&mut *output, key).map_err(|e| e.to_string())?;
                    output.push(b':');
                    emit(value, output)?;
                }
                output.push(b'}');
            }
            serde_json::Value::Array(values) => {
                output.push(b'[');
                for (index, value) in values.iter().enumerate() {
                    if index != 0 {
                        output.push(b',');
                    }
                    emit(value, output)?;
                }
                output.push(b']');
            }
            _ => serde_json::to_writer(output, value).map_err(|e| e.to_string())?,
        }
        Ok(())
    }
    let mut output = Vec::new();
    emit(&value, &mut output)?;
    Ok(output)
}

pub fn digest<T: Serialize>(value: &T) -> Result<String> {
    Ok(format!("{:x}", Sha256::digest(canonical_bytes(value)?)))
}
