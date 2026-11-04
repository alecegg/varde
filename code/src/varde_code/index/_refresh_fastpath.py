"""Standard-library-only guard for unchanged code-index refreshes."""

import hashlib
import os
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 20
UNKNOWN_METADATA = -1


def unchanged_summary(
    repo_root: str | Path,
) -> tuple[str, int, int, int, int, int, tuple[str, ...]] | None:
    """Return a primitive summary when persisted file state is certainly current."""
    root = os.path.realpath(os.fspath(repo_root))
    if not os.path.isdir(root) or _inside_git_worktree(root):
        return None

    config = os.environ.get("VARDE_CONFIG_DIR") or _xdg_config_dir()
    db_path = _database_path(root, config)
    lock_path = db_path[:-3] + ".db.lock"
    if not os.path.isfile(db_path) or not os.path.isfile(lock_path):
        return None
    if "?" in db_path or "#" in db_path:
        return None

    try:
        lock = os.open(lock_path, os.O_RDONLY)
    except OSError:
        return None
    try:
        try:
            import fcntl

            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except ImportError, OSError:
            return None
        return _check_database(root, db_path)
    finally:
        os.close(lock)


def _check_database(root, db_path):
    try:
        with sqlite3.connect("file:" + db_path + "?mode=ro", uri=True) as connection:
            if connection.execute("PRAGMA user_version").fetchone() != (
                SCHEMA_VERSION,
            ):
                return None
            if connection.execute(
                "SELECT value FROM slice_meta WHERE key='build_version'"
            ).fetchone() != (_build_version_fingerprint(),):
                return None
            rows = connection.execute(
                "SELECT path,mtime,size,content_hash FROM files"
            ).fetchall()
            if not rows or not _metadata_matches(root, rows):
                return None
            counts = connection.execute(
                "SELECT (SELECT COUNT(*) FROM entities), (SELECT COUNT(*) FROM symbols), "
                "(SELECT COUNT(*) FROM diagnostics)"
            ).fetchone()
    except OSError, sqlite3.Error, TypeError, ValueError:
        return None
    if counts is None:
        return None
    entities, symbols, diagnostics = counts
    return db_path, entities, symbols, diagnostics, len(rows), 0, ()


def _metadata_matches(root, stored_rows):
    stored = {row[0]: row[1:] for row in stored_rows}
    current = []
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    if entry.name != ".git":
                        pending.append(entry.path)
                elif entry.is_file(follow_symlinks=False):
                    metadata = entry.stat(follow_symlinks=False)
                    current.append((entry.path, metadata.st_mtime_ns, metadata.st_size))
        except OSError:
            return False

    if len(current) != len(stored):
        return False
    current.sort()
    for path, mtime, size in current:
        previous = stored.get(path)
        if previous is None:
            return False
        old_mtime, old_size, old_hash = previous
        if (mtime, size) != (old_mtime, old_size):
            return False
        if (mtime, size) == (UNKNOWN_METADATA, UNKNOWN_METADATA):
            try:
                with open(path, "rb") as source:
                    digest = _content_hash(source.read())
            except OSError:
                return False
            if digest != old_hash:
                return False
        elif not _valid_hash(old_hash):
            return False
    return True


def _build_version_fingerprint():
    package = os.path.dirname(os.path.realpath(__file__))
    sources = []
    for directory, subdirectories, filenames in os.walk(package):
        subdirectories.sort()
        sources.extend(
            os.path.join(directory, name) for name in filenames if name.endswith(".py")
        )
    digest = hashlib.blake2b(digest_size=8)
    for source in sorted(sources):
        relative = os.path.relpath(source, package).replace(os.sep, "/")
        digest.update(relative.encode())
        with open(source, "rb") as contents:
            digest.update(contents.read())
    return int.from_bytes(digest.digest(), "big", signed=True)


def _inside_git_worktree(root):
    current = root
    while True:
        if os.path.lexists(os.path.join(current, ".git")):
            return True
        parent = os.path.dirname(current)
        if parent == current:
            return False
        current = parent


def _database_path(root, config):
    name = os.path.basename(root) or "repo"
    value = 0xCBF29CE484222325
    for byte in root.encode():
        value = ((value ^ byte) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return os.path.join(config, "code", "repos-py", f"{name}-{value:016x}", "index.db")


def _xdg_config_dir():
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return os.path.join(xdg, "varde")
    home = os.environ.get("HOME")
    if home:
        return os.path.join(home, ".config", "varde")
    return os.path.join(os.path.expanduser("~"), ".config", "varde")


def _valid_hash(value):
    return (
        isinstance(value, str)
        and len(value) == 16
        and all(character in "0123456789abcdefABCDEF" for character in value)
    )


def _content_hash(contents):
    value = 14_695_981_039_346_656_037
    for byte in contents:
        value = ((value ^ byte) * 1_099_511_628_211) & 0xFFFFFFFFFFFFFFFF
    return f"{value:016x}"
