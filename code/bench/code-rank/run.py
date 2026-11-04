from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path
from tempfile import gettempdir
from typing import Any

from metrics import mean, ndcg_at_k, tokens_to_first_hit

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
REPOS = {
    "varde": REPO_ROOT,
    "openspec": Path.home() / "source/reference-repos/OpenSpec",
    "agent-deck": Path.home() / "source/reference-repos/agent-deck",
}
TOKEN_MISS_CAP = 32_000
BenchmarkRow = tuple[dict[str, Any], float, int | None, int | None]
STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "and",
    "are",
    "because",
    "before",
    "between",
    "does",
    "from",
    "give",
    "have",
    "how",
    "into",
    "is",
    "its",
    "keep",
    "make",
    "more",
    "what",
    "when",
    "where",
    "which",
    "with",
    "work",
    "this",
    "that",
    "their",
    "they",
    "them",
    "then",
    "there",
    "these",
    "those",
    "will",
    "would",
    "your",
    "you",
}


def benchmark_varde_copy() -> Path:
    """Use tracked files only, excluding nested worktrees and virtualenvs."""
    target = Path(gettempdir()) / "varde-code-rank" / "varde"
    tracked = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, check=True
    ).stdout.split(b"\0")
    target.mkdir(parents=True, exist_ok=True)
    wanted = {Path(path.decode()) for path in tracked if path}
    for relative in wanted:
        source = REPO_ROOT / relative
        destination = target / relative
        try:
            if (
                not destination.exists()
                or source.stat().st_mtime_ns != destination.stat().st_mtime_ns
            ):
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
        except OSError:
            continue
    return target


def token_count(text: str) -> int:
    """Small deterministic whitespace token estimate, shared by both methods."""
    return max(1, len(re.findall(r"\w+|[^\w\s]", text)))


