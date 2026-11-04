"""Accept or reject a proposal: the only code that changes skill or agent files.

Pure steps (`stale_paths`, `post_images`, `touches_agent_source`) are kept apart
from file I/O. `accept` needs the user's recorded approval and source paths
inside the allowed roots, checks every pre-image hash, computes every
post-image and only then writes; a failed agent regeneration restores the old
files. Files are read and written without newline translation.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from pathlib import Path

from varde_core import skill_props

from . import approval, baseline_store, filediff, installed, reset, shim, tool_entry
from . import record as rec

Regenerate = Callable[[list[str]], bool]  # extra generate.py args -> success


class ApplyError(ValueError):
    """The proposal cannot be accepted or rejected; nothing was changed."""


def stale_paths(
    pre_hashes: Mapping[str, str], current: Mapping[str, str | None]
) -> list[str]:
    """Paths whose current text no longer matches the proposal's pre-image."""
    stale = []
    for path, expected in pre_hashes.items():
        text = current.get(path)
        actual = filediff.ABSENT if text is None else rec.hash_text(text)
        if actual != expected:
            stale.append(path)
    return sorted(stale)


def post_images(
    diff_text: str, current: Mapping[str, str | None]
) -> dict[str, str | None]:
    """New text for every file in the diff (None: delete); mismatches raise."""
    images: dict[str, str | None] = {}
    for file_diff in filediff.parse_diff(diff_text):
        old = current.get(file_diff.path)
        if file_diff.creates != (old is None):
            raise ApplyError(f"file state differs from the diff: {file_diff.path}")
        new = filediff.apply_file_diff(old or "", file_diff)
        if file_diff.deletes and new:
            raise ApplyError(f"delete leaves text behind: {file_diff.path}")
        images[file_diff.path] = None if file_diff.deletes else new
    return images


def touches_agent_source(paths: list[str]) -> bool:
    return any(
        Path(path).name == "capabilities.json" or "/app/templates/" in path
        for path in paths
    )


def find_generator(paths: list[str]) -> Path | None:
    """`app/scripts/generate.py` of the checkout holding the touched agent source."""
    for path in paths:
        for parent in Path(path).parents:
            candidate = parent / "app" / "scripts" / "generate.py"
            if candidate.is_file():
                return candidate
    return None


def generator_regenerate(generator: Path) -> Regenerate:
    root = generator.parents[2]

    def run(extra: list[str]) -> bool:
        command = [sys.executable, str(generator), *extra]
        return subprocess.run(command, cwd=root, check=False).returncode == 0  # noqa: S603

    return run


def _read(path: str) -> str | None:
    target = Path(path)
    return rec.read_raw(target) if target.is_file() else None


def _write_all(images: Mapping[str, str | None]) -> None:
    for path, text in images.items():
        if text is None:
            Path(path).unlink(missing_ok=True)
            continue
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text, newline="")


def _restore(current: Mapping[str, str | None]) -> None:
    for path, text in current.items():
        if text is None:
            Path(path).unlink(missing_ok=True)
        else:
            Path(path).write_text(text, newline="")


def _regenerate(paths: list[str], regenerate: Regenerate | None) -> Regenerate | None:
    if not touches_agent_source(paths):
        return None
    if regenerate is not None:
        return regenerate
    generator = find_generator(paths)
    if generator is None:
        raise ApplyError(
            "agent source changed but app/scripts/generate.py was not found"
        )
    return generator_regenerate(generator)


AGENT_REFUSED = (
    "agent profiles are generated from the package; not editable in an installed copy"
)


def _sync_dir(sync: Path | None) -> Path:
    skills_dir = sync or tool_entry.sync_target()
    if skills_dir is None:
        raise ApplyError(tool_entry.NO_SYNC_TARGET)
    return skills_dir


def _check_installed(paths: list[str], skills_dir: Path) -> None:
    if touches_agent_source(paths):
        raise ApplyError(AGENT_REFUSED)
    reason = installed.problem(paths, skills_dir)
    if reason:
        raise ApplyError(reason)


def accept(
    memory_root: Path,
    record_id: str,
    regenerate: Regenerate | None = None,
    roots: Iterable[Path] | None = None,
    sync: Path | None = None,
) -> rec.LoopRecord:
    """Apply an approved, proposed record; see `accept_with_notes`."""
    return accept_with_notes(memory_root, record_id, regenerate, roots, sync)[0]


_PACKAGE_PATH = re.compile(r"^(?P<package>.*?)/(?:skills|how)/(?P<skill>[^/]+)/")


