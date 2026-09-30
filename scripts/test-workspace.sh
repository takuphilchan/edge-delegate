#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"
if [[ "$(uname -s)" != Linux ]]; then
  echo "Notes persistence currently requires Linux/WSL." >&2
  exit 2
fi
cargo test --locked -p edge-workspace
cargo build --locked -p edge-workspace --examples
target_dir="$(cargo metadata --locked --no-deps --format-version 1 | python3 -c 'import json,sys; print(json.load(sys.stdin)["target_directory"])')"
python3 scripts/check_workspace_example.py "$target_dir/debug/examples/notes" "$target_dir/debug/examples/notes_authority"
