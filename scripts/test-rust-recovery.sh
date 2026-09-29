#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"
if ! command -v cargo >/dev/null 2>&1; then
  echo "cargo is missing. Install Rust using https://rust-lang.org/tools/install/ and reopen your shell." >&2
  echo "The repository pins the toolchain; see docs/tutorials/rust-recovery.md." >&2
  exit 2
fi

echo "Rust software-recovery checks: no physical devices, model loading or remote service."
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked
task_run_dir="$(mktemp -d "${TMPDIR:-/tmp}/edge-recovery-XXXXXX")"
cargo run --locked -p edge-simulator --example recovery -- "$task_run_dir/evidence"
echo "Retained demonstration records: $task_run_dir/evidence"
echo "Temporary storage is not disk-backed performance or power-loss qualification."