def _repo_tree_hash(paths: list[str], skill: str) -> str | None:
    """Tree hash of the package-layout skill that holds `paths`, or None."""
    for path in paths:
        match = _PACKAGE_PATH.match(path)
        if match is None or match["skill"] != skill:
            continue
        package = Path(match["package"])
        tree = baseline_store.layout_tree(
            package / "skills" / skill, package / "how" / skill
        )
        return skill_props.tree_hash(tree)
    return None


def _check_restored(
    record: rec.LoopRecord, paths: list[str], skills_dir: Path | None
) -> str | None:
    """The baseline tree hash a restore promised, after verifying the disk has it."""
    target = reset.baseline_target(record)
    if target is None:
        return None
    expected = target[1]
    if skills_dir is not None:
        wrong = installed.installed_mismatch(paths, skills_dir, expected)
    else:
        wrong = (
            [] if _repo_tree_hash(paths, record.skill) == expected else [record.skill]
        )
    if wrong:
        raise ApplyError(f"restored tree does not match baseline hash: {wrong[0]}")
    return expected


def accept_with_notes(
    memory_root: Path,
    record_id: str,
    regenerate: Regenerate | None = None,
    roots: Iterable[Path] | None = None,
    sync: Path | None = None,
) -> tuple[rec.LoopRecord, list[str]]:
    """Apply the stored diff of an approved, proposed record; mark it applied.

    Without explicit package-layout `roots` the paths must lie in synced skills
    at the sync target; the sidecar then records the new tree hash. Returns the
    record and the touched skills whose sidecar was not refreshed because they
    had hand edits. A baseline-restore record is verified against its tree hash
    after writing; a mismatch restores the old files and raises.
    """
    skills_dir = _sync_dir(sync) if roots is None else None
    record = rec.read_record(memory_root, record_id)
    if record.state != "proposed":
        raise ApplyError(f"{record.id} is {record.state}, not proposed")
    problem = approval.approval_problem(memory_root, record.id)
    if problem:
        raise ApplyError(problem)
    diff = rec.read_diff(memory_root, record)
    if not diff:
        raise ApplyError(f"{record.id} has no stored diff")
    try:
        paths = [item.path for item in filediff.parse_diff(diff)]
    except filediff.DiffError as error:
        raise ApplyError(f"{record.id}: unreadable diff: {error}") from error
    if set(paths) != set(record.pre_hashes):
        raise ApplyError(f"{record.id}: diff files differ from the recorded pre-images")
    if skills_dir is not None:
        _check_installed(paths, skills_dir)
    else:
        escaped = approval.outside_roots(paths, roots or [])
        if escaped:
            raise ApplyError(
                f"paths outside skill or agent source: {', '.join(escaped)}"
            )
    current = {path: _read(path) for path in paths}
    stale = stale_paths(record.pre_hashes, current)
    if stale:
        raise ApplyError(f"changed since proposed, nothing applied: {', '.join(stale)}")
    try:
        images = post_images(diff, current)
    except filediff.DiffError as error:
        raise ApplyError(f"{record.id}: diff does not apply: {error}") from error
    regen = _regenerate(paths, regenerate)
    tracked = installed.loop_tracked(paths, skills_dir) if skills_dir else frozenset()
    _write_all(images)
    if regen is not None and not (regen([]) and regen(["--check"])):
        _restore(current)
        regen([])
        raise ApplyError("agent regeneration failed; files restored, nothing applied")
    try:
        restored_hash = _check_restored(record, paths, skills_dir)
    except ApplyError:
        _restore(current)
        raise
    skipped = []
    if skills_dir is not None:
        skipped = installed.refresh_sidecars(paths, skills_dir, tracked, restored_hash)
    if any(Path(path).name == tool_entry.REGISTRY_NAME for path in paths):
        shim.install_shim()
    applied = replace(record, state="applied", decision="accepted")
    rec.write_record(memory_root, applied)
    return applied, skipped


def reject(memory_root: Path, record_id: str) -> rec.LoopRecord:
    """Mark a proposed record rejected; an applied record cannot be undone."""
    record = rec.read_record(memory_root, record_id)
    if record.state == "applied":
        raise ApplyError(f"{record.id} is applied; there is no undo")
    if record.state != "proposed":
        raise ApplyError(f"{record.id} is {record.state}, not proposed")
    rejected = replace(record, state="rejected", decision="rejected")
    rec.write_record(memory_root, rejected)
    return rejected
