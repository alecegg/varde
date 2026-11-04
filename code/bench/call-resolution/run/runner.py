"""Run one labeled call-resolution split against an edge-export adapter."""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import shutil
import signal
import subprocess
import sys
import time
import tomllib
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

compute_metrics = importlib.import_module("audit.metrics").compute_metrics
validate_record = importlib.import_module("audit.records").validate_record
GROUND_TRUTH_SENTINELS = importlib.import_module("audit.records").GROUND_TRUTH_SENTINELS
parse_target_id = importlib.import_module("audit.targets").parse_target_id
target_keys_match = importlib.import_module("audit.targets").target_keys_match
TargetKey = importlib.import_module("audit.targets").TargetKey
DEFAULT_RESTRICTED_DIR = Path(
    "/Users/alec/source/agent-memory/projects/varde-py/working/plans/"
    "2026-10-17-quality-score-build/qs-call-audit/notes/restricted/call-audit"
)
DEFAULT_LOCK_FILE = DEFAULT_RESTRICTED_DIR / "test-run.lock"
DEFAULT_EDGE_CACHE_DIR = Path("~/.cache/qsca-edges").expanduser()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    split_dir = _split_dir(args.split, args.restricted_dir)
    groups = _groups(split_dir)
    if not groups:
        raise ValueError(f"no group input directories found under {split_dir}")
    inputs = []
    pending_skipped = 0
    for group_dir in groups:
        records, skipped = _load_records(group_dir)
        pending_skipped += skipped
        repos = _load_repositories(group_dir.name)
        _validate_repo_records(group_dir.name, records, repos, args.split)
        inputs.append((group_dir.name, records, repos))

    print(f"pending review records skipped: {pending_skipped}")
    if args.split == "test" and pending_skipped and not args.allow_pending_skip:
        raise ValueError(
            f"test split skipped {pending_skipped} pending review records; "
            "pass --allow-pending-skip to continue"
        )

    if args.dry_run:
        print(f"inputs: {split_dir}")
        _print_clone_plan(inputs)
        return 0

    _validate_repo_filters(inputs, args)
    if args.metrics_only:
        return _metrics_only(args)

    adapter = _load_adapter(args.adapter)
    results = _measure_repos(inputs, args, adapter)

    _write_records(args.records_dir, results)
    report_lines = []
    for language, records in sorted(results.items()):
        metrics = compute_metrics(records)
        report_lines.append(_report_line(language, metrics))
    if args.split == "test":
        _claim_test_run(args.lock_file)
    print(f"inputs: {split_dir}")
    for line in report_lines:
        print(line)
    _write_metrics(args.metrics_json, results)
    return 0


class RepoTimeLimitExceeded(Exception):
    """A repository took longer than --repo-time-limit-seconds."""


@contextmanager
def _repo_time_limit(repo_name: str, seconds: float | None):
    if not seconds or seconds <= 0:
        yield
        return

    def expire(signum: int, frame: object) -> None:
        raise RepoTimeLimitExceeded(
            f"repository {repo_name!r} exceeded --repo-time-limit-seconds "
            f"{seconds:g}; rerun it with --repo or raise the limit"
        )

    previous = signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _measure_repos(
    inputs: list[tuple[str, list[dict[str, Any]], dict[str, dict[str, Any]]]],
    args: argparse.Namespace,
    adapter: Any,
) -> dict[str, list[dict[str, Any]]]:
    selected = set(args.repo)
    skipped = set(args.skip_repo)
    results: dict[str, list[dict[str, Any]]] = defaultdict(list)
    counter = 0
    for _, records, repos in inputs:
        by_repo: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            by_repo[str(record["repo"])].append(record)
        for repo_name, repo_records in sorted(by_repo.items()):
            language = str(repo_records[0]["language"])
            if args.repo and repo_name not in selected:
                continue
            if repo_name in skipped:
                results[language].extend(repo_records)
                continue
            started = time.monotonic()
            print(f"[{counter + 1}] {repo_name}: start", flush=True)
            _measure_repo(repo_name, repo_records, repos, args, adapter)
            counter += 1
            print(
                f"[{counter}] {repo_name}: done in "
                f"{time.monotonic() - started:.1f}s ({len(repo_records)} sites)",
                flush=True,
            )
            results[language].extend(repo_records)
    return results


