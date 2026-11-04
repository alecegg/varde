"""Search file indexes and captured output in a varde-toz store."""

from __future__ import annotations

import subprocess
import sys
from enum import StrEnum
from pathlib import Path

from varde_toz.index_files import index_file, is_stale
from varde_toz.search import search as search_store
from varde_toz.store import Store

from .types import SearchHit, SearchQuery, SourceResult

CANDIDATE_POOL = 100


class TozScope(StrEnum):
    DOCS = "docs"
    PLANS = "plans"
    OUTPUT = "output"


class TozSearch:
    """Search a toz database for one of the CLI's toz-backed sources."""

    def __init__(
        self,
        scope: TozScope | str,
        db_path: Path,
        repo_root: Path,
        working: Path | None = None,
    ):
        self.scope = TozScope(scope)
        self.db_path = Path(db_path)
        self.repo_root = _canonical(Path(repo_root))
        self.working = _canonical(working or Path.cwd())

    def source(self) -> str:
        return self.scope.value

    def search(self, query: SearchQuery) -> SourceResult:
        if self.scope is TozScope.OUTPUT:
            return self._search_output(query)
        return self._search_files(query)

    def _search_output(self, query: SearchQuery) -> SourceResult:
        if not self.db_path.is_file():
            return SourceResult.unavailable(self.source(), "no toz store yet")
        try:
            with Store.open_readonly(self.db_path) as store:
                hits = _hits(
                    store, query, self.scope, self.repo_root, self.working, None
                )
        except Exception as error:
            return SourceResult.unavailable(self.source(), str(error))
        return SourceResult.found(self.source(), hits)

    def _search_files(self, query: SearchQuery) -> SourceResult:
        try:
            files = self._discover()
            allowed = (
                {str(_canonical(path)) for path in files}
                if self.scope is TozScope.DOCS
                else None
            )
            with Store.open(self.db_path) as store:
                first_plan_index = (
                    self.scope is TozScope.PLANS
                    and bool(files)
                    and not any(
                        row["kind"] == "index"
                        and _canonical(Path(row["source"]))
                        in {_canonical(path) for path in files}
                        for row in store.list(2**63 - 1, False)
                    )
                )
                missing = _refresh(
                    store, files, self.db_path, self.repo_root, self.working
                )
                hits = _hits(
                    store,
                    query,
                    self.scope,
                    self.repo_root,
                    self.working,
                    allowed,
                    candidate_limit=CANDIDATE_POOL if missing else query.limit,
                )
            if first_plan_index:
                print(
                    "varde search: indexing plan and review files (first run); "
                    "this can take a while...",
                    file=sys.stderr,
                )
        except Exception as error:
            return SourceResult.unavailable(self.source(), str(error))
        return SourceResult.found(self.source(), hits)

    def _discover(self) -> list[Path]:
        if self.scope is TozScope.PLANS:
            _ensure_git_repository(self.repo_root)
            return [
                path
                for name in ("plans", "reviews")
                for path in _markdown_under(self.working / name)
            ]
        output = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],  # noqa: S607 - Git enumerates tracked and untracked repository files.
            cwd=self.repo_root,
            check=False,
            capture_output=True,
        )
        if output.returncode:
            raise RuntimeError("not a git repository")
        files = []
        for value in output.stdout.decode("utf-8", "replace").split("\0"):
            if not value or not _is_doc(value):
                continue
            path = self.repo_root / value
            if not _is_relative_to(path, self.working):
                files.append(path)
        return files


def _hits(
    store: Store,
    query: SearchQuery,
    scope: TozScope,
    repo_root: Path,
    working: Path,
    allowed_sources: set[str] | None,
    *,
    candidate_limit: int = CANDIDATE_POOL,
) -> list[SearchHit]:
    captures = {row["handle"]: row for row in store.list(2**63 - 1, False)}
    source_filter = None
    if scope is TozScope.DOCS:
        source_filter = str(repo_root)
    elif scope is TozScope.PLANS:
        source_filter = str(working)
    results = search_store(
        store, [query.text], limit=candidate_limit, source=source_filter
    )
    mapped = []
    for result in results:
        for hit in result["hits"]:
            capture = captures.get(hit["handle"])
            if capture is None:
                continue
            source_path = Path(capture["source"])
            if scope is TozScope.OUTPUT:
                if capture["kind"] == "index":
                    continue
                location = f"{hit['handle']}#{hit['chunk']}"
            else:
                if capture["kind"] != "index" or not source_path.is_file():
                    continue
                source = str(source_path)
                if allowed_sources is not None and source not in allowed_sources:
                    continue
                if scope is TozScope.PLANS and not _is_plan_source(
                    source_path, working
                ):
                    continue
                if scope is TozScope.DOCS and not _is_repository_doc_source(
                    source_path, repo_root, working
                ):
                    continue
                shown = (
                    source_path.relative_to(repo_root)
                    if scope is TozScope.DOCS
                    and _is_relative_to(source_path, repo_root)
                    else source_path
                )
                location = f"{shown}:{hit['line_start']}"
            title = (
                hit["label"]
                if scope is TozScope.OUTPUT
                else hit["title"] or hit["label"]
            )
            mapped.append(
                SearchHit(
                    scope.value,
                    title,
                    location,
                    hit["snippet"],
                    round(float(hit["score"]) * 1_000_000),
                )
            )
            if len(mapped) == query.limit:
                return mapped
    return mapped


def _refresh(
    store: Store,
    files: list[Path],
    db_path: Path,
    repo_root: Path,
    working: Path,
) -> bool:
    indexed = {}
    missing = False
    for row in store.list(2**63 - 1, False):
        if row["kind"] != "index":
            continue
        path = Path(row["source"])
        if _is_in_scope(path, repo_root, working):
            missing |= not path.is_file()
        indexed[str(path)] = (row["file_mtime"], row["file_hash"])
    for file in files:
        path = _canonical(file)
        mtime, digest = indexed.get(str(path), (None, None))
        if is_stale(path, mtime, digest):
            try:
                index_file(path, None, repo_root, db_path)
            except OSError, ValueError, RuntimeError:
                continue
    return missing


def _is_in_scope(path: Path, repo_root: Path, working: Path) -> bool:
    return _is_repository_doc_source(path, repo_root, working) or _is_plan_source(
        path, working
    )


def _is_repository_doc_source(path: Path, repo_root: Path, working: Path) -> bool:
    try:
        relative = path.relative_to(repo_root).as_posix()
    except ValueError:
        return False
    return not _is_relative_to(path, working) and _is_doc(relative)


def _is_plan_source(path: Path, working: Path) -> bool:
    return path.suffix == ".md" and any(
        _is_relative_to(path, working / name) for name in ("plans", "reviews")
    )


def _is_doc(relative: str) -> bool:
    parts = relative.split("/")
    name = parts[-1]
    guide = name in {"README.md", "AGENTS.md"}
    return (
        (guide and len(parts) <= 2)
        or (parts[0] == "docs" and name.endswith(".md"))
        or (parts[0] == "clis" and name == "README.md")
    )


def _markdown_under(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return [path for path in directory.rglob("*.md") if path.is_file()]


def _ensure_git_repository(repo_root: Path) -> None:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],  # noqa: S607 - Git identifies the repository containing the supplied root.
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if result.returncode:
        raise RuntimeError("not a git repository")


def _canonical(path: Path) -> Path:
    try:
        return path.resolve(strict=True)
    except OSError:
        return path


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    else:
        return True
