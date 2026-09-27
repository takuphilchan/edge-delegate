#!/usr/bin/env bash
set -euo pipefail
EDGE_REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$EDGE_REPO"
EDGE_PYTHON="${VIRTUAL_ENV:-$HOME/.venvs/edge-model}/bin/python"
if [[ ! -x "$EDGE_PYTHON" ]]; then
    echo "Activate the environment with Edge Delegate and model dependencies installed." >&2
    exit 2
fi
if [[ "${1:-}" == "--help" ]]; then
    exec "$EDGE_PYTHON" scripts/test_numeric.py --help
fi
mkdir -p artifacts/numeric
EDGE_OUTPUT="$(mktemp -d "$EDGE_REPO/artifacts/numeric/challenge-XXXXXX")"
exec "$EDGE_PYTHON" scripts/test_numeric.py --output "$EDGE_OUTPUT/report" "$@"