def _measure_repo(
    repo_name: str,
    repo_records: list[dict[str, Any]],
    repos: dict[str, dict[str, Any]],
    args: argparse.Namespace,
    adapter: Any,
) -> None:
    run = _RepoRun(
        repo_name, str(repo_records[0]["language"]), repo_records, time.monotonic()
    )
    try:
        with _repo_time_limit(repo_name, args.repo_time_limit_seconds):
            edges = _edges(repo_name, repos, args, adapter)
    except NotImplementedError:
        raise
    except subprocess.TimeoutExpired as error:
        _write_failure(
            args.failures_jsonl,
            run,
            "index_build_timeout",
            f"export exceeded {args.export_timeout_seconds}s: {error}",
        )
        return
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        _write_failure(
            args.failures_jsonl,
            run,
            "worker_failure",
            f"{type(error).__name__}: {error}",
        )
        return
    _apply_edges(repo_name, repo_records, edges)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", choices=("existing", "quality"), required=True)
    parser.add_argument("--split", choices=("dev", "test"), required=True)
    parser.add_argument("--repo-cache", type=Path, required=True)
    parser.add_argument("--restricted-dir", type=Path, default=DEFAULT_RESTRICTED_DIR)
    parser.add_argument("--lock-file", type=Path, default=DEFAULT_LOCK_FILE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-pending-skip", action="store_true")
    parser.add_argument(
        "--edge-cache-dir",
        type=Path,
        default=DEFAULT_EDGE_CACHE_DIR,
        help="per-repo exported-edge cache, keyed by repository name and pinned SHA",
    )
    parser.add_argument(
        "--refresh-edges",
        action="store_true",
        help="export edges again even when the cache already holds a repo's edges",
    )
    parser.add_argument(
        "--export-timeout-seconds",
        type=float,
        help="per-repo limit for the adapter's isolated build",
    )
    parser.add_argument(
        "--repo-time-limit-seconds",
        type=float,
        default=600.0,
        help="wall-time limit per repository's export (0 disables); abort naming it",
    )
    parser.add_argument(
        "--metrics-only",
        action="store_true",
        help=(
            "recompute metrics from saved records in --records-dir; touch no repository"
        ),
    )
    parser.add_argument(
        "--records-dir",
        type=Path,
        help="write <language>-progress-records.jsonl with measured records",
    )
    parser.add_argument(
        "--metrics-json", type=Path, help="write the per-language metrics payload"
    )
    parser.add_argument(
        "--failures-jsonl",
        type=Path,
        help="append one entry per repository whose export failed or timed out",
    )
    parser.add_argument(
        "--repo",
        action="append",
        default=[],
        help="process only the named repositories (repeatable)",
    )
    parser.add_argument(
        "--skip-repo",
        action="append",
        default=[],
        help="keep a repository's sites unresolved and export nothing (repeatable)",
    )
    return parser


def _validate_repo_filters(
    inputs: list[tuple[str, list[dict[str, Any]], dict[str, dict[str, Any]]]],
    args: argparse.Namespace,
) -> None:
    known = {name for _, _, repos in inputs for name in repos}
    selected = set(args.repo)
    skipped = set(args.skip_repo)
    if selected & skipped:
        raise ValueError(
            f"repositories both selected and skipped: {sorted(selected & skipped)}"
        )
    unknown = (selected | skipped) - known
    if unknown:
        raise ValueError(
            f"repositories are not pinned in this split: {sorted(unknown)}"
        )


def _metrics_only(args: argparse.Namespace) -> int:
    if args.records_dir is None:
        raise ValueError("--metrics-only needs --records-dir")
    results: dict[str, list[dict[str, Any]]] = {}
    suffix = "-progress-records.jsonl"
    for path in sorted(args.records_dir.glob(f"*{suffix}")):
        results[path.name[: -len(suffix)]] = _read_jsonl_records(path)
    if not results:
        raise ValueError(f"no *{suffix} records found under {args.records_dir}")
    print(f"inputs: {args.records_dir}")
    for language, records in sorted(results.items()):
        print(_report_line(language, compute_metrics(records)))
    _write_metrics(args.metrics_json, results)
    return 0


def _read_jsonl_records(path: Path) -> list[dict[str, Any]]:
    records = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        record = json.loads(line)
        try:
            validate_record(record)
        except ValueError as error:
            raise ValueError(
                f"invalid record at {path}:{line_number}: {error}"
            ) from error
        records.append(record)
    return records


def _write_records(
    directory: Path | None, results: dict[str, list[dict[str, Any]]]
) -> None:
    if directory is None:
        return
    directory.mkdir(parents=True, exist_ok=True)
    for language, records in sorted(results.items()):
        path = directory / f"{language}-progress-records.jsonl"
        with path.open("w", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record, sort_keys=True) + "\n")


