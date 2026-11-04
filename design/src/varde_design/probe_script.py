"""In-page measurement script; returns plain JSON-able data for one viewport."""

from __future__ import annotations

from pathlib import Path

MAX_ELEMENTS = 2000
PROBE_SCRIPT = (Path(__file__).with_name("probe.js")).read_text(encoding="utf-8")
