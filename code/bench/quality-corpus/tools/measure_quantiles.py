"""Corpus quantiles of the wider row measures, per language (experiment).

    uv run python measure_quantiles.py [--check] [--compare-proxy] [--out FILE]

No model call; deterministic. Files are dev-split only (``splits.lock``), taken
from the verified corpus checkouts (and, for Python, the reference repos) in
path-hash order, each measured as one module with ``raw_measure_sources``.
Reports q50/q90/q99 with ``n`` beside every value for ``max_nesting`` and
``vague_names`` (per function, Python for ``vague_names``) and
``delegation_share`` and ``tokens_p50`` (per file; ``delegation_share`` exact,
Python only). ``--compare-proxy`` measures the exact delegation share against the
t18 proxy on the ``wrappers`` and ``deep_chain`` degradations (median share and
flag rate) and on the unchanged good files at each shipped cut.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from fractions import Fraction
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import baseline_index_run as ir
import baseline_measure as bm
import baseline_rank_run as rr
import region_sim as rs
import score_separation_run as ssr
from varde_code.quality_score import file_advisories as fa

LANGUAGES = {"python": "Python", "typescript": "TypeScript", "csharp": "C#"}
QUANTILES = (50, 90, 99)
FUNCTION_MEASURES = ("max_nesting", "vague_names")
FILE_MEASURES = ("delegation_share", "tokens_p50")
WRAPPER_KINDS = ("wrappers", "deep_chain")
GOOD_FLAG_BUDGET = 0.10
SKIPPED_PARTS = ir.SKIPPED_PARTS | {"node_modules", "bin", "obj", "__pycache__"}


# ---- pure helpers -----------------------------------------------------------


def nearest_rank(values: Sequence[float], percent: int) -> float:
    ordered = sorted(values)
    rank = max((percent * len(ordered) + 99) // 100, 1)
    return ordered[rank - 1]


def quantiles(values: Sequence[float]) -> dict[str, Any]:
    """q50/q90/q99 (nearest rank) with ``n``; quantiles are ``None`` when empty."""
    found = {f"q{p}": (nearest_rank(values, p) if values else None) for p in QUANTILES}
    return {**found, "n": len(values)}


def is_language_candidate(path: str, language: str) -> bool:
    parts = path.split("/")
    return (
        path.endswith(bm.SUFFIXES[language])
        and not SKIPPED_PARTS & set(parts[:-1])
        and not bm.TEST_FILE.search(parts[-1])
    )


def hash_order(paths: Sequence[str]) -> list[str]:
    return sorted(paths, key=lambda p: hashlib.sha256(p.encode()).hexdigest())


def column(values: Sequence[Any]) -> list[Any]:
    return [v for v in values if v is not None]


def language_report(measured: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Quantiles over ``raw_measure_sources`` results (one per file)."""
    rows = [row for result in measured for row in result["functions"]]
    files = [m for result in measured for m in result["file_measures"].values()]
    report: dict[str, Any] = {"files": len(measured), "functions": len(rows)}
    for name in FUNCTION_MEASURES:
        report[name] = quantiles(column([row[name] for row in rows]))
    for name in FILE_MEASURES:
        report[name] = quantiles(column([m[name] for m in files]))
    return report


def flag_rate(shares: Sequence[float | None], cut: Fraction) -> dict[str, Any]:
    """Share of files with a delegation share above ``cut``, with ``n``."""
    known = column(shares)
    flagged = sum(share > cut for share in known)
    return {
        "n": len(known),
        "flagged": flagged,
        "rate": flagged / len(known) if known else None,
    }