def run_context_pack(
    repo: Path, query: str, ranker: str
) -> tuple[list[str], str | None]:
    payload = json.dumps({"repoRoot": str(repo), "query": query, "rankingMode": ranker})
    proc = subprocess.run(
        ["uv", "run", "varde", "map", "context_pack", "--json", payload],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode:
        detail = proc.stderr + proc.stdout
        return [], "not_found" if "not_found" in detail else "error"
    try:
        result = json.loads(proc.stdout)
        return [
            item["path"]
            for item in result.get("data", {}).get("files", [])
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        ], None
    except json.JSONDecodeError, AttributeError:
        return [], "error"


def ensure_index(repo: Path) -> None:
    """Build the repo index once before issuing its retrieval queries."""
    proc = subprocess.run(
        ["uv", "run", "varde", "map", "build", "--repo-root", str(repo)],
        cwd=REPO_ROOT,
        check=False,
    )
    if proc.returncode:
        raise RuntimeError(f"could not build index for {repo}")


def grep_then_read(repo: Path, query: str) -> list[str]:
    words = list(
        dict.fromkeys(
            word.lower()
            for word in re.findall(r"[a-zA-Z][a-zA-Z0-9_]+", query)
            if len(word) >= 4 and word.lower() not in STOPWORDS
        )
    )
    hits: dict[str, int] = {}
    frequencies: list[tuple[int, str, list[str]]] = []
    for word in words:
        try:
            proc = subprocess.run(
                [
                    "rg",
                    "-l",
                    "-i",
                    "--fixed-strings",
                    "--glob",
                    "!.git/**",
                    word,
                    str(repo),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            continue
        paths = proc.stdout.splitlines()
        frequencies.append((len(paths), word, paths[:100]))
    for _, _, paths in sorted(frequencies)[:3]:
        for absolute in paths:
            try:
                path = Path(absolute).relative_to(repo).as_posix()
            except ValueError:
                continue
            hits[path] = hits.get(path, 0) + 1
    return sorted(hits, key=lambda path: (-hits[path], path))


def file_tokens(repo: Path, paths: set[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in paths:
        try:
            counts[path] = token_count(
                (repo / path).read_text(encoding="utf-8", errors="replace")
            )
        except OSError:
            counts[path] = 1
    return counts


def report_structural_zero_hit_recovery(
    queries: list[dict[str, Any]],
    rankers: tuple[str, ...],
    outputs_by_ranker: dict[str, dict[str, tuple[list[str], str | None]]],
) -> None:
    structural_outputs = outputs_by_ranker.get("structural", {})
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for query in queries:
        retrieved, outcome = structural_outputs.get(query["id"], ([], None))
        relevant = set(query["relevant_files"])
        if outcome == "not_found" or not relevant.intersection(retrieved):
            groups["all"].append(query)
            groups[f"repo:{query['repo']}"].append(query)
    print("structural zero-hit recovery (not_found or no relevant file in files)")
    for label, group in groups.items():
        for ranker in rankers:
            recovered = sum(
                bool(
                    set(query["relevant_files"]).intersection(
                        outputs_by_ranker[ranker][query["id"]][0]
                    )
                )
                for query in group
            )
            print(f"{label} {ranker}: {recovered}/{len(group)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate context_pack file retrieval")
    parser.add_argument(
        "--ranker",
        choices=("structural", "fallback", "both"),
        default="structural",
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="maximum number of queries (0 means all)"
    )
    parser.add_argument("--diagnostics", action="store_true")
    args = parser.parse_args()
    queries: list[dict[str, Any]] = json.loads((HERE / "data/queries.json").read_text())
    if args.limit:
        queries = queries[: args.limit]
    REPOS["varde"] = benchmark_varde_copy()
    for repo_name in dict.fromkeys(query["repo"] for query in queries):
        ensure_index(REPOS[repo_name])
    rankers = ("structural", "fallback") if args.ranker == "both" else (args.ranker,)
    outputs_by_ranker: dict[str, dict[str, tuple[list[str], str | None]]] = {}
    any_errors = False
    for ranker in rankers:
        rows: list[BenchmarkRow] = []
        errors = 0
        not_found = 0
        outputs_by_ranker[ranker] = {}
        for query in queries:
            repo = REPOS[query["repo"]]
            relevant = set(query["relevant_files"])
            retrieved, outcome = run_context_pack(repo, query["query"], ranker)
            outputs_by_ranker[ranker][query["id"]] = (retrieved, outcome)
            errors += outcome == "error"
            not_found += outcome == "not_found"
            grep = grep_then_read(repo, query["query"])
            tokens = file_tokens(repo, set(retrieved) | set(grep))
            rows.append(
                (
                    query,
                    ndcg_at_k(retrieved, relevant, 10),
                    tokens_to_first_hit(retrieved, relevant, tokens),
                    tokens_to_first_hit(grep, relevant, tokens),
                )
            )
            if (
                args.diagnostics
                and query["repo"] == "varde"
                and query["source"] == "commit"
            ):
                first_relevant = next(
                    (
                        (index + 1, path)
                        for index, path in enumerate(retrieved)
                        if path in relevant
                    ),
                    (None, None),
                )
                first_position = (
                    first_relevant[0] if first_relevant[0] is not None else "absent"
                )
                print(
                    f"diagnostic {ranker} {query['id']}: first relevant files "
                    "position="
                    f"{first_position} "
                    f"path={first_relevant[1]}"
                )
        any_errors |= errors > 0
        print(f"ranker: {ranker} ({len(queries)} queries)")
        print(f"errors: {errors}; not_found: {not_found}")

        groups: dict[str, list[BenchmarkRow]] = defaultdict(list)
        for row in rows:
            query = row[0]
            groups["all"].append(row)
            groups[f"repo:{query['repo']}"].append(row)
            groups[f"source:{query['source']}"].append(row)
        for label, group in groups.items():
            ndcg = mean([row[1] for row in group])
            retrieved_costs = [
                float(row[2] if row[2] is not None else TOKEN_MISS_CAP) for row in group
            ]
            baseline_costs = [
                float(row[3] if row[3] is not None else TOKEN_MISS_CAP) for row in group
            ]
            retrieved_mean = mean(retrieved_costs)
            baseline_mean = mean(baseline_costs)
            coverage = (baseline_mean / retrieved_mean) if retrieved_mean else 0.0
            retrieved_hits = sum(row[2] is not None for row in group)
            baseline_hits = sum(row[3] is not None for row in group)
            print(
                f"{label} ({len(group)} queries): NDCG@10 {ndcg:.4f}; "
                f"token coverage {coverage:.4f}x; "
                f"expected tokens {retrieved_mean:.1f} vs grep {baseline_mean:.1f}; "
                f"hits {retrieved_hits}/{len(group)} vs {baseline_hits}/{len(group)}"
            )
    if "structural" in outputs_by_ranker:
        report_structural_zero_hit_recovery(queries, rankers, outputs_by_ranker)
    return int(any_errors)


if __name__ == "__main__":
    raise SystemExit(main())
