"""Create deterministic C++ dev and held-out samples from role-pinned repos.

Sampling keeps the six call classes balanced at ``size / 6`` sites each and
enforces three dataset rules: a ``(repo, file, line, call_name)`` call site
appears at most once, vendored and third-party sources are ignored, and
test-path call sites fill at most a quarter of a split. A class that cannot
meet its quota raises instead of being padded from another class.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import tomllib
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from audit.records import validate_record

CLASSES = ("same_file", "imported", "member", "constructor", "higher_order", "dynamic")
TEST_PATH_PARTS = {
    "benchmark",
    "benchmarks",
    "fuzz",
    "fuzzing",
    "test",
    "testing",
    "tests",
    "unit_tests",
    "unittest",
}
VENDORED_PATH_PARTS = {
    "_deps",
    "deps",
    "doctest",
    "external",
    "gtest",
    "googletest",
    "third_party",
    "third-party",
    "thirdparty",
    "vendor",
    "vendors",
}
TEST_PATH_SHARE = 0.25
MAX_REPO_SHARE = 0.40
MAX_REPO_CLASS_SHARE = 0.50
SAMPLE_SIZE = 300


@dataclass(frozen=True)
class DatasetPaths:
    dev_sites: Path
    dev_stubs: Path
    test_sites: Path
    test_stubs: Path
    manifest: Path


def _is_test_path(file: str) -> bool:
    path = Path(file)
    if any(part.lower() in TEST_PATH_PARTS for part in path.parts):
        return True
    name = path.name.lower()
    stem = path.stem.lower()
    return (
        name.startswith(("test_", "test-"))
        or stem.startswith(("test_", "test-"))
        or stem.endswith(("_test", "-test", "_unittest", ".test"))
    )


def _is_vendored_path(file: str) -> bool:
    return any(part.lower() in VENDORED_PATH_PARTS for part in Path(file).parts)


def _unique_records(
    records: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Keep one record per call site and drop vendored sources."""
    grouped: dict[tuple[str, str, int, str], list[dict[str, object]]] = defaultdict(
        list
    )
    for record in records:
        item = dict(record)
        validate_record(item)
        call_name = item.get("call_name")
        if not isinstance(call_name, str) or not call_name:
            raise ValueError("call-site record needs a non-empty call_name")
        if _is_vendored_path(str(item["file"])):
            continue
        grouped[
            (str(item["repo"]), str(item["file"]), int(item["line"]), call_name)
        ].append(item)

    unique = []
    for key, candidates in grouped.items():
        known_targets = {
            str(item["ground_truth"])
            for item in candidates
            if item["ground_truth"] not in {"unknown", "external"}
        }
        if len(known_targets) > 1:
            raise ValueError(f"conflicting targets at call site {key}")
        call_classes = {str(item["call_class"]) for item in candidates}
        if len(call_classes) > 1:
            raise ValueError(f"conflicting call classes at call site {key}")
        unique.append(
            min(
                candidates,
                key=lambda item: (
                    item["ground_truth"] == "unknown",
                    item["ground_truth"] == "external",
                    str(item["truth_source"]),
                    str(item["call_class"]),
                ),
            )
        )
    return unique


def _quotas(size: int) -> dict[str, int]:
    base, remainder = divmod(size, len(CLASSES))
    return {
        call_class: base + (1 if index < remainder else 0)
        for index, call_class in enumerate(CLASSES)
    }


def _interleave_by_repo(
    rows: Iterable[Mapping[str, object]],
    usage: Mapping[str, int] | None = None,
) -> list[dict[str, object]]:
    """Round-robin rows across repos, least-used repository first."""
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["repo"])].append(dict(row))
    repos = sorted(grouped, key=lambda repo: ((usage or {}).get(repo, 0), repo))
    order: list[dict[str, object]] = []
    depth = max((len(grouped[repo]) for repo in repos), default=0)
    for index in range(depth):
        order.extend(
            grouped[repo][index] for repo in repos if index < len(grouped[repo])
        )
    return order


@dataclass
class _Allocation:
    repo_cap: int
    test_budget: int
    test_used: int = 0
    repo_totals: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    repo_class_totals: dict[tuple[str, str], int] = field(
        default_factory=lambda: defaultdict(int)
    )


