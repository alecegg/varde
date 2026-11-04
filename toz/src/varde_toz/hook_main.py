"""Entry point for direct Python invocation of the harness hook."""

from __future__ import annotations

import sys

from .hook import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
