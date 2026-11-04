"""Route items by split and audit the entire repository for restricted data."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from splits import LOCK, assign

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESTRICTED = Path(
    "/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-17-quality-score-build/qs-golden-corpus/notes/restricted/golden"
)

# The audit scans files git would publish: tracked files plus untracked files that
# are not ignored, so installed dependencies and build output cannot produce
# findings. Without git, the walk skips these directories instead.
WALK_SKIPPED_DIRECTORIES = frozenset({".git", ".venv", "node_modules", "__pycache__"})

# The quality corpus uses location and broad filename rules for labels. Elsewhere,
# only the specific panel, human, and batch JSONL label names are flagged.
LABEL_FILENAME_PATTERNS = ("*.label*", "label*.json*", "*.labels")
LABEL_TREES = frozenset({"items", "labels"})
GOLDEN_FILENAME_PATTERNS = ("panel-*.jsonl", "human-*.jsonl", "batch-*.jsonl")

# Content scan: a restricted file copied into the repository under a different
# name keeps its bytes, so its sha256 digest matches the restricted store's and
# it is still flagged. Files smaller than MIN_RESTRICTED_BYTES are skipped so
# trivial and empty files do not match everywhere. A restricted file whose name
# and content both differ from the store is only caught by the name and location
# rules above.
MIN_RESTRICTED_BYTES = 20
DIGEST_CHUNK_BYTES = 1 << 16


def restricted_root() -> Path:
    return (
        Path(os.environ.get("VARDE_GOLDEN_RESTRICTED", DEFAULT_RESTRICTED))
        .expanduser()
        .resolve()
    )


def is_test_split(split: str) -> bool:
    return split in {"test", "test-restricted", "test-2"}


def repository_root(start: Path | None = None) -> Path:
    working_directory = start or Path.cwd()
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],  # noqa: S607 - Uses the system git executable from PATH.
        cwd=working_directory,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise FileNotFoundError("current directory is not inside a git repository")
    return Path(result.stdout.strip()).resolve()


def item_destination(item: Path, split: str, task_id: str, repo_items: Path) -> Path:
    base = restricted_root() if is_test_split(split) else repo_items
    task_digest = hashlib.sha256(task_id.encode()).hexdigest()[:24]
    return base / split / task_digest / item.name


def place(
    item: Path,
    split: str,
    task_id: str,
    repo_items: Path = ROOT / "items",
    repo_root: Path | None = None,
) -> Path:
    if not task_id:
        raise ValueError("--task is required")
    if split not in {"dev", "regression", "test", "test-restricted", "test-2"}:
        raise ValueError(f"unknown split: {split}")
    repo = repo_root.resolve() if repo_root else repository_root()
    destination = item_destination(item, split, task_id, repo_items)
    if is_test_split(split) and destination.resolve().is_relative_to(repo):
        raise ValueError("restricted test items cannot be placed inside the repository")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(item, destination, dirs_exist_ok=True)
    (destination / ".varde-split.json").write_text(
        json.dumps({"task_id": task_id, "split": split}) + "\n"
    )
    return destination


def known_test_ids(lock_path: Path = LOCK) -> set[str]:
    if not lock_path.exists():
        return set()
    payload = json.loads(lock_path.read_text())
    return {
        hashlib.sha256(task.encode()).hexdigest()[:24]
        for task, split in payload["assignments"].items()
        if is_test_split(split)
    }


def known_test_tasks(lock_path: Path = LOCK) -> set[str]:
    if not lock_path.exists():
        return set()
    payload = json.loads(lock_path.read_text())
    return {
        task for task, split in payload["assignments"].items() if is_test_split(split)
    }


def listed_files(root: Path) -> list[Path] | None:
    """Files git would publish under ``root``: tracked plus non-ignored others."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],  # noqa: S607 - Uses the system git executable from PATH.
            cwd=root,
            check=False,
            capture_output=True,
        )
    except OSError:
        return None
    if result.returncode:
        return None
    names = result.stdout.decode("utf-8", "surrogateescape").split("\0")
    return [root / name for name in names if name]