def _write_metrics(path: Path | None, results: dict[str, list[dict[str, Any]]]) -> None:
    if path is None:
        return
    payload = {
        language: compute_metrics(records)
        for language, records in sorted(results.items())
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


@dataclass(frozen=True)
class _RepoRun:
    repo: str
    language: str
    records: list[dict[str, Any]]
    started: float


def _write_failure(
    path: Path | None, run: _RepoRun, status: str, evidence: str
) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "duration_seconds": round(time.monotonic() - run.started, 1),
        "evidence": evidence[-4096:],
        "language": run.language,
        "repo": run.repo,
        "sites_unresolved_by_failure": len(run.records),
        "status": status,
    }
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, sort_keys=True) + "\n")


def _split_dir(split: str, restricted_dir: Path) -> Path:
    return ROOT / "data" / "dev" if split == "dev" else restricted_dir


def _groups(split_dir: Path) -> list[Path]:
    return sorted(path for path in split_dir.iterdir() if path.is_dir())


def _load_records(group_dir: Path) -> tuple[list[dict[str, Any]], int]:
    records = []
    pending_skipped = 0
    for path in sorted(group_dir.glob("*.jsonl")):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if _is_pending_review(record):
                    pending_skipped += 1
                    continue
                _require_record_object(record)
                validate_record(record)
            except (json.JSONDecodeError, TypeError, ValueError) as error:
                raise ValueError(
                    f"invalid record at {path}:{line_number}: {error}"
                ) from error
            records.append(record)
    if not records:
        raise ValueError(f"no JSONL records found under {group_dir}")
    return records, pending_skipped


def _require_record_object(record: object) -> None:
    if not isinstance(record, dict):
        raise TypeError("record must be a JSON object")


def _is_pending_review(record: object) -> bool:
    return isinstance(record, dict) and (
        (
            "repo" not in record
            and record.get("status") == "pending_human_verification"
            and isinstance(record.get("site"), dict)
        )
        or all(key in record for key in ("reviewer_1", "reviewer_2", "agreement"))
    )


def _load_repositories(group: str) -> dict[str, dict[str, Any]]:
    path = ROOT / "repos" / f"{group}.toml"
    if not path.is_file():
        raise FileNotFoundError(
            f"missing pinned repositories file for group {group!r}: {path}"
        )
    with path.open("rb") as stream:
        data = tomllib.load(stream)
    collection = _repository_rows(data, path)
    repos: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(collection, 1):
        name = _manifest_value(row, ("name", "repo"), "repository name", path, index)
        url = _manifest_value(row, ("url",), "url", path, index)
        sha = _manifest_value(row, ("sha", "pin_sha"), "pinned SHA", path, index)
        role = _manifest_value(row, ("role",), "role", path, index)
        languages = _manifest_languages(row, data, group, path, index)
        if name in repos:
            raise ValueError(f"duplicate repository {name!r} in {path}")
        repos[name] = {
            "name": name,
            "url": url,
            "sha": sha,
            "languages": languages,
            "role": role,
        }
    return repos


