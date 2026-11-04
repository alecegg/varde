"""Count design-check findings per rule on Varde pages, with and without config.

Usage (repository root, venv python, PYTHONPATH=design/src):
    python design/corpus/adopt_varde.py OUTDIR [--memory-root DIR] [--static-only]

Corpus pages sit outside this repo, so the sheets come from `--tokens`
(runner style sheet) and settings from `--config`. Maintainer tool.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UNCAPPED = (
    "import sys, varde_design.check as c; c.MAX_FINDINGS = 10**9; "
    "from varde_design.cli import run; sys.exit(run(sys.argv[1:]))"
)
TOKENS = "runner/ui/src/style.css"


def units(memory_root: Path) -> list[Path]:
    manifest = json.loads((ROOT / "design/corpus/manifest.json").read_text())
    base = memory_root / manifest["varde"]["root"]
    pages = [base / name for name in sorted(manifest["varde"]["pages"])]
    return [*pages, ROOT / "runner/ui/src/app.html"]


def run_one(path: Path, configured: bool, static_only: bool, profile: str) -> dict:
    cmd = [sys.executable, "-c", UNCAPPED, "check", "--json"]
    if configured:
        cmd += ["--config", str(ROOT / "varde-design.toml")]
        cmd += ["--tokens", str(ROOT / TOKENS)]
    if static_only:
        cmd.append("--static-only")
    if profile:
        cmd += ["--profile", profile]
    full = [*cmd, str(path)]
    done = subprocess.run(full, capture_output=True, text=True, check=False)  # noqa: S603
    try:
        report = json.loads(done.stdout)
    except json.JSONDecodeError:
        report = {"error": done.stderr[-300:], "findings": []}
    return {"path": str(path), "exit": done.returncode, "report": report}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("outdir")
    default_root = str(Path.home() / "source/agent-memory")
    parser.add_argument("--memory-root", default=default_root)
    parser.add_argument("--static-only", action="store_true")
    parser.add_argument("--profile", default="")
    args = parser.parse_args(argv)
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    paths = units(Path(args.memory_root))
    summary: dict[str, dict] = {}
    for label, configured in (("without", False), ("with", True)):
        opts = {
            "configured": configured,
            "static_only": args.static_only,
            "profile": args.profile,
        }
        with ThreadPoolExecutor(4) as pool:
            rows = list(pool.map(partial(run_one, **opts), paths))
        (out / f"{label}.json").write_text(json.dumps(rows))
        counts: Counter[str] = Counter()
        for row in rows:
            counts.update(f["id"] for f in row["report"].get("findings", []))
        summary[label] = {
            "rules": dict(sorted(counts.items())),
            "exits": dict(Counter(row["exit"] for row in rows)),
            "errors": sum("error" in row["report"] for row in rows),
        }
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
