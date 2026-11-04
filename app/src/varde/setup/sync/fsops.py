"""Safe filesystem operations used by setup sync."""

from __future__ import annotations

import itertools
import os
import shutil
import stat
from pathlib import Path

_ids = itertools.count()


def _sibling(destination: Path, kind: str) -> Path:
    parent = destination.parent if str(destination.parent) else Path(".")
    for _ in range(100):
        candidate = (
            parent / f".{destination.name}.varde-{kind}-{os.getpid()}-{next(_ids)}"
        )
        if not os.path.lexists(candidate):
            return candidate
    raise FileExistsError(f"could not find a temporary sibling for {destination}")


def remove_path(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    if stat.S_ISDIR(mode):
        shutil.rmtree(path)
    else:
        path.unlink()


def _replace(destination: Path, prepare) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = _sibling(destination, "stage")
    try:
        prepare(staged)
    except BaseException:
        remove_path(staged)
        raise
    backup = None
    if os.path.lexists(destination):
        backup = _sibling(destination, "backup")
        try:
            os.replace(destination, backup)
        except OSError:
            remove_path(staged)
            raise
    try:
        os.replace(staged, destination)
    except OSError as error:
        rollback_error = None
        if backup is not None:
            try:
                os.replace(backup, destination)
            except OSError as rollback:
                rollback_error = rollback
        remove_path(staged)
        if rollback_error:
            raise OSError(
                error.errno,
                f"could not install {destination}: {error}; could not restore its "
                f"backup: {rollback_error}",
            ) from error
        if backup is not None:
            raise OSError(
                error.errno,
                f"could not install {destination}: {error}; restored its previous copy",
            ) from error
        raise OSError(
            error.errno, f"could not install {destination}: {error}"
        ) from error
    if backup is not None:
        remove_path(backup)


def replace_directory(destination: Path, populate) -> None:
    def prepare(staged: Path) -> None:
        staged.mkdir()
        populate(staged)

    _replace(destination, prepare)


def replace_file(destination: Path, contents: bytes) -> None:
    _replace(destination, lambda staged: write_file(staged, contents))


def replace_with_copy(destination: Path, source: Path) -> None:
    replace_directory(destination, lambda staged: copy_directory(source, staged))


def replace_with_symlink(destination: Path, target: Path) -> None:
    _replace(
        destination, lambda staged: staged.symlink_to(target, target_is_directory=True)
    )


def replace_with_file_symlink(destination: Path, target: Path) -> None:
    _replace(destination, lambda staged: staged.symlink_to(target))


def copy_directory(source: Path, destination: Path) -> None:
    if not stat.S_ISDIR(source.lstat().st_mode):
        raise OSError(f"copy source {source} is not a real directory")
    destination.mkdir(parents=True, exist_ok=True)
    for entry in source.iterdir():
        target = destination / entry.name
        mode = entry.lstat().st_mode
        if stat.S_ISDIR(mode):
            copy_directory(entry, target)
        elif stat.S_ISREG(mode):
            shutil.copyfile(entry, target)
            shutil.copystat(entry, target, follow_symlinks=False)
        else:
            raise OSError(f"refusing to copy symlink or special file {entry}")


def write_file(path: Path, contents: bytes, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contents)
    if os.name == "posix":
        path.chmod(0o755 if executable else 0o644)