def _repository_rows(data: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    keys = [key for key in ("repo", "repos") if key in data]
    if len(keys) != 1:
        raise ValueError(
            f"unknown repository manifest shape in {path}; expected [[repo]] "
            "or [[repos]] rows"
        )
    rows = data[keys[0]]
    if keys[0] == "repos" and isinstance(rows, dict):
        rows = [
            dict(row, name=name) for name, row in rows.items() if isinstance(row, dict)
        ]
    if not isinstance(rows, list):
        raise TypeError(
            f"unknown repository manifest shape in {path}; expected [[repo]] "
            "or [[repos]] rows"
        )
    if not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError(
            f"unknown repository manifest shape in {path}; rows must be tables"
        )
    return rows


def _manifest_value(
    row: dict[str, Any],
    aliases: tuple[str, ...],
    label: str,
    path: Path,
    index: int,
) -> str:
    values = [row[key] for key in aliases if key in row]
    if not values or any(not isinstance(value, str) or not value for value in values):
        raise ValueError(
            f"unknown repository manifest shape in {path}: row {index} needs {label}"
        )
    if len(set(values)) != 1:
        raise ValueError(
            f"unknown repository manifest shape in {path}: conflicting {label} "
            f"aliases in row {index}"
        )
    return values[0]


def _manifest_languages(
    row: dict[str, Any],
    data: dict[str, Any],
    group: str,
    path: Path,
    index: int,
) -> list[str]:
    value = row.get("languages", row.get("language"))
    if value is None:
        value = data.get("languages", data.get("language"))
    if value is None and group == "cpp":
        value = "cpp"
    languages = [value] if isinstance(value, str) else value
    if (
        not isinstance(languages, list)
        or not languages
        or any(not isinstance(language, str) or not language for language in languages)
    ):
        raise ValueError(
            f"unknown repository manifest shape in {path}: row {index} needs "
            "language or languages"
        )
    return sorted(set(languages))


def _validate_repo_records(
    group: str,
    records: list[dict[str, Any]],
    repos: dict[str, dict[str, Any]],
    split: str,
) -> None:
    expected_role = "dev" if split == "dev" else "test-only"
    for record in records:
        repo_name = str(record["repo"])
        repo = repos.get(repo_name)
        if repo is None:
            raise ValueError(
                f"{split} split: record repository {repo_name!r} is not in "
                f"the {group} repository manifest"
            )
        if repo["role"] != expected_role:
            raise ValueError(
                f"{split} split: repository {repo_name!r} has role {repo['role']!r}; "
                f"expected {expected_role!r} in {group}"
            )
        if record["language"] not in repo["languages"]:
            raise ValueError(
                f"{split} split: repository {repo_name!r} is not pinned for "
                f"language {record['language']!r} in {group}"
            )


def _print_clone_plan(
    inputs: list[tuple[str, list[dict[str, Any]], dict[str, dict[str, Any]]]],
) -> None:
    pins = {
        (group, record["repo"]): repos[str(record["repo"])]["sha"]
        for group, records, repos in inputs
        for record in records
    }
    for (group, name), sha in sorted(pins.items()):
        print(f"would clone {group}:{name} @ {sha}")


def _checkout_repo(name: str, repos: dict[str, dict[str, Any]], cache: Path) -> Path:
    if name not in repos:
        raise ValueError(f"repository {name!r} is not pinned in its group TOML")
    entry = repos[name]
    sha = entry["sha"]
    path = cache / name.replace("/", "__")
    cache.mkdir(parents=True, exist_ok=True)
    if not (path / ".git").exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--no-checkout", entry["url"], str(path)], check=True
        )
    if _git_head(path) != sha or not _worktree_is_clean(path):
        subprocess.run(["git", "-C", str(path), "fetch", "origin", sha], check=True)
        subprocess.run(
            ["git", "-C", str(path), "checkout", "--detach", sha], check=True
        )
    actual = _git_head(path)
    if actual != sha:
        raise ValueError(f"{name} checkout is {actual}, expected pinned SHA {sha}")
    return path


