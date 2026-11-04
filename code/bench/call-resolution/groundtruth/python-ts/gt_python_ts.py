"""Shared schema, sampling, and manifest helpers for Python/TS call audits."""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

from audit.records import CALL_CLASSES, validate_record

Record = dict[str, object]
Repo = Mapping[str, object]
ToolRunner = Callable[[Repo], Iterable[Mapping[str, object]]]


def export_repository(
    repo: Repo, language: str, tool_runner: ToolRunner
) -> list[Record]:
    """Convert tool sites to the shared labeled-record schema."""
    output = []
    for site in tool_runner(repo):
        record = record_from_site(repo, language, site)
        validate_record(record)
        output.append(record)
    return output


def record_from_site(repo: Repo, language: str, site: Mapping[str, object]) -> Record:
    target = site.get("target_id")
    if isinstance(target, str) and target:
        ground_truth = target
    elif site.get("external") is True:
        ground_truth = "external"
    else:
        ground_truth = "unknown"

    record: Record = {
        "repo": _required_text(repo, "repo"),
        "language": language,
        "file": _required_text(site, "file"),
        "line": site.get("line"),
        "call_name": _required_text(site, "call_name"),
        "call_class": _required_text(site, "call_class"),
        "ground_truth": ground_truth,
        "measured_edge": None,
        "measured_status": "unresolved",
        "truth_source": _required_text(site, "truth_source"),
        "function_id": _optional_text(site.get("function_id")),
        "module": _optional_text(site.get("module")),
        "ground_truth_module": _optional_text(site.get("target_module")),
        "measured_module": None,
    }
    return record


def sample_records(
    records: Iterable[Mapping[str, object]], seed: int, n_per_language: int = 300
) -> dict[str, dict[str, list[Record]]]:
    """Return repository-disjoint, class-stratified dev and test samples."""
    return stratified_samples(records, seed, n_per_language)[0]


def stratified_samples(
    records: Iterable[Mapping[str, object]], seed: int, n_per_language: int = 300
) -> tuple[dict[str, dict[str, list[Record]]], dict[str, object]]:
    """Sample each language and report composition, balance, and shortfalls.

    Repositories are partitioned into disjoint dev and test halves in the same
    deterministic order as the audit harness. Within a split, every call class
    receives an even quota drawn round-robin across repositories, so no single
    repository dominates. Classes that cannot reach their quota are reported
    rather than padded, and the remainder of the split is filled from the real
    surplus so each split still holds ``n_per_language`` sites.
    """
    if n_per_language < len(CALL_CLASSES):
        raise ValueError("n_per_language must cover every call class")
    grouped: dict[str, dict[str, list[Record]]] = defaultdict(lambda: defaultdict(list))
    for record in _unique_records(records):
        grouped[str(record["language"])][str(record["repo"])].append(dict(record))

    samples: dict[str, dict[str, list[Record]]] = {}
    notes: dict[str, object] = {}
    for language in sorted(grouped):
        repositories = sorted(grouped[language])
        if len(repositories) < 2:
            raise ValueError(f"{language} requires two repositories for disjoint sets")
        order = list(repositories)
        random.Random(f"{seed}:{language}").shuffle(order)  # noqa: S311 - Reproducible dataset partitioning is not cryptographic.
        midpoint = len(order) // 2
        samples[language] = {}
        language_notes: dict[str, object] = {}
        for split, names in (("dev", order[:midpoint]), ("test", order[midpoint:])):
            selected, note = _select_split(
                grouped[language], names, seed, language, split, n_per_language
            )
            samples[language][split] = selected
            language_notes[split] = note
        notes[language] = language_notes
    return samples, notes


def _select_split(
    repo_records: Mapping[str, list[Record]],
    names: Iterable[str],
    seed: int,
    language: str,
    split: str,
    size: int,
) -> tuple[list[Record], dict[str, object]]:
    order = sorted(names)
    random.Random(f"{seed}:{language}:{split}:repos").shuffle(order)  # noqa: S311 - Reproducible dataset partitioning is not cryptographic.
    quotas = _quotas(size)
    selected: list[Record] = []
    class_counts: dict[str, int] = {}
    shortfalls: dict[str, int] = {}
    leftover: list[Record] = []
    for call_class in CALL_CLASSES:
        buckets = {
            repo: sorted(
                (
                    record
                    for record in repo_records[repo]
                    if record["call_class"] == call_class
                ),
                key=_record_key,
            )
            for repo in order
        }
        picked = _round_robin(buckets, order, quotas[call_class])
        class_counts[call_class] = len(picked)
        if len(picked) < quotas[call_class]:
            shortfalls[call_class] = len(picked)
        selected.extend(picked)
        leftover.extend(_leftover(buckets, order))
    if len(selected) < size:
        selected.extend(sorted(leftover, key=_record_key)[: size - len(selected)])
    selected.sort(key=_record_key)
    note = {
        "sites": len(selected),
        "class_counts": dict(sorted(class_counts.items())),
        "shortfalls": dict(sorted(shortfalls.items())),
        "repo_counts": dict(
            sorted(Counter(str(record["repo"]) for record in selected).items())
        ),
        "test_path_sites": sum(
            1 for record in selected if _is_test_path(str(record["file"]))
        ),
    }
    return selected, note