def _cap_aware_class(
    candidates: list[dict[str, object]],
    quota: int,
    *,
    class_cap: int,
    call_class: str,
    allocation: _Allocation,
) -> tuple[list[dict[str, object]], bool]:
    """Fill one class up to ``quota`` while honouring the repo and test-path caps."""
    production = _interleave_by_repo(
        (row for row in candidates if not _is_test_path(str(row["file"]))),
        allocation.repo_totals,
    )
    test_sites = _interleave_by_repo(
        (row for row in candidates if _is_test_path(str(row["file"]))),
        allocation.repo_totals,
    )
    taken: list[dict[str, object]] = []
    blocked_by_test_cap = False
    for pool, is_test in ((production, False), (test_sites, True)):
        for row in pool:
            if len(taken) >= quota:
                break
            repo = str(row["repo"])
            if allocation.repo_class_totals[(repo, call_class)] >= class_cap:
                continue
            if allocation.repo_totals[repo] >= allocation.repo_cap:
                continue
            if is_test and allocation.test_used >= allocation.test_budget:
                blocked_by_test_cap = True
                continue
            taken.append(row)
            allocation.repo_totals[repo] += 1
            allocation.repo_class_totals[(repo, call_class)] += 1
            allocation.test_used += 1 if is_test else 0
        if len(taken) >= quota:
            break
    return taken, blocked_by_test_cap


def stratified_sample(
    records: Iterable[Mapping[str, object]],
    roles: Mapping[str, str],
    *,
    seed: int = 26017,
    size: int = SAMPLE_SIZE,
) -> dict[str, list[dict[str, object]]]:
    """Select ``size`` dev and test-only records, balanced across call classes."""
    grouped: dict[str, dict[str, list[dict[str, object]]]] = {
        "dev": defaultdict(list),
        "test": defaultdict(list),
    }
    for item in _unique_records(records):
        repo = str(item["repo"])
        role = roles.get(repo)
        if role not in {"dev", "test-only"}:
            raise ValueError(f"repo has no supported role: {repo}")
        grouped["test" if role == "test-only" else "dev"][
            str(item["call_class"])
        ].append(item)

    quotas = _quotas(size)
    repo_cap = int(size * MAX_REPO_SHARE)
    max_test_sites = int(size * TEST_PATH_SHARE)
    selected: dict[str, list[dict[str, object]]] = {}
    for split, by_class in grouped.items():
        candidates_by_class = {
            call_class: sorted(
                by_class[call_class],
                key=lambda row: (str(row["repo"]), str(row["file"]), int(row["line"])),
            )
            for call_class in CLASSES
        }
        shortfalls = [
            f"{split} {call_class} shortfall: "
            f"{len(candidates_by_class[call_class])}/{quotas[call_class]} unique sites"
            for call_class in CLASSES
            if len(candidates_by_class[call_class]) < quotas[call_class]
        ]
        if shortfalls:
            available = sum(map(len, candidates_by_class.values()))
            raise ValueError(
                f"{'; '.join(shortfalls)} (available {available}, needs {size})"
            )
        rng = random.Random(f"{seed}:cpp:{split}")  # noqa: S311 - Reproducible benchmark sampling is not cryptographic.
        rows: list[dict[str, object]] = []
        allocation = _Allocation(repo_cap=repo_cap, test_budget=max_test_sites)
        for call_class in CLASSES:
            candidates = candidates_by_class[call_class]
            rng.shuffle(candidates)
            class_cap = max(1, int(quotas[call_class] * MAX_REPO_CLASS_SHARE))
            taken, test_blocked = _cap_aware_class(
                candidates,
                quotas[call_class],
                class_cap=class_cap,
                call_class=call_class,
                allocation=allocation,
            )
            rows.extend(taken)
            if len(taken) < quotas[call_class]:
                if test_blocked:
                    raise ValueError(
                        f"{split} test-path cap exceeded: "
                        f"{allocation.test_used}/{max_test_sites} "
                        f"while filling {call_class}"
                    )
                raise ValueError(
                    f"{split} {call_class} shortfall under repo caps: "
                    f"{len(taken)}/{quotas[call_class]} sites "
                    f"(repo cap {repo_cap}, class cap {class_cap})"
                )
        if allocation.test_used > max_test_sites:
            raise ValueError(
                f"{split} test-path cap exceeded: "
                f"{allocation.test_used}/{max_test_sites}"
            )
        selected[split] = sorted(
            rows,
            key=lambda row: (
                str(row["repo"]),
                str(row["file"]),
                int(row["line"]),
                str(row["call_class"]),
            ),
        )
        keys = [
            (row["repo"], row["file"], row["line"], row["call_name"])
            for row in selected[split]
        ]
        if len(keys) != len(set(keys)):
            raise ValueError(f"{split} sample contains duplicate call-site keys")
    return selected


def unknown_count(rows: Iterable[Mapping[str, object]]) -> int:
    return sum(row.get("ground_truth") == "unknown" for row in rows)


def _class_counts(rows: Iterable[Mapping[str, object]]) -> dict[str, int]:
    counts = dict.fromkeys(CLASSES, 0)
    for row in rows:
        counts[str(row["call_class"])] += 1
    return counts


