#!/usr/bin/env bash
# Run from WSL/Linux. Uses fresh emulator state, never your interactive demo.
set -euo pipefail
REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"
if [[ -n "${VIRTUAL_ENV:-}" && -x "$VIRTUAL_ENV/bin/python" ]]; then
    EDGE_PYTHON="$VIRTUAL_ENV/bin/python"
elif [[ -x "$HOME/.venvs/edge-model/bin/python" ]]; then
    EDGE_PYTHON="$HOME/.venvs/edge-model/bin/python"
else
    echo "Activate the Python environment with Edge Delegate and model dependencies installed." >&2
    exit 2
fi
if [[ "${1:-}" == "--help" ]]; then
    exec "$EDGE_PYTHON" scripts/profile_latency.py --help
fi
mkdir -p artifacts/performance
EDGE_REPORT_ROOT="$(mktemp -d "$REPO_DIR/artifacts/performance/latency-XXXXXX")"
echo "Automatic software-emulator test: no physical hardware, training, or external model calls."
echo "36 requests by default; includes pauses. Compilation may take a few minutes."
echo "Report: $EDGE_REPORT_ROOT/report/report.json"
exec "$EDGE_PYTHON" scripts/profile_latency.py \
    --artifact artifacts/training/functiongemma-tasks-v1-r2-b16/selected-adapter \
    --settings configs/inference/functiongemma-tasks-compiled.json \
    --output "$EDGE_REPORT_ROOT/report" "$@"
