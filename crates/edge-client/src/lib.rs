//! Public experimental preview and software-execution clients. No executor, storage,
//! adapter or model dependencies. Authentication is not OS isolation from same-user code.
#[cfg(target_os = "linux")]
pub mod execution;
#[cfg(target_os = "linux")]
pub mod local;
