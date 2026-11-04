"""Mutation testing for `varde design check`: person-free ground truth.

Usage (repository root):
    python design/corpus/mutate.py OUTDIR [--memory-root DIR] [--per-family N]
                                   [--seed S] [--jobs J]

Takes base pages (synthetic fixtures, self-contained pinned Varde pages), keeps
per rule only the bases where the checker reports nothing for that rule, applies
the mutation families in design_mutations.py, runs the checker (both tiers) and writes
results.jsonl, summary.json and summary.md under OUTDIR. Deterministic for a
given seed and base set. Reads rules only through the checker's JSON; never
tunes a rule.
"""

# ruff: noqa: S311  (seeded sampling for reproducibility, not cryptography)

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import design_mutations
from design_mutations import MARK, Family

ROOT = Path(__file__).resolve().parents[2]
UNCAPPED = (
    "import sys, varde_design.check as c; c.MAX_FINDINGS = 10**9; "
    "from varde_design.cli import run; sys.exit(run(sys.argv[1:]))"
)
RELATIVE_ASSET = re.compile(
    r"""<link[^>]+rel=["']?stylesheet[^>]+href=["']?(?!https?:|data:|//)"""
    r"""|<script[^>]+src=["']?(?!https?:|data:|//)""",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Mutant:
    family: Family
    base: str
    html: str


def self_contained(html: str) -> bool:
    return RELATIVE_ASSET.search(html) is None


def load_bases(manifest: dict, memory_root: Path | None) -> dict[str, str]:
    synthetic = ROOT / manifest["synthetic"]["root"]
    bases = {
        f"synthetic/{p.relative_to(synthetic)}": p
        for p in sorted(synthetic.rglob("*.html"))
    }
    if memory_root is not None:
        root = memory_root / manifest["varde"]["root"]
        bases |= {
            f"varde/{name}": root / name for name in sorted(manifest["varde"]["pages"])
        }
    texts = {}
    for name, path in bases.items():
        try:
            texts[name] = path.read_text(encoding="utf-8")
        except OSError, UnicodeDecodeError:
            continue
    return {name: text for name, text in texts.items() if self_contained(text)}


def check_html(path: Path, static_only: bool) -> dict:
    command = [
        sys.executable,
        "-c",
        UNCAPPED,
        "check",
        "--json",
        "--profile",
        "opinion",
    ]
    command += ["--static-only"] if static_only else []
    done = subprocess.run(  # noqa: S603
        [*command, str(path)], capture_output=True, text=True, check=False
    )
    try:
        return json.loads(done.stdout)
    except json.JSONDecodeError:
        return {"error": done.stderr[-300:], "findings": [], "checked": {}}


def rules_hit(report: dict) -> dict[str, list[dict]]:
    hit: dict[str, list[dict]] = defaultdict(list)
    for finding in report.get("findings", []):
        hit[finding["id"]].append(finding)
    return hit


def pick(items: list, count: int, label: str, seed: int) -> list:
    return random.Random(f"{seed}:{label}").sample(items, min(count, len(items)))


def generate(
    families: tuple[Family, ...],
    bases: dict[str, str],
    eligible: dict[str, set[str]],
    per_family: int,
    seed: int,
) -> list[Mutant]:
    """Pure: choose bases per family and apply the mutation. Deterministic."""
    mutants = []
    for family in families:
        pool = sorted(eligible[family.rule]) if family.rule != "*" else sorted(bases)
        applicable = []
        for base in pool:
            html = family.apply(
                bases[base], random.Random(f"{seed}:{family.name}:{base}")
            )
            if html is not None and html != bases[base]:
                applicable.append(Mutant(family, base, html))
        mutants += pick(applicable, per_family, family.name, seed)
    return mutants


def _names_mark(finding: dict, lines: list[str]) -> bool:
    if MARK in (finding["selector"] or "") or MARK in (finding["snippet"] or ""):
        return True
    line = finding["line"]
    return line is not None and 0 < line <= len(lines) and MARK in lines[line - 1]


def fired(mutant: Mutant, rule: str, hits: dict[str, list[dict]]) -> tuple[bool, bool]:
    """(any finding of rule, finding on the MARK element or no element needed)."""
    findings = hits.get(rule, [])
    lines = mutant.html.splitlines()
    on_mark = any(_names_mark(f, lines) for f in findings)
    return bool(findings), on_mark or not mutant.family.targeted


def score(
    mutant: Mutant, report: dict, base_zero: dict[str, set[str]], rules: list[str]
) -> list[dict]:
    hits = rules_hit(report)
    targets = rules if mutant.family.rule == "*" else [mutant.family.rule]
    rows = []
    for rule in targets:
        if mutant.base not in base_zero[rule]:
            continue
        any_hit, on_target = fired(mutant, rule, hits)
        rows.append(
            {
                "family": mutant.family.name,
                "kind": mutant.family.kind,
                "rule": rule,
                "base": mutant.base,
                "fired": any_hit,
                "hit": any_hit and on_target,
                "messages": [f["message"] for f in hits.get(rule, [])[:1]],
            }
        )
    return rows


def summarize(rows: list[dict], flaky: list[dict]) -> dict:
    """Per rule: defect recall, benign false-fire, base re-run false-fire, misses."""
    out: dict[str, dict] = defaultdict(
        lambda: {
            "defect_n": 0,
            "defect_hit": 0,
            "benign_n": 0,
            "benign_fired": 0,
            "base_n": 0,
            "base_fired": 0,
            "by_family": {},
            "false_fires": [],
        }
    )
    for row in rows:
        rule = out[row["rule"]]
        stat = rule["by_family"].setdefault(
            row["family"], {"kind": row["kind"], "n": 0, "ok": 0}
        )
        stat["n"] += 1
        if row["kind"] == "defect":
            rule["defect_n"] += 1
            rule["defect_hit"] += row["hit"]
            stat["ok"] += row["hit"]
            continue
        rule["benign_n"] += 1
        rule["benign_fired"] += row["fired"]
        stat["ok"] += not row["fired"]
        if row["fired"]:
            rule["false_fires"].append(
                f"{row['family']} on {row['base']}: {row['messages']}"
            )
    for row in flaky:
        out[row["rule"]]["base_n"] += 1
        out[row["rule"]]["base_fired"] += row["fired"]
    return dict(sorted(out.items()))


def markdown(summary: dict, config: dict) -> str:
    lines = [
        (
            f"seed {config['seed']}, per-family cap {config['per_family']}, "
            f"{config['bases']} bases, rendered tier: {config['rendered']}"
        ),
        "",
        (
            "| rule | defect recall | benign false-fire | base re-run false-fire "
            "| family breakdown (ok/n) |"
        ),
        "| --- | --- | --- | --- | --- |",
    ]
    for rule, s in summary.items():
        families = "; ".join(
            f"{k}{'*' if v['kind'] == 'benign' else ''} {v['ok']}/{v['n']}"
            for k, v in sorted(s["by_family"].items())
        )
        recall = f"{s['defect_hit']}/{s['defect_n']}" if s["defect_n"] else "-"
        benign = f"{s['benign_fired']}/{s['benign_n']}" if s["benign_n"] else "-"
        lines.append(
            f"| {rule} | {recall} | {benign} | {s['base_fired']}/{s['base_n']} | {families} |"  # noqa: E501
        )
    lines += ["", "`*` marks a benign family (ok = did not fire)."]
    return "\n".join(lines)


def run_all(paths: list[Path], static_only: bool, jobs: int) -> list[dict]:
    with ThreadPoolExecutor(jobs) as pool:
        return list(pool.map(lambda p: check_html(p, static_only), paths))


def digest(mutants: list[Mutant]) -> str:
    text = json.dumps([[m.family.name, m.base, m.html] for m in mutants])
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("outdir", type=Path)
    ap.add_argument("--memory-root", type=Path)
    ap.add_argument("--per-family", type=int, default=6)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=4)
    args = ap.parse_args(argv)
    manifest = json.loads((Path(__file__).parent / "manifest.json").read_text())
    bases = load_bases(manifest, args.memory_root)
    work = args.outdir / "pages"
    work.mkdir(parents=True, exist_ok=True)
    names = sorted(bases)
    for i, name in enumerate(names):
        (work / f"base-{i}.html").write_text(bases[name], encoding="utf-8")
    paths = [work / f"base-{i}.html" for i in range(len(names))]
    first, second = run_all(paths, False, args.jobs), run_all(paths, False, args.jobs)
    rendered = all(r.get("checked", {}).get("rendered") for r in first)
    rules = sorted(
        {f["id"] for r in first for f in r["findings"]}
        | {s["rule"] for s in manifest["synthetic"]["rule_pairs"]}
    )
    rules = [r for r in rules if r != "IGN"]
    base_zero = {
        r: {n for n, rep in zip(names, first, strict=True) if r not in rules_hit(rep)}
        for r in rules
    }
    flaky = [
        {"rule": r, "fired": r in rules_hit(rep2)}
        for r in rules
        for n, rep2 in zip(names, second, strict=True)
        if n in base_zero[r]
    ]
    eligible = {**base_zero, "*": set(names)}
    runnable = tuple(f for f in design_mutations.FAMILIES if rendered or not f.rendered)
    mutants = generate(runnable, bases, eligible, args.per_family, args.seed)
    for i, m in enumerate(mutants):
        (work / f"m-{i}.html").write_text(m.html, encoding="utf-8")
    reports = run_all(
        [work / f"m-{i}.html" for i in range(len(mutants))], False, args.jobs
    )
    rows = [
        row
        for m, rep in zip(mutants, reports, strict=True)
        for row in score(m, rep, base_zero, rules)
    ]
    summary = summarize(rows, flaky)
    config = {
        "seed": args.seed,
        "per_family": args.per_family,
        "bases": len(names),
        "rendered": rendered,
        "digest": digest(mutants),
    }
    (args.outdir / "results.jsonl").write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n"
    )
    (args.outdir / "summary.json").write_text(
        json.dumps({"config": config, "rules": summary}, indent=2)
    )
    (args.outdir / "summary.md").write_text(markdown(summary, config) + "\n")
    print(markdown(summary, config))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
