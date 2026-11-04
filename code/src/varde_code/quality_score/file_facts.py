"""Facts for one source file at HEAD or at a git ref.

Uses the same single-file entry as the baseline page and bench
(``varde_code.quality_pass.facts.extract_facts``): facts of one file, with no
cross-file call resolution. That keeps a file's score the same whether it is
scored alone (``--file``), at a base ref (``--base``) or inside a reference.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from varde_code.git import run_git, run_git_bytes
from varde_code.quality_pass.facts import extract_facts
from varde_code.quality_score.raw_measure import (
    max_nesting_by_line,
    python_function_facts,
)

SUFFIXES: dict[str, tuple[str, ...]] = {
    "python": (".py",),
    "typescript": (".ts", ".tsx"),
    "csharp": (".cs",),
}
HEAD = "HEAD"


def language_of(path: str) -> str:
    suffix = PurePosixPath(path).suffix
    for language, suffixes in SUFFIXES.items():
        if suffix in suffixes:
            return language
    raise ValueError(f"no supported language for {path!r}")


def resolve_commit(root: Path, ref: str | None = None) -> str:
    """The commit sha of ``ref`` (default HEAD); a ref is never read as an option."""
    name = ref or HEAD
    if name.startswith("-"):
        raise ValueError(f"invalid git ref {name!r}")
    sha = run_git(
        ["rev-parse", "--verify", "--end-of-options", f"{name}^{{commit}}"], root
    )
    if sha is None:
        raise ValueError(f"unknown git ref {name!r} in {root}")
    return sha.strip()


def read_at(root: Path, path: str, ref: str | None = None) -> bytes:
    """File bytes at the commit of ``ref`` (default HEAD); a missing file raises
    ``FileNotFoundError``, an unknown ref ``ValueError``."""
    sha = resolve_commit(root, ref)
    source = run_git_bytes(["show", "--end-of-options", f"{sha}:{path}"], root)
    if source is None:
        raise FileNotFoundError(f"{path} not found at {ref or HEAD} in {root}")
    return source


def exact_facts(source: bytes | str, language: str, path: str) -> dict[str, Any]:
    """``extract_facts`` plus the exact per-function ``max_nesting`` and, for Python,
    ``vague_names`` and ``delegates`` (the measures ``raw_measure`` reports)."""
    record = extract_facts(source, language, path)
    text = (
        source
        if isinstance(source, str)
        else source.decode("utf-8-sig", errors="replace")
    )
    nesting = max_nesting_by_line(path, text, language)
    python = python_function_facts(text) if language == "python" else {}
    functions = []
    for function in record.get("functions", ()):
        line = function.get("line")
        extra = {"max_nesting": nesting.get(line)} if isinstance(line, int) else {}
        functions.append({**function, **extra, **python.get(line, {})})
    return {**record, "functions": functions}


def facts_for_file(root: Path, path: str, ref: str | None = None) -> dict[str, Any]:
    """The facts record of ``path`` (repository-relative) at HEAD or at ``ref``."""
    return exact_facts(read_at(root, path, ref), language_of(path), path)


def list_files(root: Path, language: str, ref: str | None = None) -> list[str]:
    """Sorted repository-relative source paths of ``language`` at HEAD or ``ref``."""
    suffixes = SUFFIXES.get(language)
    if suffixes is None:
        raise ValueError(f"unsupported language {language!r}")
    sha = resolve_commit(root, ref)
    listing = run_git(["ls-tree", "-r", "--name-only", sha], root)
    if listing is None:
        raise FileNotFoundError(f"cannot list files at {ref or HEAD} in {root}")
    return sorted(p for p in listing.splitlines() if p.endswith(suffixes))


def head_commit(root: Path) -> str:
    commit = run_git(["rev-parse", HEAD], root)
    if commit is None:
        raise FileNotFoundError(f"{root} has no HEAD commit")
    return commit.strip()
