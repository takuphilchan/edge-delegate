#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"
if [[ "$(uname -s)" != Linux ]]; then
  echo "Authenticated workspace service currently requires Linux/WSL." >&2
  exit 2
fi
echo "V2 service diagnostic: real private test notes; no model or native device actions."
cargo test --locked -p edge-workspace --test service
cargo build --locked -p edge-host -p edge-workspace -p edge-cli
cargo build --locked -p edge-client --example workspace_client
target_dir="$(cargo metadata --locked --no-deps --format-version 1 | python3 -c 'import json,sys; print(json.load(sys.stdin)["target_directory"])')"
python3 scripts/check_workspace_service.py "$target_dir/debug"
