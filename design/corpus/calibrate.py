"""Calibration runner: run `varde design check` over the corpus and aggregate.

Usage (repository root):
    python design/corpus/calibrate.py OUTDIR [--memory-root DIR] [--jobs N]

Fetches the third-party pages into OUTDIR/third (never committed), checks every
unit twice with both tiers and once static-only, and writes raw.jsonl,
summary.json, label-sheet.jsonl and label-key.jsonl under OUTDIR. Maintainer
tool; no model calls. Labelling and rule tuning happen elsewhere.
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import corpus

SHEET_CAP = 300
# The CLI shows at most 40 findings; lift the cap here so counts are complete.
UNCAPPED = (
    "import sys, varde_design.check as c; c.MAX_FINDINGS = 10**9; "
    "from varde_design.cli import run; sys.exit(run(sys.argv[1:]))"
)
ROOT = Path(__file__).resolve().parents[2]


def fetch_with_retry(url: str) -> bytes:
    """curl copes with the sandbox proxy truncating urllib reads (IncompleteRead)."""
    done = subprocess.run(
        ["curl", "-sS", "-f", "--retry", "6", "--retry-all-errors", url],
        capture_output=True, check=True,
    )
    return done.stdout


def fetch_third_party(manifest: dict, dest: Path) -> list[str]:
    return [
        f"{page['id']}: {path}"
        for page in manifest["third_party"]
        for path in corpus.fetch_page(page, dest, fetch_with_retry)
    ]


def units(manifest: dict, third: Path, memory_root: Path) -> list[dict]:
    result = [
        {"part": "varde", "name": name, "path": memory_root / manifest["varde"]["root"] / name}
        for name in sorted(manifest["varde"]["pages"])
    ]
    result += [
        {"part": "third-party", "name": page["id"], "path": third / page["id"]}
        for page in manifest["third_party"]
    ]
    synthetic = ROOT / manifest["synthetic"]["root"]
    result += [
        {"part": "synthetic", "name": str(p.relative_to(synthetic)), "path": p}
        for p in sorted(synthetic.rglob("*.html"))
    ]
    return result


def run_check(unit: dict, static_only: bool) -> dict:
    command = [sys.executable, "-c", UNCAPPED, "check", "--json", "--profile", "opinion"]
    command += ["--static-only"] if static_only else []
    started = time.monotonic()
    done = subprocess.run([*command, str(unit["path"])], capture_output=True, text=True, check=False)
    seconds = time.monotonic() - started
    try:
        report = json.loads(done.stdout)
    except json.JSONDecodeError:
        report = {"error": done.stderr[-300:], "findings": [], "checked": {}}
    return {"unit": unit, "report": report, "seconds": seconds, "exit": done.returncode}


def run_all(unit_list: list[dict], static_only: bool, jobs: int) -> list[dict]:
    with ThreadPoolExecutor(jobs) as pool:
        return list(pool.map(lambda u: run_check(u, static_only), unit_list))


def finding_rows(results: list[dict]) -> list[dict]:
    rows = []
    for result in results:
        unit = result["unit"]
        for f in result["report"].get("findings", []):
            file = Path(f["file"])
            base = unit["path"] if unit["path"].is_dir() else unit["path"].parent
            rows.append({
                "part": unit["part"], "page": f"{unit['part']}/{unit['name']}",
                "file": str(file.relative_to(base)) if file.is_relative_to(base) else file.name,
                "rule": f["id"], "severity": f["severity"], "tier": f["tier"],
                "line": f["line"], "selector": f["selector"], "width": f["width"],
                "snippet": f["snippet"], "message": f["message"],
                "abs": str(file),
            })
    return sorted(rows, key=lambda r: json.dumps(r, sort_keys=True))


def fair_quotas(sizes: dict[str, int], cap: int) -> dict[str, int]:
    quotas = {rule: 0 for rule in sizes}
    left = cap
    open_rules = {rule for rule, n in sizes.items() if n}
    while left > 0 and open_rules:
        share = max(left // len(open_rules), 1)
        for rule in sorted(open_rules):
            take = min(share, sizes[rule] - quotas[rule], left)
            quotas[rule] += take
            left -= take
        open_rules = {r for r in open_rules if quotas[r] < sizes[r]}
    return quotas


def sample_rule(rows: list[dict], quota: int, rng: random.Random) -> list[dict]:
    by_part: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_part[row["part"]].append(row)
    for part_rows in by_part.values():
        rng.shuffle(part_rows)
    picked = []
    while len(picked) < quota:
        for part in sorted(by_part):
            if by_part[part] and len(picked) < quota:
                picked.append(by_part[part].pop())
    return picked


def context(row: dict) -> str:
    if row["part"] == "third-party" or not row["line"]:
        return ""
    lines = Path(row["abs"]).read_text(encoding="utf-8", errors="replace").splitlines()
    low = max(row["line"] - 2, 0)
    return "\n".join(line[:200] for line in lines[low : row["line"] + 1])


def label_sheet(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    rng = random.Random(4)
    by_rule: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_rule[row["rule"]].append(row)
    quotas = fair_quotas({r: len(v) for r, v in by_rule.items()}, SHEET_CAP)
    chosen = [r for rule in sorted(by_rule) for r in sample_rule(by_rule[rule], quotas[rule], rng)]
    rng.shuffle(chosen)
    sheet, key = [], []
    for index, row in enumerate(chosen, 1):
        ident = f"F{index:03d}"
        sheet.append({"id": ident, "page": row["page"], "file": row["file"], "line": row["line"],
                      "selector": row["selector"], "width": row["width"],
                      "snippet": row["snippet"], "context": context(row)})
        key.append({"id": ident, "rule": row["rule"], "part": row["part"], "tier": row["tier"],
                    "severity": row["severity"], "message": row["message"]})
    return sheet, key


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path)
    parser.add_argument("--memory-root", type=Path, default=Path.home() / "source/agent-memory")
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = corpus.load()
    mismatched = fetch_third_party(manifest, args.out / "third")
    unit_list = units(manifest, args.out / "third", args.memory_root)
    runs = {}
    for name, static_only in (("full1", False), ("full2", False), ("static", True)):
        started = time.monotonic()
        runs[name] = run_all(unit_list, static_only, args.jobs)
        runs[name + "_wall"] = time.monotonic() - started
    rows = {name: finding_rows(runs[name]) for name in ("full1", "full2", "static")}
    write_jsonl(args.out / "raw.jsonl", rows["full1"])
    write_jsonl(args.out / "raw2.jsonl", rows["full2"])
    write_jsonl(args.out / "raw-static.jsonl", rows["static"])
    sheet, key = label_sheet(rows["full1"])
    write_jsonl(args.out / "label-sheet.jsonl", sheet)
    write_jsonl(args.out / "label-key.jsonl", key)
    timing = {
        name: {"sum_seconds": sum(r["seconds"] for r in runs[name]), "wall": runs[name + "_wall"]}
        for name in ("full1", "full2", "static")
    }
    summary = {
        "units": Counter(u["part"] for u in unit_list), "hash_mismatch": mismatched,
        "timing": timing,
        "exit_codes": Counter(r["exit"] for r in runs["full1"]),
        "errors": [r["unit"]["name"] for r in runs["full1"] if "error" in r["report"]],
        "truncated": [r["unit"]["name"] for r in runs["full1"] if r["report"].get("checked", {}).get("truncated")],
        "not_run": sorted({str(n) for r in runs["full1"] for n in r["report"].get("checked", {}).get("not_run", [])}),
        "per_unit_seconds": {f"{r['unit']['part']}/{r['unit']['name']}": round(r["seconds"], 2) for r in runs["full1"]},
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=1, default=dict), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("units", "hash_mismatch", "timing", "errors", "truncated", "not_run")}, default=dict))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