def _git_head(path: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _worktree_is_clean(path: Path) -> bool:
    status = subprocess.run(
        ["git", "-C", str(path), "status", "--porcelain", "--untracked-files=no"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return not status.strip()


def _edge_cache_path(directory: Path, repo: str, sha: str) -> Path:
    return directory / f"{repo.replace('/', '__')}__{sha}.jsonl"


def _edges(
    repo: str,
    repos: dict[str, dict[str, Any]],
    args: argparse.Namespace,
    adapter: Any,
) -> list[dict[str, Any]]:
    cache = _edge_cache_path(args.edge_cache_dir, repo, repos[repo]["sha"])
    if cache.is_file() and cache.stat().st_size and not args.refresh_edges:
        return _load_edges(cache)
    repo_path = _checkout_repo(repo, repos, args.repo_cache)
    exported = _export_edges(adapter, repo_path, args.export_timeout_seconds)
    _store_edges(exported, cache)
    return _load_edges(cache)


def _export_edges(adapter: Any, repo_path: Path, timeout: float | None) -> Path:
    if timeout is None:
        return adapter.export_edges(repo_path)
    if "timeout_seconds" not in inspect.signature(adapter.export_edges).parameters:
        raise ValueError(
            f"adapter {adapter.__name__!r} cannot honour --export-timeout-seconds"
        )
    return adapter.export_edges(repo_path, timeout_seconds=timeout)


def _store_edges(exported: Path, cache: Path) -> None:
    cache.parent.mkdir(parents=True, exist_ok=True)
    if exported.resolve() != cache.resolve():
        temporary = cache.with_name(cache.name + ".tmp")
        shutil.copyfile(exported, temporary)
        temporary.replace(cache)
        exported.unlink(missing_ok=True)


def _load_adapter(name: str) -> Any:
    return importlib.import_module(f"adapters.{name}")


def _load_edges(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _apply_edges(
    repo: str, records: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> None:
    by_site: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        file = edge.get("file")
        line = edge.get("site_line")
        if (
            not isinstance(file, str)
            or not isinstance(line, int)
            or isinstance(line, bool)
        ):
            raise TypeError(
                "adapter edges must include repo-relative 'file' and integer "
                "'site_line' "
                "to match labeled sites"
            )
        by_site[(repo, file, line)].append(edge)
    targets = _labeled_targets(records)
    for record in records:
        candidates = by_site.get((repo, str(record["file"]), int(record["line"])), [])
        if not candidates:
            _set_measurement(record, None, "unresolved")
            continue
        if len(candidates) > 1:
            call_name = record.get("call_name") or _ground_truth_name(record)
            candidates = [edge for edge in candidates if edge.get("name") == call_name]
        if len(candidates) != 1:
            _set_measurement(record, None, "ambiguous")
            continue
        edge = candidates[0]
        status = str(edge.get("kind", "opaque"))
        if status != "resolved":
            _set_measurement(record, None, status, edge.get("callee_module"))
            continue
        measured = _measured_target(edge)
        record["measured_file"] = measured.file
        record["measured_name"] = measured.name
        record["measured_line"] = measured.line
        matched = _match_target(measured, targets)
        _set_measurement(
            record,
            matched or _index_target_id(measured),
            "resolved",
            edge.get("callee_module"),
        )


def _labeled_targets(records: list[dict[str, Any]]) -> list[tuple[Any, str]]:
    targets = []
    for record in records:
        truth = record.get("ground_truth")
        if not isinstance(truth, str) or truth in GROUND_TRUTH_SENTINELS:
            continue
        key = parse_target_id(str(record["language"]), truth)
        targets.append((key, truth))
    return targets


def _match_target(measured: Any, targets: list[tuple[Any, str]]) -> str | None:
    matching = sorted(
        target_id for key, target_id in targets if target_keys_match(measured, key)
    )
    return matching[0] if matching else None


def _measured_target(edge: dict[str, Any]) -> Any:
    file = edge.get("callee_file")
    name = edge.get("callee_name")
    line = edge.get("callee_line")
    if not isinstance(file, str) or not file or not isinstance(name, str) or not name:
        raise TypeError(
            f"resolved adapter edge at {edge.get('file')}:{edge.get('site_line')} "
            "lacks "
            "callee_file/callee_name; rebuild the edge cache with --refresh-edges"
        )
    if line is not None and (not isinstance(line, int) or isinstance(line, bool)):
        raise TypeError("adapter edge callee_line must be a positive integer or null")
    return TargetKey(file=file, name=name, line=line)


def _index_target_id(measured: Any) -> str:
    line = "?" if measured.line is None else str(measured.line)
    return f"index:{measured.file}:{line}:{measured.name}"


def _ground_truth_name(record: dict[str, Any]) -> str | None:
    truth = record.get("ground_truth")
    if not isinstance(truth, str) or truth in GROUND_TRUTH_SENTINELS:
        return None
    return parse_target_id(str(record["language"]), truth).name


def _set_measurement(
    record: dict[str, Any],
    edge: object,
    status: str,
    module: object = None,
) -> None:
    record["measured_edge"] = edge
    record["measured_status"] = status
    record["measured_module"] = module


def _report_line(language: str, metrics: dict[str, Any]) -> str:
    recall = metrics["natural_frequency_recall"]
    depth = metrics["depth_error"]["within_one_share"]
    return (
        f"{language}: precision={_number(metrics['precision'])} "
        f"recall={_number(recall)} resolved_share={_number(metrics['resolved_share'])} "
        f"depth_error_le1={_number(depth)}"
    )


def _number(value: object) -> str:
    return "n/a" if value is None else f"{float(value):.4f}"


def _claim_test_run(lock_file: Path) -> None:
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with lock_file.open("x", encoding="utf-8") as stream:
            stream.write("test split run claimed\n")
    except FileExistsError as error:
        raise RuntimeError(
            "test split already run; remove lock only with orchestrator approval: "
            f"{lock_file}"
        ) from error


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
