"""Compatibility entry point for the guarded adapter trainer."""

import sys

from edge_delegate.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["train", *sys.argv[1:]]))
