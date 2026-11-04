"""Search and retrieve captured output."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from varde_toz.chunk import truncate
from varde_toz.config import config_dir, env_os, load_config, varde_toz_dir
from varde_toz.project import project_root, store_db_path
from varde_toz.raw import RawHandle, RawStore
from varde_toz.search import search
from varde_toz.store import Store

QUERY_HELP = """Search or retrieve stored output

Usage: varde run query [OPTIONS] [QUERIES]...

Arguments:
  [QUERIES]...
          Search terms. Omit to retrieve a capture with --handle

Options:
      --fallback-dir <FALLBACK_DIR>
          External store to try after primary-store access fails

  -H, --handle <HANDLE>
          Capture to search or retrieve
@@BLANK10@@
          [alias: --id]

      --project <PROJECT>
          Project directory (default: git root of cwd, else cwd)

      --raw <RAW>
          Retrieve exact bytes from an opt-in raw-output handle

      --json
          Machine-readable JSON output

      --list
          List recent captures

  -c, --chunk <CHUNK>
          Print only this chunk (0-based)

      --quiet
          Print only the handle line on overflow

      --records <RECORDS>
          Print a matched profile script's `vardeToz.record()` output of this kind, as JSONL

  -l, --lines <LINES>
          Print only lines A:B (1-based, inclusive)

      --stream <STREAM>
          Output stream for capture or raw retrieval
@@BLANK10@@
          [default: stdout]
          [possible values: stdout, stderr]

  -s, --source <SOURCE>
          Partial match on label or source when searching

      --limit <LIMIT>
          Results per search term, or number of listed captures

      --type <CONTENT_TYPE>
          Filter search results by content type
@@BLANK10@@
          [possible values: code, prose]

      --all
          Include superseded captures

      --global
          Search every project store

  -h, --help
          Print help (see a summary with '-h')

Examples:
  varde run query --handle H "error" "failed"   Search within one capture
  varde run query "connection refused"           Search this project
  varde run query --handle H --chunk 7            Read one 0-based chunk
  varde run query --handle H --lines 120:160      Read a 1-based inclusive line range
  varde run query --list                          List recent captures
  varde run query --raw RAW-H --stream stdout     Write retained raw bytes

