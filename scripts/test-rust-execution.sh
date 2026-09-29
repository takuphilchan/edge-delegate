#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"
if [[ "$(uname -s)" != Linux ]]; then
  echo "Execution IPC currently requires Linux/WSL." >&2
  exit 2
fi
if ! command -v cargo >/dev/null 2>&1; then
  echo 'Cargo is missing. Run: source "$HOME/.cargo/env"' >&2
  exit 2
fi
command -v python3 >/dev/null
echo "Authenticated SOFTWARE execution: separate client/owner credentials, no model or native device actions."
cargo build --locked -p edge-host -p edge-cli -p edge-simulator --bins
cargo build --locked -p edge-client --example approved_request
cargo test --locked -p edge-protocol --test execution
cargo test --locked -p edge-simulator --test execution_service
target_dir="$(cargo metadata --locked --no-deps --format-version 1 | python3 -c 'import json,sys; print(json.load(sys.stdin)["target_directory"])')"
task_run_dir="$(mktemp -d /tmp/edge-execution-XXXXXX)"
python3 scripts/check_rust_execution.py "$target_dir/debug/edge-delegate-host" "$target_dir/debug/edgectl" "$task_run_dir/evidence"
python3 scripts/check_rust_execution_tutorial.py "$target_dir/debug/edge-delegate-host" "$target_dir/debug/edgectl" "$task_run_dir/tutorial" "$target_dir/debug/examples/approved_request"
