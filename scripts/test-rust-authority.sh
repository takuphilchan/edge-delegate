#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"
if [[ "$(uname -s)" != Linux ]]; then
  echo "This software authority diagnostic requires Linux/WSL." >&2
  exit 2
fi
if ! command -v cargo >/dev/null 2>&1; then
  echo 'Cargo is missing. Run: source "$HOME/.cargo/env"' >&2
  exit 2
fi
command -v python3 >/dev/null
echo "SOFTWARE ONLY: scoped admission, cancellation, overload and recovery. No model or physical actions."
cargo build --locked -p edge-simulator --bins
cargo test --locked -p edge-core cancellation
cargo test --locked -p edge-storage --test admission
cargo test --locked -p edge-simulator --test authority --test recovery
target_dir="$(cargo metadata --locked --no-deps --format-version 1 | python3 -c 'import json,sys; print(json.load(sys.stdin)["target_directory"])')"
task_run_dir="$(mktemp -d /tmp/edge-authority-XXXXXX)"
cargo run --locked -p edge-simulator --example authority -- \
  "$task_run_dir/evidence" "$target_dir/debug/edge-delegate-simulator-worker"
echo "Journals retained. This is an in-process diagnostic, not execution RPC or production qualification."
