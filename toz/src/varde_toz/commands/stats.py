"""Summarize capture and query savings."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from typing import Any

from varde_toz.config import env_os
from varde_toz.project import project_key

from ._maintenance import (
    all_stores,
    current_project,
    current_store,
    error,
    json_enabled,
)

HELP = (
    "Bytes kept out of context, per kind (estimated tokens labelled as such)\n\n"
    "Usage: varde run stats [OPTIONS]\n\n"
    "Options:\n"
    "      --fallback-dir <FALLBACK_DIR>  External store to try after "
    "primary-store access fails\n"
    "      --session                      Only this session "
    "(VARDE_TOZ_SESSION if set, else the last 8 hours)\n"
    "      --global                       Every project store\n"
    "      --project <PROJECT>            Project directory (default: "
    "git root of cwd, else cwd)\n"
    "      --events <N>                   Include up to N recent query events "
    "per project (max 10000)\n"
    "      --json                         Machine-readable JSON output\n"
    "      --quiet                        Print only the handle line on overflow\n"
    "  -h, --help                         Print help\n"
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--fallback-dir")
    parser.add_argument("--session", action="store_true")
    parser.add_argument("--global", action="store_true", dest="global_stats")
    parser.add_argument("--project")
    parser.add_argument("--events", type=int)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    return parser


def _aggregate(
    conn: sqlite3.Connection,
    session: str | None,
    since: int | None,
    event_limit: int | None,
) -> tuple[dict, list[dict]]:
    if session is not None:
        where, bound = "session = ?", session
    elif since is not None:
        where, bound = "ts >= ?", since
    else:
        where, bound = "1 = 1", None
    stats_query = (
        f"SELECT kind,COUNT(*),COALESCE(SUM(bytes_in),0),"  # noqa: S608 - fixed SQL predicate.
        f"COALESCE(SUM(bytes_out),0) FROM stats_log WHERE {where} "
        "GROUP BY kind ORDER BY SUM(bytes_in) DESC"
    )
    by_kind = [
        {
            "kind": kind,
            "captures": captures,
            "bytes_in": bytes_in,
            "bytes_out": bytes_out,
        }
        for kind, captures, bytes_in, bytes_out in conn.execute(
            stats_query, (bound,) if bound is not None else ()
        )
    ]
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    by_query_kind: list[dict] = []
    events: list[dict] = []
    if "query_log" in tables:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(query_log)")}
        outcome = (
            "AND outcome IN ('ok','partial','no_store')" if "outcome" in columns else ""
        )
        query_kind_query = (
            "SELECT kind,COUNT(*),COALESCE(SUM(bytes_out),0) "  # noqa: S608 - fixed SQL fragments.
            f"FROM query_log WHERE {where} {outcome} "
            "GROUP BY kind ORDER BY SUM(bytes_out) DESC"
        )
        by_query_kind = [
            {"kind": kind, "queries": queries, "bytes_out": bytes_out}
            for kind, queries, bytes_out in conn.execute(
                query_kind_query, (bound,) if bound is not None else ()
            )
        ]
        if event_limit is not None:
            session_filter = "session = ?" if session is not None else "1 = 1"
            since_filter = " AND ts >= ?" if since is not None else ""
            params: list[Any] = [session] if session is not None else []
            if since is not None:
                params.append(since)
            params.append(event_limit)
            details = "details_json" if "details_json" in columns else "NULL"
            events_query = (
                "SELECT id,ts,kind,bytes_out,session,"  # noqa: S608 - schema-selected SQL.
                f"{('outcome' if 'outcome' in columns else chr(39) + 'ok' + chr(39))},"
                f"{details} FROM query_log WHERE {session_filter}{since_filter} "
                "ORDER BY ts DESC,id DESC LIMIT ?"
            )
            event_rows = conn.execute(events_query, params)
            for row in event_rows:
                try:
                    value = json.loads(row[6]) if row[6] else None
                except TypeError, json.JSONDecodeError:
                    value = None
                events.append(
                    {
                        "id": row[0],
                        "ts": row[1],
                        "kind": row[2],
                        "bytes_out": row[3],
                        "session": row[4],
                        "outcome": row[5],
                        "details": value,
                    }
                )
    captures = sum(row["captures"] for row in by_kind)
    bytes_in = sum(row["bytes_in"] for row in by_kind)
    bytes_out = sum(row["bytes_out"] for row in by_kind)
    queries = sum(row["queries"] for row in by_query_kind)
    query_bytes = sum(row["bytes_out"] for row in by_query_kind)
    stored = conn.execute("SELECT COUNT(*) FROM captures").fetchone()[0]
    page_size, page_count = (
        conn.execute("PRAGMA page_size").fetchone()[0],
        conn.execute("PRAGMA page_count").fetchone()[0],
    )
    return (
        {
            "captures": captures,
            "bytes_in": bytes_in,
            "bytes_out": bytes_out,
            "by_kind": by_kind,
            "queries": queries,
            "query_bytes": query_bytes,
            "by_query_kind": by_query_kind,
            "net_saved_bytes": bytes_in - bytes_out - query_bytes,
            "stored_captures": stored,
            "db_bytes": page_size * page_count,
        },
        events,
    )


def _fmt_bytes(size: int) -> str:
    return f"{size:,} bytes"


def _trunc_div(numerator: int, denominator: int) -> int:
    magnitude = abs(numerator) // denominator
    return -magnitude if numerator < 0 else magnitude


def _print_stats(rows, args, window: str) -> None:
    if not rows:
        print(f"varde-toz: no store yet ({window})")
        return
    for key, stats, events in rows:
        if args.global_stats:
            print(f"== {key} ==")
        saved = stats["net_saved_bytes"]
        pct = _trunc_div(saved * 100, stats["bytes_in"]) if stats["bytes_in"] else 0
        net = ("-" + _fmt_bytes(-saved)) if saved < 0 else _fmt_bytes(saved)
        print(
            f"{window}: {stats['captures']} captures, "
            f"{_fmt_bytes(stats['bytes_in'])} in → "
            f"{_fmt_bytes(stats['bytes_out'])} preview + "
            f"{_fmt_bytes(stats['query_bytes'])} query readback "
            f"({stats['queries']} queries); net savings {net} "
            f"({pct}% of input, ~{_trunc_div(saved, 4)} tokens at bytes/4)"
        )
        for row in stats["by_kind"]:
            print(
                f"  {row['kind']:<14} {row['captures']:>5}  "
                f"{_fmt_bytes(row['bytes_in']):>14} → "
                f"{_fmt_bytes(row['bytes_out'])}"
            )
        for row in stats["by_query_kind"]:
            print(
                f"  query:{row['kind']:<8} {row['queries']:>5}  "
                f"{_fmt_bytes(row['bytes_out'])} read back"
            )
        if args.events is not None:
            for event in events:
                event_details = (
                    json.dumps(event["details"], separators=(",", ":"), sort_keys=True)
                    if event["details"] is not None
                    else "null"
                )
                print(
                    f"  {event['ts']} query:{event['kind']} "
                    f"{event['outcome']} {_fmt_bytes(event['bytes_out'])} "
                    f"read back {event_details}"
                )
        print(
            f"store: {stats['stored_captures']} captures on disk, "
            f"{_fmt_bytes(stats['db_bytes'])} DB"
        )


def main(argv: list[str] | None = None) -> int:
    values = sys.argv[1:] if argv is None else argv
    if "--help" in values or "-h" in values:
        print(HELP, end="")
        return 0
    try:
        args = _parser().parse_args(values)
    except SystemExit as exc:
        return 0 if exc.code is None else int(exc.code)
    if args.events is not None and not 1 <= args.events <= 10_000:
        return error("--events must be between 1 and 10000")
    if args.fallback_dir and os.environ.get("TOZ_FALLBACK_DIR") is None:
        os.environ["TOZ_FALLBACK_DIR"] = args.fallback_dir
    try:
        root = current_project(args.project)
        paths = (
            all_stores(root)
            if args.global_stats
            else [(project_key(root), current_store(root))]
        )
        session = env_os("TOZ_SESSION")
        if not session:
            session = None
        since = None
        if args.session and not session:
            since = int(time.time()) - 8 * 3600
        rows = []
        for key, path in paths:
            if not path.is_file():
                continue
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            stats, events = _aggregate(
                conn, session if args.session else None, since, args.events
            )
            conn.close()
            stats["project"] = key
            if args.events is not None:
                stats["events"] = events
            saved = stats["net_saved_bytes"]
            stats["tokens_saved_estimate"] = _trunc_div(saved, 4)
            stats["reduction_pct"] = (
                _trunc_div(saved * 100, stats["bytes_in"])
                if stats["bytes_in"] > 0
                else 0
            )
            rows.append((key, stats, events))
        window = (
            f"session {session}"
            if args.session and session
            else "last 8 hours"
            if args.session
            else "all time"
        )
        if json_enabled(args):
            print(
                json.dumps(
                    [stats for _, stats, _ in rows],
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
        else:
            _print_stats(rows, args, window)
    except (OSError, ValueError, sqlite3.Error) as exc:
        return error(str(exc))
    else:
        return 0
