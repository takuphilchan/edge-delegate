"""Compatibility entry point for planner evaluation."""

from __future__ import annotations

import sys

from edge_delegate_lab.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["evaluate", *sys.argv[1:]]))