def _repo_class_breakdown(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Records and unknown records per repository and call class."""
    grouped: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"records": 0, "unknown_records": 0}
    )
    for row in rows:
        counts = grouped[(str(row["repo"]), str(row["call_class"]))]
        counts["records"] += 1
        counts["unknown_records"] += row.get("ground_truth") == "unknown"
    return [
        {
            "repo": repo,
            "call_class": call_class,
            "records": counts["records"],
            "unknown_records": counts["unknown_records"],
        }
        for (repo, call_class), counts in sorted(grouped.items())
    ]


def _split_summary(rows: list[dict[str, object]]) -> dict[str, object]:
    return {
        "records": len(rows),
        "unknown_records": unknown_count(rows),
        "class_counts": _class_counts(rows),
        "repo_counts": _repo_counts(rows),
        "unknown_by_class": _unknown_by(rows, "call_class"),
        "unknown_by_repo": _unknown_by(rows, "repo"),
        "repo_class_breakdown": _repo_class_breakdown(rows),
        "test_path_sites": sum(_is_test_path(str(row["file"])) for row in rows),
        "repos": sorted({str(row["repo"]) for row in rows}),
    }


def _repo_counts(rows: Iterable[Mapping[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[str(row["repo"])] += 1
    return dict(sorted(counts.items()))


def _unknown_by(rows: Iterable[Mapping[str, object]], field: str) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        if row.get("ground_truth") == "unknown":
            counts[str(row[field])] += 1
    return dict(sorted(counts.items()))


def manifest_file(
    relative_path: str, path: Path, records: int, unknown_records: int
) -> dict[str, object]:
    """Describe one written file so a reader can verify its hash and counts."""
    payload = path.read_bytes()
    return {
        "path": relative_path,
        "records": records,
        "unknown_records": unknown_records,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
    }


def write_jsonl(path: Path, rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, sort_keys=True) + "\n")


def read_jsonl(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def stubs_for_unknown(
    records: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Return one reviewer stub for each unknown sampled record."""
    from .review import stub

    return [
        stub(record) for record in records if record.get("ground_truth") == "unknown"
    ]


def _checked_stubs(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    unknown = unknown_count(rows)
    stubs = stubs_for_unknown(rows)
    if len(stubs) != unknown:
        raise ValueError(f"stub count {len(stubs)} does not match {unknown} unknowns")
    return stubs


def write_dataset(
    records: Iterable[Mapping[str, object]],
    roles: Mapping[str, str],
    paths: DatasetPaths,
    *,
    manifest_prefix: str,
    seed: int = 26017,
    size: int = SAMPLE_SIZE,
) -> dict[str, object]:
    """Write both splits, their reviewer stubs, and the frozen-set manifest."""
    selected = stratified_sample(records, roles, seed=seed, size=size)
    dev, frozen = selected["dev"], selected["test"]
    dev_stubs = _checked_stubs(dev)
    frozen_stubs = _checked_stubs(frozen)
    write_jsonl(paths.dev_sites, dev)
    write_jsonl(paths.dev_stubs, dev_stubs)
    write_jsonl(paths.test_sites, frozen)
    write_jsonl(paths.test_stubs, frozen_stubs)
    manifest = {
        "language": "cpp",
        "seed": seed,
        "sample_size": size,
        "records": len(frozen),
        "unknown_records": unknown_count(frozen),
        "partially_validated": any(
            str(row["truth_source"]).startswith("source-only")
            for split in selected.values()
            for row in split
        ),
        "dev": _split_summary(dev),
        "frozen": _split_summary(frozen),
        "files": [
            manifest_file(
                f"{manifest_prefix}/test-sites.jsonl",
                paths.test_sites,
                len(frozen),
                unknown_count(frozen),
            ),
            manifest_file(
                f"{manifest_prefix}/review-stubs.jsonl",
                paths.test_stubs,
                len(frozen_stubs),
                0,
            ),
        ],
    }
    paths.manifest.parent.mkdir(parents=True, exist_ok=True)
    paths.manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def repo_roles(manifest_path: Path) -> dict[str, str]:
    """Read ``repo``/``role`` pairs from a pinned-repository manifest."""
    payload = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    return {str(entry["repo"]): str(entry["role"]) for entry in payload["repos"]}


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--repos", type=Path, required=True)
    parser.add_argument("--dev-sites", type=Path, required=True)
    parser.add_argument("--dev-stubs", type=Path, required=True)
    parser.add_argument("--test-sites", type=Path, required=True)
    parser.add_argument("--test-stubs", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-prefix", required=True)
    parser.add_argument("--size", type=int, default=SAMPLE_SIZE)
    parser.add_argument("--seed", type=int, default=26017)
    args = parser.parse_args(list(argv) if argv is not None else None)
    manifest = write_dataset(
        read_jsonl(args.records),
        repo_roles(args.repos),
        DatasetPaths(
            dev_sites=args.dev_sites,
            dev_stubs=args.dev_stubs,
            test_sites=args.test_sites,
            test_stubs=args.test_stubs,
            manifest=args.manifest,
        ),
        manifest_prefix=args.manifest_prefix,
        seed=args.seed,
        size=args.size,
    )
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
