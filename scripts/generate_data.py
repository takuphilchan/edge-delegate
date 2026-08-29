"""Compatibility entry point for deterministic dataset generation."""

from __future__ import annotations

import sys

from edge_delegate.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["generate-data", *sys.argv[1:]]))
