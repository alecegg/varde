"""Normalize compiler call sites, sample disjoint repo splits, and freeze hashes."""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter, defaultdict, deque
from collections.abc import Iterable, Mapping
from pathlib import Path

from audit.records import GROUND_TRUTH_SENTINELS, validate_record

CALL_CLASSES = (
    "same_file",
    "imported",
    "member",
    "constructor",
    "higher_order",
    "dynamic",
)
GENERATED_SUFFIXES = (".generated.cs", ".g.cs")
GENERATED_PARTS = {"gen", "generated", "obj", "bin"}
VENDORED_PARTS = {
    "third_party",
    "thirdparty",
    "third-party",
    "vendor",
    "vendored",
    "external",
    "extern",
    "node_modules",
    "subprojects",
}
TEST_PARTS = {"test", "tests", "testing", "spec", "specs"}


def export_tool_output(
    rows: Iterable[Mapping[str, object]], *, repo: str, language: str
) -> list[dict[str, object]]:
    """Map normalized compiler rows to the shared call-site schema."""
    if language not in {"java", "csharp"}:
        raise ValueError(f"unsupported language: {language}")
    records = []
    for row in rows:
        call_class = _call_class(row)
        target = _optional_text(row.get("target"))
        target_kind = row.get("target_kind")
        if target_kind == "dynamic" or call_class in {"dynamic", "higher_order"}:
            ground_truth = "unknown"
        elif target_kind == "external":
            ground_truth = "external"
        elif target is None:
            ground_truth = "unknown"
        else:
            ground_truth = target
        record = {
            "repo": repo,
            "language": language,
            "file": _required_text(row, "file"),
            "line": _positive_int(row, "line"),
            "call_name": _required_text(row, "call_name"),
            "call_class": call_class,
            "ground_truth": ground_truth,
            "measured_edge": _optional_text(row.get("measured_edge")),
            "measured_status": str(row.get("measured_status", "unresolved")),
            "truth_source": _required_text(row, "truth_source"),
            "function_id": _optional_text(row.get("caller")),
            "module": _optional_text(row.get("module")),
            "ground_truth_module": _optional_text(row.get("target_module")),
            "measured_module": None,
        }
        validate_record(record)
        records.append(record)
    return records


