"""Redact and re-key legacy capture metadata and fetch cache entries."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import blake3

from varde_toz.capture import source_key as capture_source_key
from varde_toz.config import config_dir
from varde_toz.metadata import (
    cache_key,
    identity_at,
    project_identity,
    sanitize_text,
    sanitize_url,
)
from varde_toz.redact_toz import configured_redactor, redact_configured
from varde_toz.store import Store

from ._maintenance import all_stores, current_project, error, json_enabled

HELP = "Redact legacy capture and fetch-cache metadata in place"
OPTIONS = "Options:\n      --fallback-dir <FALLBACK_DIR>  External store to try after primary-store access fails\n      --project <PROJECT>            Project directory (default: git root of cwd, else cwd)\n      --json                         Machine-readable JSON output\n      --quiet                        Print only the handle line on overflow\n  -h, --help                         Print help\n"


def _redact(root: Path):
    config = configured_redactor(root)
    return lambda value: redact_configured(value, config)


def _migrate_store(path: Path, redact) -> int:
    changed = 0
    with Store.open(path) as store:
        rows = list(
            store.conn.execute("SELECT id,label,source,source_key FROM captures")
        )
        for capture_id, label, source, source_key in rows:
            hex_key = len(source_key) == 64 and all(
                char.isascii() and (char.isdigit() or "a" <= char <= "f")
                for char in source_key
            )
            if not source_key:
                safe_key = source_key
            elif hex_key:
                candidates = [label.strip(), capture_source_key(source)]
                already_keyed = any(
                    candidate and identity_at(path.parent, candidate) == source_key
                    for candidate in candidates
                )
                safe_key = (
                    source_key
                    if already_keyed or source_key not in candidates
                    else identity_at(path.parent, source_key)
                )
            else:
                safe_key = identity_at(path.parent, source_key)
            safe_label = sanitize_text(label, redact)
            safe_source = sanitize_text(source, redact)
            if (safe_key, safe_label, safe_source) != (source_key, label, source):
                store.conn.execute(
                    "UPDATE captures SET label=?,source=?,source_key=? WHERE id=?",
                    (safe_label, safe_source, safe_key, capture_id),
                )
                changed += 1
        store.conn.commit()
        if changed:
            store.conn.execute("VACUUM")
            store.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return changed


def _cache_migration(root: Path) -> int:
    directory = config_dir() / "cache"
    try:
        entries = list(directory.iterdir())
    except FileNotFoundError:
        return 0
    redact = _redact(root)
    count = 0
    for source_meta in entries:
        if source_meta.suffix != ".meta":
            continue
        try:
            meta = json.loads(source_meta.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"parsing fetch cache metadata: {exc}") from exc
        url = meta["url"]
        if source_meta.stem != blake3.blake3(url.encode()).hexdigest():
            continue
        key = cache_key(url, config_dir())
        target_meta = directory / f"{key}.meta"
        target_body = directory / f"{key}.body"
        source_body = source_meta.with_suffix(".body")
        if target_meta.exists():
            if not target_body.is_file():
                raise ValueError("incomplete keyed fetch cache entry")
            json.loads(target_meta.read_text())
        else:
            if not source_body.is_file():
                raise ValueError("incomplete legacy fetch cache entry")
            if target_body.exists():
                if source_body.read_bytes() != target_body.read_bytes():
                    raise ValueError("conflicting keyed fetch cache body")
            else:
                os.link(source_body, target_body)
            meta["url"] = sanitize_url(url, redact)
            meta["final_url"] = sanitize_url(meta["final_url"], redact)
            meta["content_type"] = sanitize_text(meta["content_type"], redact)
            if meta.get("title") is not None:
                meta["title"] = sanitize_text(meta["title"], redact)
            if meta.get("etag") is not None:
                meta["etag"] = sanitize_text(meta["etag"], redact)
            if meta.get("project_key") is not None:
                meta["project_key"] = project_identity(
                    meta["project_key"], config_dir()
                )
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=directory, delete=False
            ) as output:
                json.dump(meta, output, separators=(",", ":"))
                temporary = Path(output.name)
            try:
                os.link(temporary, target_meta)
            except FileExistsError:
                if not target_body.is_file():
                    raise ValueError("incomplete keyed fetch cache entry") from None
                json.loads(target_meta.read_text())
            finally:
                temporary.unlink(missing_ok=True)
        source_body.unlink(missing_ok=True)
        source_meta.unlink(missing_ok=True)
        count += 1
    return count


def main(argv: list[str] | None = None) -> int:
    values = sys.argv[1:] if argv is None else argv
    if "--help" in values or "-h" in values:
        print(
            f"{HELP}\n\nUsage: varde setup migrate-metadata [OPTIONS]\n\n{OPTIONS}",
            end="",
        )
        return 0
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--fallback-dir")
    parser.add_argument("--project")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    try:
        args = parser.parse_args(values)
        root = current_project(args.project)
        redactor = _redact(root)
        captures = stores = 0
        for _key, path in all_stores(root):
            captures += _migrate_store(path, redactor)
            stores += 1
        cached_pages = _cache_migration(root)
        if json_enabled(args):
            print(
                json.dumps(
                    {
                        "stores": stores,
                        "captures": captures,
                        "cached_pages": cached_pages,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
        else:
            print(
                f"varde-toz: migrated {captures} capture(s) across {stores} "
                f"store(s) and {cached_pages} cached page(s)"
            )
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        return error(str(exc))
    else:
        return 0
