#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
echo "Software light controls: no model inference, training, or physical actions."
python -m pytest -q tests/integration/test_light_control.py
