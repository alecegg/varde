#!/usr/bin/env python3
"""Record system load around a measured row."""

from __future__ import annotations

import json
import os


def sample() -> tuple[float, float, float]:
    return os.getloadavg()


def main() -> int:
    print(json.dumps({"load": sample()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