def sample_by_role(
    records: Iterable[Mapping[str, object]],
    repo_roles: Mapping[str, str],
    *,
    seed: int,
    size: int = 300,
) -> tuple[dict[str, list[dict[str, object]]], dict[str, dict[str, dict[str, int]]]]:
    """Select equal per-class dev/test samples from declared disjoint repo roles.

    Returns the samples and, per split and class, how many sites were available
    and selected, so a shortfall is reported instead of padded away.
    """
    if size < len(CALL_CLASSES) or size % len(CALL_CLASSES):
        raise ValueError("sample size must divide evenly across call classes")
    role_repos = {
        role: {repo for repo, value in repo_roles.items() if value == role}
        for role in ("dev", "test-only")
    }
    if len(role_repos["dev"]) < 2 or len(role_repos["test-only"]) < 3:
        raise ValueError("each language needs two dev and three test-only repositories")
    grouped: dict[str, dict[str, list[dict[str, object]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    unique_sites: set[tuple[str, str, int, str]] = set()
    for raw in records:
        record = dict(raw)
        validate_record(record)
        role = repo_roles.get(str(record["repo"]))
        path = str(record["file"])
        if role not in role_repos or _is_vendored(path) or _is_generated(path):
            continue
        key = _site_key(record)
        if key in unique_sites:
            continue
        unique_sites.add(key)
        grouped[role][str(record["call_class"])].append(record)
    quota = size // len(CALL_CLASSES)
    samples: dict[str, list[dict[str, object]]] = {"dev": [], "test": []}
    coverage: dict[str, dict[str, dict[str, int]]] = {"dev": {}, "test": {}}
    for role, split in (("dev", "dev"), ("test-only", "test")):
        rng = random.Random(f"{seed}:{role}")  # noqa: S311 - Reproducible benchmark sampling is not cryptographic.
        pools: dict[str, list[deque[dict[str, object]]]] = {}
        available: dict[str, int] = {}
        for call_class in CALL_CLASSES:
            candidates = list(grouped[role][call_class])
            rng.shuffle(candidates)
            candidates.sort(key=lambda row: _is_test_path(str(row["file"])))
            pools[call_class] = _class_pools(call_class, candidates)
            available[call_class] = sum(len(pool) for pool in pools[call_class])
        selected, taken = _select_sites(
            pools,
            order=sorted(
                CALL_CLASSES,
                key=lambda value: (available[value], CALL_CLASSES.index(value)),
            ),
            quota=quota,
            repo_cap=int(size * 0.40),
            test_path_cap=int(size * 0.25),
        )
        _fill_from_surplus(
            pools,
            selected,
            taken,
            size=size,
            repo_cap=int(size * 0.40),
            test_path_cap=int(size * 0.25),
        )
        for call_class in CALL_CLASSES:
            samples[split].extend(selected[call_class])
            coverage[split][call_class] = {
                "available": available[call_class],
                "selected": len(selected[call_class]),
                "in_repo": sum(1 for row in selected[call_class] if _is_in_repo(row)),
                "quota": quota,
            }
        samples[split].sort(
            key=lambda row: (
                str(row["repo"]),
                str(row["file"]),
                int(row["line"]),
                str(row["call_class"]),
            )
        )
    return samples, coverage


def write_jsonl(path: Path, records: Iterable[Mapping[str, object]]) -> str:
    """Write canonical JSONL and return the SHA-256 digest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        for record in records
    ).encode()
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def write_manifest(
    path: Path,
    entries: Mapping[str, str],
    coverage: Mapping[str, object],
    quota: int,
) -> None:
    """Write restricted-file digests with coverage and per-class shortfalls."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "files": dict(sorted(entries.items())),
        "quota": quota,
        "coverage": coverage,
        "class_shortfalls": _class_shortfalls(coverage),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _class_shortfalls(coverage: Mapping[str, object]) -> dict[str, object]:
    """Report each class below its quota as actual versus target, for weighting."""
    shortfalls: dict[str, object] = {}
    for language, splits in coverage.items():
        per_split: dict[str, object] = {}
        for split, classes in splits.items():
            below = {
                call_class: {"actual": entry["selected"], "target": entry["quota"]}
                for call_class, entry in sorted(classes.items())
                if entry["selected"] < entry["quota"]
            }
            if below:
                per_split[split] = below
        shortfalls[language] = per_split
    return shortfalls


def verify_manifest(path: Path, restricted_dir: Path) -> bool:
    """Verify only file hashes from the restricted set manifest."""
    entries = json.loads(path.read_text())["files"]
    return all(
        hashlib.sha256((restricted_dir / name).read_bytes()).hexdigest() == digest
        for name, digest in entries.items()
    )


def verification_stub(record: Mapping[str, object]) -> dict[str, object]:
    """Create two independent human-review slots for a compiler-unresolved site."""
    if record["ground_truth"] != "unknown":
        raise ValueError("verification stubs are only for unknown ground truth")
    return {
        "site": {
            "repo": record["repo"],
            "file": record["file"],
            "line": record["line"],
            "call_name": record.get("call_name"),
            "call_class": record["call_class"],
            "function_id": record["function_id"],
        },
        "reviewers": [
            {"id": "reviewer_a", "target": None},
            {"id": "reviewer_b", "target": None},
        ],
        "agreement": None,
        "status": "pending_human_verification",
    }


def _call_class(row: Mapping[str, object]) -> str:
    value = row.get("call_class")
    if value not in CALL_CLASSES:
        raise ValueError(f"invalid call class: {value}")
    return str(value)


def _select_sites(
    pools: dict[str, list[deque[dict[str, object]]]],
    *,
    order: list[str],
    quota: int,
    repo_cap: int,
    test_path_cap: int,
) -> tuple[dict[str, list[dict[str, object]]], dict[str, list[int]]]:
    """Take quota sites per class where the corpus has them; never pad a class.

    Classes are filled one at a time, scarcest first. Filling them together would
    let an abundant class consume a repository's capacity before a scarce class
    reaches its quota, which would under-sample a class the corpus can supply.
    Returns the selected sites and, per class, how many came from each pool, so
    the surplus pass can keep balancing a class' pools.
    """
    selected: dict[str, list[dict[str, object]]] = {
        call_class: [] for call_class in CALL_CLASSES
    }
    taken = {call_class: [0] * len(pools[call_class]) for call_class in CALL_CLASSES}
    repo_counts: Counter[str] = Counter()
    test_path_count = 0
    for call_class in order:
        for _ in range(quota):
            choice = _take_candidate(
                pools[call_class],
                taken[call_class],
                repo_counts,
                test_path_count,
                repo_cap,
                test_path_cap,
            )
            if choice is None:
                break
            selected[call_class].append(choice)
            repo_counts[str(choice["repo"])] += 1
            test_path_count += _is_test_path(str(choice["file"]))
    return selected, taken


def _fill_from_surplus(
    pools: dict[str, list[deque[dict[str, object]]]],
    selected: dict[str, list[dict[str, object]]],
    taken: dict[str, list[int]],
    *,
    size: int,
    repo_cap: int,
    test_path_cap: int,
) -> None:
    """Fill the remaining slots from the classes that still have supply.

    One site at a time into the class with the fewest sites so far (larger supply
    breaks the tie), so the extras spread over the classes that can supply them.
    A class whose pool is exhausted after the quota pass contributes nothing here,
    so a scarce class keeps its honest count and the shortfall stays visible.
    """
    total = sum(len(rows) for rows in selected.values())
    repo_counts = Counter(
        str(row["repo"]) for rows in selected.values() for row in rows
    )
    test_path_count = sum(
        _is_test_path(str(row["file"])) for rows in selected.values() for row in rows
    )
    blocked: set[str] = set()
    while total < size:
        supply = {
            call_class: sum(len(pool) for pool in pools[call_class])
            for call_class in CALL_CLASSES
        }
        candidates = [
            call_class
            for call_class in CALL_CLASSES
            if supply[call_class] and call_class not in blocked
        ]
        if not candidates:
            break
        call_class = min(
            candidates, key=lambda name: (len(selected[name]), -supply[name])
        )
        choice = _take_candidate(
            pools[call_class],
            taken[call_class],
            repo_counts,
            test_path_count,
            repo_cap,
            test_path_cap,
        )
        if choice is None:
            blocked.add(call_class)
            continue
        selected[call_class].append(choice)
        repo_counts[str(choice["repo"])] += 1
        test_path_count += _is_test_path(str(choice["file"]))
        total += 1


def _class_pools(
    call_class: str, candidates: list[dict[str, object]]
) -> list[deque[dict[str, object]]]:
    """Split the member class by target location so both halves are sampled."""
    if call_class != "member":
        return [deque(candidates)]
    return [
        deque([row for row in candidates if _is_in_repo(row)]),
        deque([row for row in candidates if not _is_in_repo(row)]),
    ]


def _take_candidate(
    pools: list[deque[dict[str, object]]],
    taken: list[int],
    repo_counts: Counter[str],
    test_path_count: int,
    repo_cap: int,
    test_path_cap: int,
) -> dict[str, object] | None:
    """Take from the least-used pool, preferring the least-used repository.

    Preferring the least-used repository spreads every class over the split's
    repositories, so one repository reaching its cap cannot stop another class
    from reaching its quota.
    """
    for index in sorted(range(len(pools)), key=lambda value: (taken[value], value)):
        pool = pools[index]
        chosen = -1
        for position, candidate in enumerate(pool):
            repo = str(candidate["repo"])
            if repo_counts[repo] >= repo_cap:
                continue
            if (
                _is_test_path(str(candidate["file"]))
                and test_path_count >= test_path_cap
            ):
                continue
            if chosen < 0 or repo_counts[repo] < repo_counts[str(pool[chosen]["repo"])]:
                chosen = position
                if not repo_counts[repo]:
                    break
        if chosen < 0:
            continue
        candidate = pool[chosen]
        del pool[chosen]
        taken[index] += 1
        return candidate
    return None


def _is_in_repo(record: Mapping[str, object]) -> bool:
    return record["ground_truth"] not in GROUND_TRUTH_SENTINELS


def _site_key(record: Mapping[str, object]) -> tuple[str, str, int, str]:
    return (
        str(record["repo"]),
        str(record["file"]),
        int(record["line"]),
        str(record.get("call_name") or ""),
    )


def _is_generated(path: str) -> bool:
    lowered = path.lower()
    return lowered.endswith(GENERATED_SUFFIXES) or any(
        part.lower() in GENERATED_PARTS for part in path.split("/")
    )


def _is_vendored(path: str) -> bool:
    return any(part.lower() in VENDORED_PARTS for part in path.split("/"))


def _is_test_path(path: str) -> bool:
    return any(part.lower() in TEST_PARTS for part in path.split("/"))


def _required_text(row: Mapping[str, object], key: str) -> str:
    return _optional_text(row.get(key)) or _raise(f"missing {key}")


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("expected text value")
    return value or None


def _positive_int(row: Mapping[str, object], key: str) -> int:
    value = row.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{key} must be a positive integer")
    return value


def _raise(message: str) -> object:
    raise ValueError(message)
