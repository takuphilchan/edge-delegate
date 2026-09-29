#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"
if [[ "$(uname -s)" != Linux ]]; then
  echo "This service smoke test needs Linux or WSL; other native transports are pending." >&2
  exit 2
fi
if ! command -v cargo >/dev/null 2>&1; then
  echo 'Cargo is missing from this shell. Run: source "$HOME/.cargo/env"' >&2
  exit 2
fi
command -v python3 >/dev/null
echo "Authenticated Rust preview test: no execution, model, journal or physical-device access."
cargo build --locked -p edge-host -p edge-cli
target_dir="$(cargo metadata --locked --no-deps --format-version 1 | python3 -c 'import json,sys; print(json.load(sys.stdin)["target_directory"])')"
task_run_dir="$(mktemp -d /tmp/edge-service-XXXXXX)"
host_pid=""
cleanup() {
  if [[ -n "$host_pid" ]]; then
    kill "$host_pid" 2>/dev/null || true
    wait "$host_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
"$target_dir/debug/edge-delegate-host" serve-preview \
  --directory "$task_run_dir/host" \
  --context conformance/contracts/preview-v2/context.json \
  > "$task_run_dir/host.log" 2>&1 &
host_pid=$!
for ((attempt=0; attempt<100; attempt++)); do
  [[ -f "$task_run_dir/host/client.json" ]] && break
  if ! kill -0 "$host_pid" 2>/dev/null; then
    echo "Host startup failed; see $task_run_dir/host.log" >&2
    exit 1
  fi
  sleep 0.05
done
if [[ ! -f "$task_run_dir/host/client.json" ]]; then
  echo "Host readiness timed out; see $task_run_dir/host.log" >&2
  exit 1
fi
"$target_dir/debug/edgectl" capabilities --directory "$task_run_dir/host" > "$task_run_dir/capabilities.json"
"$target_dir/debug/edgectl" preview --request conformance/contracts/preview-v2/request.json \
  --directory "$task_run_dir/host" > "$task_run_dir/remote-preview.json"
"$target_dir/debug/edgectl" preview --request conformance/contracts/preview-v2/request.json \
  --context conformance/contracts/preview-v2/context.json > "$task_run_dir/offline-preview.json"
python3 - "$task_run_dir" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
remote = json.loads((root / "remote-preview.json").read_text())
offline = json.loads((root / "offline-preview.json").read_text())
assert remote == offline, "service/offline preview mismatch"
assert remote["execution_attempted"] is False
assert remote["decision"]["status"] == "proposed"
assert remote["decision"]["requires_approval"] is True
assert remote["decision"]["plan"]["steps"][0]["parameters"]["percent"]["value"] == 40
assert not list((root / "host").glob("*.sqlite*")), "preview must not create an execution journal"
print("PASS: authenticated capability discovery and matching 40% preview; zero actions executed.")
PY
echo "Reports retained: $task_run_dir (client.json is private; do not share it)."
echo "The test host stops automatically. This is not execution or production qualification."