Search and retrieved text is normalized and redacted. A matching output profile
may replace the preview with a table of contents, head, or script summary;
--records reads extracted records from a script profile. Raw retrieval requires
a raw-retained handle, returns exact unredacted bytes, and raw handles expire.
Widen searches with --global or include superseded captures with --all; --source
filters by label or source. Capture hooks skip commands starting with varde run.
""".replace("@@BLANK10@@", "          ")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="varde run query", add_help=True)
    parser.add_argument("queries", nargs="*")
    parser.add_argument("-H", "--handle", "--id", dest="handle")
    parser.add_argument("--raw")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("-c", "--chunk", type=int)
    parser.add_argument("--records")
    parser.add_argument("-l", "--lines")
    parser.add_argument("--stream", choices=("stdout", "stderr"), default="stdout")
    parser.add_argument("-s", "--source")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--type", choices=("code", "prose"), dest="content_type")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--global", action="store_true", dest="global_search")
    parser.add_argument("--json", action="store_true")
    return parser


def _error(message: str) -> int:
    print(f"varde-toz: {message}", file=sys.stderr)
    return 2


def _path() -> tuple[Path, Path]:
    root = project_root(os.environ.get("TOZ_PROJECT"))
    load_config()
    base = env_os("TOZ_CONFIG_DIR")
    if base is None:
        base = str(config_dir())
    return root, store_db_path(root, base)


def _global_paths(root: Path, current_path: Path) -> list[Path]:
    bases = [config_dir()]
    configured = varde_toz_dir(root)
    if configured is not None:
        bases.append(configured)
    fallback = env_os("TOZ_FALLBACK_DIR")
    if fallback:
        bases.append(Path(fallback))
    paths = {current_path}
    for base in bases:
        try:
            paths.update(base.glob("*/toz.db"))
        except OSError:
            continue
    return sorted(paths)


def _global_search(
    root: Path, path: Path, args: argparse.Namespace
) -> list[dict[str, Any]]:
    results = [
        {"query": query, "corrected": None, "hits": []} for query in args.queries
    ]
    for db_path in _global_paths(root, path):
        if not db_path.is_file():
            continue
        try:
            with Store.open(db_path) as store:
                if not store.list(1, True):
                    continue
                store.index_deferred(args.handle)
                _refresh_stale(store)
                found = search(
                    store,
                    args.queries,
                    limit=3 if args.limit is None else args.limit,
                    handle=args.handle,
                    source=args.source,
                    content_type=args.content_type,
                    include_superseded=args.all,
                )
        except OSError:
            continue
        project = db_path.parent.name
        for i, result in enumerate(found):
            if results[i]["corrected"] is None:
                results[i]["corrected"] = result["corrected"]
            for hit in result["hits"]:
                hit["project"] = project
                results[i]["hits"].append(hit)
    for result in results:
        result["hits"].sort(key=lambda hit: -hit["score"])
        result["hits"] = result["hits"][
            : max(3 if args.limit is None else args.limit, 1)
        ]
    return results


def _store_with_handle(root: Path, path: Path, handle: str) -> Store | None:
    for candidate in _global_paths(root, path):
        if not candidate.is_file():
            continue
        try:
            store = Store.open_readonly(candidate)
            if store.get_by_handle(handle) is not None:
                return store
            store.conn.close()
        except OSError, sqlite3.Error:
            continue
    return None


def _record_query(
    path: Path, kind: str, bytes_out: int, outcome: str = "ok", details=None
) -> None:
    try:
        store = Store.open(path)
        store.conn.execute(
            (
                "INSERT INTO query_log(ts,kind,bytes_out,session,outcome,details_json) "
                "VALUES(?,?,?,?,?,?)"
            ),
            (
                int(time.time()),
                kind,
                bytes_out,
                None,
                outcome,
                json.dumps(details or {}, separators=(",", ":"), sort_keys=True),
            ),
        )
        store.conn.commit()
        store.conn.close()
    except OSError, sqlite3.Error:
        return


def _refresh_stale(store: Store, root: Path | None = None) -> list[str]:
    from varde_toz.index_files import refresh_stale

    return refresh_stale(store, root)


@contextmanager
def _store(path: Path) -> Iterator[Store]:
    store = Store.open_readonly(path)
    try:
        yield store
    finally:
        store.conn.close()


def _conflict(args: argparse.Namespace) -> str | None:
    if args.raw:
        if (
            args.list
            or args.handle
            or args.queries
            or args.chunk is not None
            or args.records
            or args.lines
            or args.source
            or args.limit is not None
            or args.content_type
            or args.all
            or args.global_search
        ):
            return "--raw cannot be combined with search or capture options"
        return None
    if args.list and (
        args.handle
        or args.queries
        or args.chunk is not None
        or args.records
        or args.lines
        or args.source
        or args.content_type
        or args.global_search
        or args.stream != "stdout"
    ):
        return "--list cannot be combined with search or capture options"
    if args.queries:
        if (
            args.chunk is not None
            or args.records
            or args.lines
            or args.stream != "stdout"
        ):
            return "--chunk, --records, --lines, and --stream require capture retrieval"
        return None
    if not args.list and not args.handle:
        return "provide search terms, --handle, --list, or --raw"
    if not args.list and (
        args.source
        or args.limit is not None
        or args.content_type
        or args.all
        or args.global_search
    ):
        return "search filters require search terms"
    if args.chunk is not None and args.lines:
        return "--chunk and --lines cannot be combined"
    if args.records and (args.chunk is not None or args.lines):
        return "--records cannot be combined with --chunk or --lines"
    return None


def main(argv: list[str] | None = None) -> int:
    try:
        command_args = sys.argv[1:] if argv is None else argv
        if "--help" in command_args or "-h" in command_args:
            sys.stdout.write(QUERY_HELP)
            return 0
        args = _parser().parse_args(command_args)
        args.json = args.json or env_os("TOZ_JSON") not in (None, "", "0", "false")
        message = _conflict(args)
        if message:
            return _error(message)
        root, path = _path()
        if args.raw:
            try:
                handle = RawHandle.parse(args.raw)
                cfg = load_config()
                raw_cfg = cfg.get("raw", {})
                if not isinstance(raw_cfg, dict):
                    raw_cfg = {}
                raw_dir = path.parent / "raw"
                raw = RawStore(
                    raw_dir,
                    enabled=True,
                    max_bytes=int(raw_cfg.get("max_bytes", 1_000_000)),
                    ttl_secs=int(raw_cfg.get("ttl_secs", 86400)),
                )
                try:
                    output = raw.get(handle)
                except ValueError, OSError:
                    fallback = env_os("TOZ_FALLBACK_DIR")
                    fallback_dirs = [
                        p.parent / "raw"
                        for p in _global_paths(root, path)
                        if p.parent / "raw" != raw_dir
                    ]
                    if fallback:
                        fallback_dirs.append(Path(fallback) / "raw")
                    for fallback_dir in fallback_dirs:
                        try:
                            output = RawStore(fallback_dir, enabled=True).get(handle)
                            break
                        except ValueError, OSError:
                            continue
                    else:
                        raise
                sys.stdout.buffer.write(
                    output.stderr if args.stream == "stderr" else output.stdout
                )
                _record_query(
                    path,
                    "raw",
                    len(output.stderr if args.stream == "stderr" else output.stdout),
                    details={
                        "handle_fingerprint": hashlib.sha256(
                            args.raw.encode()
                        ).hexdigest(),
                        "stream": args.stream,
                    },
                )
            except (ValueError, OSError) as exc:
                return _error(str(exc))
            else:
                return 0
        if args.list:
            if not path.exists():
                print("[]" if args.json else "")
                return 0
            with _store(path) as as_store:
                rows = as_store.list(20 if args.limit is None else args.limit, args.all)
                values = [
                    {
                        "handle": row["handle"],
                        "label": row["label"],
                        "kind": row["kind"],
                        "source": row["source"],
                        "bytes": row["bytes"],
                        "chunks": as_store.conn.execute(
                            "SELECT count(*) FROM chunks WHERE capture_id=?",
                            (row["id"],),
                        ).fetchone()[0],
                        "exit_code": row["exit_code"],
                        "created_at": row["created_at"],
                        "superseded": row["superseded_by"] is not None,
                        "session": row["session"],
                        "state": row["state"],
                    }
                    for row in rows
                ]
                if args.json:
                    print(json.dumps(values, separators=(",", ":"), sort_keys=True))
                else:
                    for value in values:
                        age = _format_age(int(time.time()) - value["created_at"])
                        superseded = " (superseded)" if value["superseded"] else ""
                        print(
                            f"{value['handle']:<6} {_format_bytes(value['bytes']):>12} "
                            f"{value['chunks']:>4} chunks  {age:>7}  "
                            f"{value['label'][:70]}{superseded}"
                        )
                _record_query(
                    path,
                    "list",
                    len(json.dumps(values)) if args.json else 0,
                    details={
                        "limit": 20 if args.limit is None else args.limit,
                        "all": args.all,
                        "json": args.json,
                        "row_count": len(values),
                    },
                )
                return 0
        if args.queries:
            if args.global_search:
                results = _global_search(root, path, args)
            elif not path.exists():
                if args.json:
                    print("[]")
                else:
                    print("varde-toz: no captures yet for this project")
                _record_query(
                    path,
                    "search",
                    0,
                    "no_store",
                    {"query_count": len(args.queries), "json": args.json},
                )
                return 0
            else:
                with Store.open(path) as as_store:
                    if not as_store.list(1, True):
                        if args.json:
                            print("[]")
                        else:
                            print("varde-toz: no captures yet for this project")
                        _record_query(
                            path,
                            "search",
                            0,
                            "no_store",
                            {"query_count": len(args.queries), "json": args.json},
                        )
                        return 0
                    as_store.index_deferred(args.handle)
                    refreshed = _refresh_stale(as_store, root)
                    if refreshed and not args.json:
                        count = len(refreshed)
                        print(
                            f"varde-toz: re-indexed {count} changed "
                            f"file{'s' if count != 1 else ''}"
                        )
                    results = search(
                        as_store,
                        args.queries,
                        limit=3 if args.limit is None else args.limit,
                        handle=args.handle,
                        source=args.source,
                        content_type=args.content_type,
                        include_superseded=args.all,
                    )
            if args.json:
                output = json.dumps(results, separators=(",", ":"))
                print(output)
            else:
                for result in results:
                    print(f"## {result['query']}")
                    if not result["hits"]:
                        print("  no matches")
                    for hit in result["hits"]:
                        print(
                            f"[{hit['handle']}:{hit['chunk']}] "
                            f"{truncate(hit['label'], 70)} — {hit['title']} "
                            f"(L{hit['line_start']}-L{hit['line_end']})"
                        )
                        for line in hit["snippet"].splitlines():
                            print(f"    {line}")
                    print()
                output = ""
            _record_query(
                path,
                "search",
                len(output.encode()) if args.json else 0,
                details={
                    "query_count": len(args.queries),
                    "json": args.json,
                    "hit_count": sum(len(result["hits"]) for result in results),
                    "corrected_count": sum(
                        result["corrected"] is not None for result in results
                    ),
                    "limit": 3 if args.limit is None else args.limit,
                    "all": args.all,
                    "global": args.global_search,
                    "source_filter": args.source is not None,
                    "content_type": args.content_type,
                },
            )
            return 0
        selected = _store_with_handle(root, path, args.handle)
        if selected is None:
            return _error(
                f"no capture with handle {args.handle}; handles are project-scoped"
            )
        with selected as as_store:
            capture = as_store.get_by_handle(args.handle)
            if capture is None:
                return _error(
                    f"no capture with handle {args.handle}; handles are project-scoped"
                )
            if capture["binary"]:
                return _error(
                    "legacy binary capture contains metadata only; content "
                    "was not retained"
                )
            if args.records:
                for record in as_store.records_for(capture["id"], args.records):
                    print(record)
            elif args.chunk is not None:
                chunks = as_store.chunks_for(capture["id"])
                if args.chunk < 0 or args.chunk >= len(chunks):
                    return _error(f"capture {args.handle} has {len(chunks)} chunks")
                chunk = chunks[args.chunk]
                if args.json:
                    print(
                        json.dumps(
                            {
                                "handle": args.handle,
                                "chunk": args.chunk,
                                "stream": chunk["stream"],
                                "title": chunk["title"],
                                "line_start": chunk["line_start"],
                                "line_end": chunk["line_end"],
                                "body": chunk["body"],
                            },
                            separators=(",", ":"),
                            sort_keys=True,
                        )
                    )
                else:
                    print(
                        f"── {chunk['title']} [{chunk['stream']}] "
                        f"L{chunk['line_start']}-L{chunk['line_end']} "
                        f"──\n{chunk['body']}"
                    )
            else:
                text = as_store.full_text(capture["id"], args.stream)
                if args.lines:
                    try:
                        low, high = (int(part) for part in args.lines.split(":", 1))
                    except ValueError, TypeError:
                        return _error("range must be A:B")
                    lines = text.split("\n") if capture["chunk_count"] else []
                    high = min(high, len(lines))
                    if low < 1 or low > high:
                        return _error(
                            f"range {args.lines} out of bounds (1..{len(lines)})"
                        )
                    text = "\n".join(lines[low - 1 : high])
                print(text)
    except (OSError, ValueError, sqlite3.Error) as exc:
        return _error(str(exc))
    else:
        return 0


def _format_age(seconds):
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _format_bytes(size):
    return f"{size:,} bytes"