def without_exact(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [{**row, "delegates": None} for row in rows]


def proxy_and_exact(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[float | None, float | None]:
    return fa.delegation_share(without_exact(rows)), fa.exact_delegation_share(rows)


def proxy_comparison(
    by_kind: Mapping[str, Sequence[Sequence[Mapping[str, Any]]]],
    proxy_cut: Fraction,
    exact_cut: Fraction,
) -> dict[str, Any]:
    """Flag rates of the proxy and the exact share per variant kind (rows per file)."""
    result: dict[str, Any] = {}
    for kind, files in sorted(by_kind.items()):
        pairs = [proxy_and_exact(rows) for rows in files if rows]
        result[kind] = {
            "proxy": flag_rate([p for p, _ in pairs], proxy_cut),
            "exact": flag_rate([e for _, e in pairs], exact_cut),
            "p90": {
                "proxy": quantiles(column([p for p, _ in pairs]))["q90"],
                "exact": quantiles(column([e for _, e in pairs]))["q90"],
            },
            "median": {
                "proxy": quantiles(column([p for p, _ in pairs]))["q50"],
                "exact": quantiles(column([e for _, e in pairs]))["q50"],
            },
            "exact_at_least_proxy": {
                "n": len(pairs),
                "files": sum((e or 0) >= (p or 0) for p, e in pairs),
            },
        }
    return result


def comparison_problems(comparison: Mapping[str, Any]) -> list[str]:
    problems = []
    for kind in WRAPPER_KINDS:
        cell = comparison.get(kind)
        if not cell or not cell["exact"]["n"]:
            problems.append(f"{kind}: no files")
        elif cell["median"]["exact"] < cell["median"]["proxy"]:
            problems.append(f"{kind}: exact median share below the proxy median")
    good = comparison.get("good")
    if not good or not good["exact"]["n"]:
        problems.append("good: no files")
    elif good["exact"]["rate"] > GOOD_FLAG_BUDGET:
        problems.append(f"good: exact flag rate above {GOOD_FLAG_BUDGET:.0%}")
    return problems


def check_problems(report: Mapping[str, Any]) -> list[str]:
    python = report["languages"].get("python", {})
    return [
        f"python {name}: n=0"
        for name in (*FUNCTION_MEASURES, *FILE_MEASURES)
        if not python.get(name, {}).get("n")
    ]


# ---- loading (I/O) ----------------------------------------------------------


def dev_candidates(repo: str, paths: Sequence[str], language: str) -> list[str]:
    chosen = [p for p in paths if is_language_candidate(p, language)]
    return [p for p in hash_order(chosen) if rs.split_of(f"{repo}:{p}") == "dev"]


def read_files(
    repo: str,
    paths: Sequence[str],
    read: Callable[[str], bytes | None],
    language: str,
    per_repo: int,
) -> list[bytes]:
    blobs: list[bytes] = []
    for path in dev_candidates(repo, paths, language):
        if len(blobs) >= per_repo:
            break
        blob = read(path)
        if blob is not None and ir.MIN_BYTES <= len(blob) <= ir.MAX_BYTES:
            blobs.append(blob)
    return blobs


def corpus_blobs(args: argparse.Namespace, language: str) -> dict[str, list[bytes]]:
    """Dev-split file blobs per repo for one language."""
    found: dict[str, list[bytes]] = {}
    manifest = json.loads(ir.MANIFEST.read_text())
    for repo in manifest["repositories"]:
        if repo["status"] != "verified" or LANGUAGES[language] not in repo["languages"]:
            continue
        checkout = args.cache / repo["name"].replace("/", "__")
        if not checkout.is_dir():
            continue
        out = ir.git_out(checkout, "ls-tree", "-r", "--name-only", repo["pin_sha"])
        read = rs.git_reader(checkout, repo["pin_sha"])
        found[repo["name"]] = read_files(
            repo["name"], out.decode().splitlines(), read, language, args.per_repo
        )
    if language == "python":
        for root in args.reference_repos:
            if root.is_dir():
                name = f"ref/{root.name}"
                found[name] = read_files(
                    name,
                    rr.listed_paths(root),
                    rs.file_reader(root),
                    language,
                    args.per_repo,
                )
    return {name: blobs for name, blobs in found.items() if blobs}


def measure_blob(blob: bytes, language: str) -> dict[str, Any] | None:
    name = "module" + bm.SUFFIXES[language]
    try:
        return bm.raw_measure_sources({name: blob}, language)
    except Exception:  # noqa: BLE001 - a file the parser rejects is skipped
        return None


def measure_corpus(
    blobs: Mapping[str, Sequence[bytes]], language: str
) -> list[dict[str, Any]]:
    measured = (measure_blob(b, language) for files in blobs.values() for b in files)
    return [m for m in measured if m is not None]


def degraded_rows(blob: bytes) -> dict[str, list[dict[str, Any]]]:
    """Rows of the ``wrappers`` and ``deep_chain`` variants of one Python file."""
    import quality_degrade as qd

    source = blob.decode("utf-8", "replace")
    unchanged = qd.identity(source)
    rows: dict[str, list[dict[str, Any]]] = {}
    for kind in WRAPPER_KINDS:
        try:
            text = qd.DEGRADATIONS[kind](source)
            if text != unchanged:
                rows[kind] = ir.rows_of_source(text)
        except Exception:  # noqa: BLE001, S112 - inapplicable degradations are skipped
            continue
    return rows


def compare_proxy(
    blobs: Mapping[str, Sequence[bytes]], variant_files: int
) -> dict[str, Any]:
    by_kind: dict[str, list[list[dict[str, Any]]]] = {
        "good": [],
        **{k: [] for k in WRAPPER_KINDS},
    }
    for files in blobs.values():
        for blob in files[:variant_files]:
            try:
                by_kind["good"].append(
                    ir.rows_of_source(blob.decode("utf-8", "replace"))
                )
            except Exception:  # noqa: BLE001, S112 - unmeasurable files are skipped
                continue
            for kind, rows in degraded_rows(blob).items():
                by_kind[kind].append(rows)
    cuts = (fa.DELEGATION_SHARE_CUT, fa.EXACT_DELEGATION_SHARE_CUT)
    return {
        "cuts": {"proxy": str(cuts[0]), "exact": str(cuts[1])},
        "kinds": proxy_comparison(by_kind, *cuts),
    }


# ---- report -----------------------------------------------------------------


def cell(node: Mapping[str, Any]) -> str:
    if not node["n"]:
        return "- (n=0)"
    parts = [f"q{p}={node[f'q{p}']:g}" for p in QUANTILES]
    return " ".join(parts) + f" (n={node['n']})"


def rate_cell(node: Mapping[str, Any]) -> str:
    return "-" if node["rate"] is None else f"{node['rate']:.0%} (n={node['n']})"


def comparison_lines(comparison: Mapping[str, Any]) -> list[str]:
    cuts = comparison["cuts"]
    lines = [f"flag rate above the cut (proxy {cuts['proxy']}, exact {cuts['exact']}):"]
    for kind, both in sorted(comparison["kinds"].items()):
        at_least = both["exact_at_least_proxy"]
        lines.append(
            f"  {kind}: proxy {rate_cell(both['proxy'])}, "
            f"exact {rate_cell(both['exact'])}; "
            f"median share proxy {both['median']['proxy']:.3f}, "
            f"exact {both['median']['exact']:.3f}; "
            f"exact >= proxy in {at_least['files']} of {at_least['n']} files"
        )
    return lines


def render(report: Mapping[str, Any]) -> str:
    lines = []
    for language, entry in sorted(report["languages"].items()):
        lines.append(
            f"{language}: {entry['files']} files, {entry['functions']} functions"
        )
        lines += [
            f"  {name}: {cell(entry[name])}"
            for name in (*FUNCTION_MEASURES, *FILE_MEASURES)
        ]
    if report.get("proxy_comparison"):
        lines += comparison_lines(report["proxy_comparison"])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--compare-proxy", action="store_true")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--per-repo", type=int, default=40)
    parser.add_argument("--variant-files", type=int, default=12)
    parser.add_argument(
        "--languages", nargs="+", default=list(LANGUAGES), choices=list(LANGUAGES)
    )
    parser.add_argument("--cache", type=Path, default=ssr.USER_CACHE)
    parser.add_argument(
        "--reference-repos",
        type=Path,
        nargs="*",
        default=[
            ssr.USER_HOME / "source/reference-repos" / n for n in rr.DEFAULT_REFERENCE
        ],
    )
    return parser


def run(args: argparse.Namespace) -> dict[str, Any]:
    report: dict[str, Any] = {"languages": {}, "per_repo": args.per_repo}
    python_blobs: dict[str, list[bytes]] = {}
    for language in args.languages:
        blobs = corpus_blobs(args, language)
        report["languages"][language] = language_report(measure_corpus(blobs, language))
        report["languages"][language]["repos"] = len(blobs)
        if language == "python":
            python_blobs = blobs
    if args.compare_proxy:
        report["proxy_comparison"] = compare_proxy(python_blobs, args.variant_files)
    return report


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run(args)
    print(render(report))
    if args.out:
        args.out.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    problems = []
    if args.check:
        problems += check_problems(report)
    if args.compare_proxy:
        problems += comparison_problems(report["proxy_comparison"]["kinds"])
    if args.check or args.compare_proxy:
        print("check: " + ("ok" if not problems else f"FAIL {problems}"))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
