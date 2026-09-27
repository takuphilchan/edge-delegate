#!/usr/bin/env bash
# Explicit deterministic baseline, not a replacement measurement of the trained model.
set -euo pipefail
EDGE_REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
echo "Bounded command grammar test: NOT a learned-model accuracy result."
exec bash "$EDGE_REPO/scripts/test-numeric.sh" \
    --plugin bounded-commands --no-artifact \
    --settings configs/inference/numeric-decimal-v1.json "$@"
