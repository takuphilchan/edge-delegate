//! Immutable, client-owned notes. Installed trusted adapter, NOT a permission service.
//! Linux persistence only until Windows private-file/ACL support is implemented.
#[cfg(target_os = "linux")]
use edge_contracts::Parameter;
use edge_contracts::actions::{Action, Endpoint, FieldRule, OutputRule, Shape};
use edge_contracts::preview::{Effect, ParameterRule};
use edge_contracts::{Evidence, Result, TargetBinding, digest};

#[cfg(target_os = "linux")]
mod store;
#[cfg(target_os = "linux")]
pub use store::Workspace;

fn string(max_bytes: usize) -> FieldRule {
    FieldRule::Scalar {
        rule: ParameterRule::String { max_bytes },
    }
}
fn note_fields() -> Shape {
    [
        ("note_id".into(), FieldRule::ResourceReference {}),
        ("title".into(), string(256)),
        ("body".into(), string(4096)),
    ]
    .into()
}
/// Data-only catalog, with no owner permissions or client identities embedded.
pub fn catalog(authority: &str, endpoint: &str) -> Result<Endpoint> {
    let mut summary = note_fields();
    summary.remove("body");
    let actions = vec![
        Action {
            action: "notes.create".into(),
            effect: Effect::Write,
            parameters: [("title".into(), string(256)), ("body".into(), string(4096))].into(),
            output: OutputRule::Scalar {
                rule: FieldRule::ResourceReference {},
            },
            max_duration_ms: 2000,
            expected_evidence: Evidence::DurableReceipt,
            allows_handoff: false,
        },
        Action {
            action: "notes.read".into(),
            effect: Effect::Read,
            parameters: [("note_id".into(), FieldRule::ResourceReference {})].into(),
            output: OutputRule::Record {
                fields: note_fields(),
            },
            max_duration_ms: 2000,
            expected_evidence: Evidence::DurableReceipt,
            allows_handoff: false,
        },
        Action {
            action: "notes.list".into(),
            effect: Effect::Read,
            parameters: [
                ("after".into(), string(128)),
                (
                    "limit".into(),
                    FieldRule::Scalar {
                        rule: ParameterRule::Integer {
                            minimum: 1,
                            maximum: 20,
                        },
                    },
                ),
            ]
            .into(),
            output: OutputRule::Page {
                fields: summary,
                max_items: 20,
            },
            max_duration_ms: 2000,
            expected_evidence: Evidence::DurableReceipt,
            allows_handoff: false,
        },
    ];
    let endpoint = Endpoint {
        binding: TargetBinding {
            authority_id: authority.into(),
            endpoint_id: endpoint.into(),
            registration_generation: 1,
            observation_generation: 0,
            catalog_sha256: digest(&actions)?,
        },
        actions,
    };
    endpoint.validate()?;
    Ok(endpoint)
}
#[cfg(target_os = "linux")]
fn text(value: &str) -> Parameter {
    Parameter::String {
        value: value.into(),
    }
}
