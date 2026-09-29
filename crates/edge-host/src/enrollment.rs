//! Private persistent enrollment for the local software service. No Debug for secrets.
use edge_protocol::{
    execution::{Credential, Scope},
    local::private_file,
};
use serde::{Deserialize, Serialize};
use std::{
    fs::{self, File, OpenOptions},
    io::{self, Write},
    os::unix::fs::OpenOptionsExt,
    path::Path,
};
use uuid::Uuid;

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Entry {
    pub credential: Credential,
    pub scope: Scope,
    pub revoked: bool,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Registry {
    schema_version: String,
    pub owner: Credential,
    pub peers: Vec<Entry>,
}

pub(crate) fn credential(authority: &str, principal: &str) -> Credential {
    Credential {
        schema_version: "edge-execution-credential.v1".into(),
        authority_id: authority.into(),
        principal: principal.into(),
        token: format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple()),
    }
}
impl Registry {
    pub fn new(authority: &str) -> Self {
        Self {
            schema_version: "edge-execution-enrollment.v1".into(),
            owner: credential(authority, "owner"),
            peers: Vec::new(),
        }
    }
    pub fn load(path: &Path, authority: &str) -> io::Result<Self> {
        let meta = edge_protocol::local::private_metadata(path)?;
        if !meta.is_file() || meta.len() > 32768 {
            return Err(io::Error::other("invalid enrollment file"));
        }
        use std::{io::Read, os::unix::fs::MetadataExt};
        if meta.nlink() != 1 {
            return Err(io::Error::other("invalid enrollment link"));
        }
        let file = File::open(path)?;
        let after = file.metadata()?;
        if (meta.dev(), meta.ino()) != (after.dev(), after.ino()) {
            return Err(io::Error::other("enrollment changed"));
        }
        let mut bytes = Vec::new();
        file.take(32769).read_to_end(&mut bytes)?;
        if bytes.len() > 32768 {
            return Err(io::Error::other("enrollment too large"));
        }
        let registry: Self = edge_contracts::parse_json(&bytes).map_err(io::Error::other)?;
        registry.owner.validate().map_err(io::Error::other)?;
        if registry.schema_version != "edge-execution-enrollment.v1"
            || registry.owner.authority_id != authority
            || registry.owner.principal != "owner"
            || registry.peers.len() > 64
        {
            return Err(io::Error::other("enrollment identity/version mismatch"));
        }
        let mut names = std::collections::BTreeSet::from([registry.owner.principal.clone()]);
        let mut tokens = std::collections::BTreeSet::from([registry.owner.token.clone()]);
        for peer in &registry.peers {
            peer.credential.validate().map_err(io::Error::other)?;
            if peer.credential.authority_id != authority
                || !names.insert(peer.credential.principal.clone())
                || !tokens.insert(peer.credential.token.clone())
            {
                return Err(io::Error::other("invalid enrollment binding"));
            }
        }
        Ok(registry)
    }
    pub fn save(&self, directory: &Path) -> io::Result<()> {
        save(directory, "enrollment.json", self)
    }
    pub fn ensure_owner_file(&self, directory: &Path) -> io::Result<()> {
        let path = directory.join("owner.json");
        if path.symlink_metadata().is_ok() {
            let stored: Credential =
                edge_contracts::parse_json(&private_file(&path)?).map_err(io::Error::other)?;
            if serde_json::to_vec(&stored)? != serde_json::to_vec(&self.owner)? {
                return Err(io::Error::other(
                    "owner credential mismatch; refusing overwrite",
                ));
            }
            Ok(())
        } else {
            save(directory, "owner.json", &self.owner)
        }
    }
}
fn save(directory: &Path, name: &str, value: &impl Serialize) -> io::Result<()> {
    let target = directory.join(name);
    if target.symlink_metadata().is_ok() {
        let meta = edge_protocol::local::private_metadata(&target)?;
        use std::os::unix::fs::MetadataExt;
        if !meta.is_file() || meta.nlink() != 1 {
            return Err(io::Error::other("unsafe enrollment target"));
        }
    }
    let temporary = directory.join(format!("enrollment-{}.tmp", Uuid::new_v4()));
    let result = (|| {
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&temporary)?;
        serde_json::to_writer(&mut file, value)?;
        file.flush()?;
        file.sync_all()?;
        fs::rename(&temporary, &target)?;
        File::open(directory)?.sync_all()
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result
}