def _round_robin(
    buckets: dict[str, list[Record]], order: list[str], quota: int
) -> list[Record]:
    picked: list[Record] = []
    while len(picked) < quota:
        before = len(picked)
        for repo in order:
            if len(picked) >= quota:
                break
            if buckets[repo]:
                picked.append(buckets[repo].pop(0))
        if len(picked) == before:
            break
    return picked


def _leftover(buckets: dict[str, list[Record]], order: list[str]) -> list[Record]:
    remaining = [record for repo in order for record in buckets[repo]]
    return sorted(remaining, key=_record_key)


def _unique_records(
    records: Iterable[Mapping[str, object]],
) -> list[Record]:
    """Keep one record per (repo, file, line, call_name) identity."""
    unique: dict[tuple[object, ...], Record] = {}
    for record in records:
        call_name = record.get("call_name")
        if isinstance(call_name, str) and call_name:
            identity = (record["repo"], record["file"], record["line"], call_name)
        else:
            identity = (
                record["repo"],
                record["file"],
                record["line"],
                record["call_class"],
            )
        unique.setdefault(identity, dict(record))
    return list(unique.values())


def _quotas(size: int) -> dict[str, int]:
    base, remainder = divmod(size, len(CALL_CLASSES))
    return {
        call_class: base + (index < remainder)
        for index, call_class in enumerate(CALL_CLASSES)
    }


def _record_key(record: Mapping[str, object]) -> tuple[str, str, int, str, str]:
    return (
        str(record["repo"]),
        str(record["file"]),
        int(record["line"]),
        str(record.get("call_name") or ""),
        str(record["call_class"]),
    )


def _is_test_path(relative: str) -> bool:
    parts = [part.lower() for part in relative.split("/")]
    if {"test", "tests", "__tests__", "spec", "specs", "testing"} & set(parts[:-1]):
        return True
    name = parts[-1]
    return name.startswith("test_") or ".test." in name or ".spec." in name


def review_stub(record: Mapping[str, object]) -> dict[str, object]:
    """Create independent, unfilled reviewer slots for an unresolved site."""
    identity = {
        field: record[field]
        for field in ("repo", "language", "file", "line", "call_name", "call_class")
    }
    return {
        **identity,
        "tool_ground_truth": record.get("ground_truth", "unknown"),
        "tool_truth_source": record.get("truth_source", ""),
        "reviewer_1": {
            "reviewer": "independent-reviewer-1",
            "target": None,
            "confidence": None,
            "rationale": None,
        },
        "reviewer_2": {
            "reviewer": "independent-reviewer-2",
            "target": None,
            "confidence": None,
            "rationale": None,
        },
    }


def review_stubs(records: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    """Return stubs for unresolved higher-order and dynamic call sites."""
    return [
        review_stub(record)
        for record in records
        if record.get("ground_truth") == "unknown"
        and record.get("call_class") in {"higher_order", "dynamic"}
    ]


def write_jsonl(path: Path, records: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, sort_keys=True, ensure_ascii=False))
            stream.write("\n")


def write_test_manifest(
    manifest_path: Path,
    restricted_root: Path,
    test_files: Mapping[str, Path],
    record_counts: Mapping[str, int] | None = None,
) -> None:
    """Write SHA-256 entries without copying restricted labels into the repo."""
    entries: dict[str, dict[str, object]] = {}
    for language, path in sorted(test_files.items()):
        if path.parent.resolve() != restricted_root.resolve():
            raise ValueError("frozen set file must be directly under restricted root")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entry: dict[str, object] = {
            "file": f"notes/restricted/call-audit/python-ts/{path.name}",
            "sha256": digest,
        }
        if record_counts and language in record_counts:
            entry["records"] = record_counts[language]
        entries[language] = entry

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps({"format_version": 1, "files": entries}, indent=2) + "\n",
        encoding="utf-8",
    )


def verify_test_manifest(manifest_path: Path, restricted_root: Path) -> bool:
    """Verify only frozen-file bytes; never parse their labels."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = manifest["files"]
        if set(entries) != {"python", "typescript"}:
            return False
        for entry in entries.values():
            file_name = Path(entry["file"])
            if file_name.parts[:4] != (
                "notes",
                "restricted",
                "call-audit",
                "python-ts",
            ):
                return False
            path = restricted_root / file_name.name
            if not path.is_file():
                return False
            if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
                return False
    except Exception as error:
        if isinstance(error, (KeyError, OSError, TypeError, ValueError)):
            return False
        raise
    else:
        return True


def _required_text(record: Mapping[str, object], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) else None
