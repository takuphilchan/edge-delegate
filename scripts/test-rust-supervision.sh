#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"
if [[ "$(uname -s)" != Linux ]]; then
  echo "This supervision test requires Linux/WSL. Other native supervisors are pending." >&2
  exit 2
fi
if ! command -v cargo >/dev/null 2>&1; then
  echo 'Cargo is missing. Run: source "$HOME/.cargo/env"' >&2
  exit 2
fi
command -v python3 >/dev/null
echo "Supervised SOFTWARE test: fixture approvals, no physical device or native audio changes."
cargo build --locked -p edge-host -p edge-simulator --bins
cargo test --locked -p edge-simulator --test supervised
target_dir="$(cargo metadata --locked --no-deps --format-version 1 | python3 -c 'import json,sys; print(json.load(sys.stdin)["target_directory"])')"
task_run_dir="$(mktemp -d /tmp/edge-supervision-XXXXXX)"
cargo run --locked -p edge-simulator --example supervised -- \
  "$task_run_dir/evidence" "$target_dir/debug/edge-delegate-simulator-worker"
python3 scripts/check_rust_console.py "$target_dir/debug/edge-delegate-host" "$task_run_dir/console"
echo "No journals deleted. This diagnostic is not hardware, model-quality or production qualification."