def walked_files(root: Path) -> list[Path]:
    files = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if WALK_SKIPPED_DIRECTORIES.intersection(relative.parts):
            continue
        if path.is_file():
            files.append(path)
    return files


def audited_files(root: Path) -> list[Path]:
    listed = listed_files(root)
    return listed if listed is not None else walked_files(root)


def is_label_path(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    relative_parts = relative.parts
    name = path.name.casefold()
    if any(fnmatch.fnmatch(name, pattern) for pattern in GOLDEN_FILENAME_PATTERNS):
        return True
    corpus = Path("code") / "bench" / "quality-corpus"
    if not relative.is_relative_to(corpus):
        return False
    trees = {part.casefold() for part in relative_parts}
    if "labels" in trees:
        return True
    if any(fnmatch.fnmatch(name, pattern) for pattern in LABEL_FILENAME_PATTERNS):
        return True
    return "label" in name and bool(LABEL_TREES.intersection(trees))


def is_test_marker(
    path: Path, restricted_ids: set[str], restricted_tasks: set[str]
) -> bool:
    record = json.loads(path.read_text())
    task_id = record.get("task_id", "")
    digest = hashlib.sha256(task_id.encode()).hexdigest()[:24]
    return (
        is_test_split(record.get("split", ""))
        or digest in restricted_ids
        or task_id in restricted_tasks
    )


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(DIGEST_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def store_digests(store: Path) -> dict[int, set[str]] | None:
    """Digests of the restricted store, keyed by file size; None when absent."""
    if not store.is_dir():
        print(
            f"restricted store unavailable, content scan skipped: {store}",
            file=sys.stderr,
        )
        return None
    digests: dict[int, set[str]] = {}
    for path in store.rglob("*"):
        if not path.is_file():
            continue
        size = path.stat().st_size
        if size < MIN_RESTRICTED_BYTES:
            continue
        digests.setdefault(size, set()).add(file_digest(path))
    return digests


def is_restricted_copy(path: Path, digests: dict[int, set[str]] | None) -> bool:
    """A repository file whose size and digest match a restricted store file."""
    if not digests:
        return False
    same_size = digests.get(path.stat().st_size, set())
    return bool(same_size) and file_digest(path) in same_size


def audit_repo(
    root: Path = ROOT, lock_path: Path = LOCK, store: Path | None = None
) -> list[str]:
    """Restricted data inside ``root``: see the label and content scan rules above."""
    restricted_ids = known_test_ids(lock_path)
    restricted_tasks = known_test_tasks(lock_path)
    digests = store_digests(restricted_root() if store is None else store)
    findings = []
    for path in audited_files(root):
        if not path.is_file():
            continue
        if path.name == ".varde-split.json" and is_test_marker(
            path, restricted_ids, restricted_tasks
        ):
            findings.append(str(path))
            continue
        if is_label_path(path, root) or is_restricted_copy(path, digests):
            findings.append(str(path))
            continue
        relative_parts = path.relative_to(root).parts
        if any(task_id in relative_parts for task_id in restricted_ids):
            findings.append(str(path))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-repo", action="store_true")
    parser.add_argument("--item", type=Path)
    parser.add_argument("--task")
    parser.add_argument("--split")
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--repo-items", type=Path, default=ROOT / "items")
    args = parser.parse_args()
    if args.repo_root:
        repo_root = args.repo_root.resolve()
    else:
        try:
            repo_root = repository_root()
        except FileNotFoundError as error:
            if not args.audit_repo:
                parser.error(str(error))
            repo_root = Path.cwd().resolve()
    if args.audit_repo:
        print(f"audited root: {repo_root}")
        findings = audit_repo(repo_root, LOCK)
        print("\n".join(findings) if findings else "repository split audit: ok")
        return 1 if findings else 0
    if args.item is None or args.split is None or not args.task:
        parser.error("--item, --split and --task are required")
    if not args.item.is_dir():
        parser.error(f"item directory does not exist: {args.item}")
    try:
        split = assign(args.task) if args.split == "locked" else args.split
        print(f"restricted store: {restricted_root()}")
        print(place(args.item, split, args.task, args.repo_items, repo_root=repo_root))
    except FileNotFoundError as error:
        parser.error(str(error))
    except ValueError as error:
        print(error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
