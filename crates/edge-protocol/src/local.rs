//! Linux transport primitives, not a sandbox against applications of the same user.
use nix::{
    sys::socket::{getsockopt, sockopt::PeerCredentials},
    unistd::geteuid,
};
use std::{
    fs::{self, File, Metadata},
    io::{self, Read, Write},
    os::unix::{fs::MetadataExt, net::UnixStream},
    path::Path,
    time::Instant,
};

#[derive(Clone, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LocalCredential {
    pub schema_version: String,
    pub principal: String,
    pub authority_id: String,
    pub token: String,
}
impl LocalCredential {
    pub fn load(directory: &Path) -> io::Result<Self> {
        private_directory(directory)?;
        let credential: Self =
            edge_contracts::parse_json(&private_file(&directory.join("client.json"))?)
                .map_err(|_| denied("invalid local credential file"))?;
        if credential.schema_version != "edge-local-credential.v1"
            || credential.principal != "local-owner"
        {
            return Err(denied("unsupported local credential"));
        }
        edge_contracts::identifier(&credential.authority_id)
            .map_err(|_| denied("invalid authority"))?;
        edge_contracts::fingerprint(&credential.token).map_err(|_| denied("invalid credential"))?;
        Ok(credential)
    }
}

pub fn denied(message: &str) -> io::Error {
    io::Error::new(io::ErrorKind::PermissionDenied, message)
}

pub fn private_metadata(path: &Path) -> io::Result<Metadata> {
    let meta = fs::symlink_metadata(path)?;
    if meta.file_type().is_symlink() || meta.uid() != geteuid().as_raw() || meta.mode() & 0o077 != 0
    {
        return Err(denied(
            "local transport path must be owned by this user, private, and not a symlink",
        ));
    }
    Ok(meta)
}

pub fn private_directory(path: &Path) -> io::Result<()> {
    if !private_metadata(path)?.is_dir() {
        return Err(denied("expected private directory"));
    }
    Ok(())
}

pub fn private_file(path: &Path) -> io::Result<Vec<u8>> {
    let before = private_metadata(path)?;
    if !before.is_file() || before.nlink() != 1 {
        return Err(denied("expected private regular file"));
    }
    let file = File::open(path)?;
    let after = file.metadata()?;
    if (before.dev(), before.ino()) != (after.dev(), after.ino()) {
        return Err(denied("file changed while opening"));
    }
    let mut bytes = Vec::new();
    file.take(4097).read_to_end(&mut bytes)?;
    if bytes.len() > 4096 {
        return Err(denied("credential file exceeds limit"));
    }
    Ok(bytes)
}

pub fn same_user(stream: &UnixStream) -> io::Result<()> {
    let peer = getsockopt(stream, PeerCredentials).map_err(io::Error::other)?;
    if peer.uid() != geteuid().as_raw() {
        return Err(denied("peer OS identity mismatch"));
    }
    Ok(())
}

/// All partial reads/writes share one absolute deadline: drip feeding does not reset it.
pub struct DeadlineStream {
    pub stream: UnixStream,
    pub deadline: Instant,
}
impl DeadlineStream {
    fn remaining(&self) -> io::Result<std::time::Duration> {
        self.deadline
            .checked_duration_since(Instant::now())
            .filter(|d| !d.is_zero())
            .ok_or_else(|| io::Error::new(io::ErrorKind::TimedOut, "local call expired"))
    }
}
impl Read for DeadlineStream {
    fn read(&mut self, bytes: &mut [u8]) -> io::Result<usize> {
        self.stream.set_read_timeout(Some(self.remaining()?))?;
        self.stream.read(bytes)
    }
}
impl Write for DeadlineStream {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        self.stream.set_write_timeout(Some(self.remaining()?))?;
        self.stream.write(bytes)
    }
    fn flush(&mut self) -> io::Result<()> {
        self.stream.flush()
    }
}
