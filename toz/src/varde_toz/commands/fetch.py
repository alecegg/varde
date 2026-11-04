"""`fetch` command."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from varde_toz import fetch as fetch_core
from varde_toz import metadata
from varde_toz.capture import CaptureInput, capture
from varde_toz.chunk import strip_ansi
from varde_toz.config import config_dir, env_os
from varde_toz.project import project_key, project_root
from varde_toz.redact_toz import configured_redactor, redact_configured
from varde_toz.store import Store

HELP = """Fetch web pages as readable text and index them (24 h disk cache)

Usage: varde run fetch [OPTIONS] <URLS>...

Arguments:
  <URLS>...  

Options:
      --fallback-dir <FALLBACK_DIR>  External store to try after primary-store access fails
  -l, --label <LABEL>                Human label (single URL only; also the supersession key)
      --project <PROJECT>            Project directory (default: git root of cwd, else cwd)
      --ttl <TTL>                    Cache TTL in seconds (default 86400); 0 always refetches
      --force                        Ignore the cache
      --json                         Machine-readable JSON output
  -c, --concurrency <CONCURRENCY>    Parallel fetches [default: 4]
      --quiet                        Print only the handle line on overflow
  -h, --help                         Print help
"""


def _safe_url(url: str) -> str:
    redactor = configured_redactor(Path.cwd())
    return metadata.sanitize_url(url, lambda value: redact_configured(value, redactor))


def _cached_report(
    fetched: fetch_core.Fetched, root: Path
) -> tuple[str, str, int] | None:
    if not fetched.from_cache or fetched.meta.get(
        "project_key"
    ) != metadata.project_identity(project_key(root), config_dir()):
        return None
    handle = fetched.meta.get("handle")
    if not handle:
        return None
    from varde_toz.project import store_db_path

    path = store_db_path(root, config_dir())
    try:
        with Store.open(path) as store:
            row = store.get_by_handle(handle)
            if row is None or row["superseded_by"] is not None:
                return None
            age = max(0, int(time.time()) - int(fetched.meta["fetched_at"]))
            return str(handle), _format_age(age), int(row["chunk_count"])
    except OSError:
        return None


def _format_age(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _emit_preview(
    output: str,
    args,
    url: str,
    fetched: fetch_core.Fetched | None = None,
    cache_hit: tuple[str, str, int] | None = None,
) -> str:
    json_output = args.json or env_os("TOZ_JSON") not in (None, "", "0", "false")
    quiet = args.quiet or env_os("TOZ_QUIET") not in (None, "", "0", "false")
    if cache_hit:
        if fetched is None:
            raise AssertionError("cache hit requires fetched metadata")
        handle, age, chunks = cache_hit
        if json_output:
            return (
                json.dumps(
                    {
                        "handle": handle,
                        "cached": True,
                        "fetched_at": fetched.meta["fetched_at"],
                        "url": _safe_url(url),
                    },
                    separators=(",", ":"),
                )
                + "\n"
            )
        return (
            f"varde-toz: cached {age} ago → handle {handle} ({chunks} chunks)   next: "
            f'varde run query --handle {handle} "<query>"   |   '
            f"varde run query --handle {handle} --chunk N\n"
        )
    if output:
        if json_output:
            return (
                json.dumps(
                    {"preview": output}, separators=(",", ":"), ensure_ascii=False
                )
                + "\n"
            )
        if quiet:
            return (output.splitlines()[0] if output.splitlines() else "") + "\n"
        return output
    return ""


def _store_fetch(
    fetched: fetch_core.Fetched, root: Path, label: str | None, args
) -> tuple[int, str]:
    cache_hit = _cached_report(fetched, root)
    if cache_hit:
        return 0, ""
    capture_result = capture(
        CaptureInput(
            fetched.text.encode(),
            label=label,
            source=fetched.request_url,
            kind="fetch",
            force=True,
        ),
        root,
    )
    status, output = capture_result.status, capture_result.output
    if status:
        match = re.search(r"handle ([a-z2-9]{4,})", output)
        if match:
            fetched.meta["handle"] = match.group(1)
            fetched.meta["project_key"] = metadata.project_identity(
                project_key(root), config_dir()
            )
            redactor = configured_redactor(root)
            fetched.text = redact_configured(strip_ansi(fetched.text), redactor)[0]
            fetch_core.cache_put(fetched)
    return status, output


def main(argv: list[str]) -> int:
    if "--help" in argv or "-h" in argv:
        print(HELP, end="")
        return 0
    if "-j" in argv:
        print(
            (
                "error: unexpected argument '-j' found\n\n  tip: to pass '-j' "
                "as a value, use '-- -j'\n\nUsage: varde run fetch [OPTIONS] "
                "<URLS>...\n\nFor more information, try '--help'."
            ),
            file=sys.stderr,
        )
        return 2
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("urls", nargs="+")
    parser.add_argument("-l", "--label")
    parser.add_argument("--ttl", type=int, default=fetch_core.DEFAULT_TTL_SECS)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("-c", "--concurrency", type=int, default=4)
    parser.add_argument("--fallback-dir")
    parser.add_argument("--project")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code is None else int(exc.code)
    if args.ttl < 0:
        print(
            "error: invalid value '"
            + str(args.ttl)
            + (
                "' for '--ttl <TTL>': invalid digit found in string\n\n"
                "For more information, try '--help'."
            ),
            file=sys.stderr,
        )
        return 2
    if args.concurrency < 0:
        print(
            (
                f"error: unexpected argument '{args.concurrency}' found\n\n  tip: "
                f"to pass '{args.concurrency}' as a value, use '-- "
                f"{args.concurrency}'\n\nUsage: varde run fetch [OPTIONS] "
                "<URLS>...\n\nFor more information, try '--help'."
            ),
            file=sys.stderr,
        )
        return 2
    root = Path(args.project).resolve() if args.project else project_root()
    urls = [fetch_core.normalize_url(url) for url in args.urls]
    label = args.label if len(urls) == 1 else None
    if len(urls) > 1 and args.label:
        print("varde-toz: --label ignored for multiple URLs")
    worst = 0

    def persist_report(
        url: str, fetched: fetch_core.Fetched | None
    ) -> tuple[str, str, int]:
        if fetched is None:
            return f"varde-toz: fetch failed for {_safe_url(url)}\n", "", 1
        hit = _cached_report(fetched, root)
        if hit:
            return _emit_preview("", args, url, fetched, hit), "", 0
        try:
            status, output = _store_fetch(fetched, root, label, args)
        except (OSError, ValueError, RuntimeError) as exc:
            return "", f"varde-toz: {exc}\n", 1
        return (_emit_preview(output, args, url, fetched) if status else ""), "", 0

    reports = _fetch_ordered(
        urls, args.concurrency, lambda url: _fetch_safely(url, args), persist_report
    )
    for url, (stdout, stderr, status) in zip(urls, reports, strict=False):
        if len(urls) > 1:
            print(f"=== {_safe_url(url)} ===")
        sys.stdout.write(stdout)
        sys.stderr.write(stderr)
        worst = max(worst, status)
    return worst


def _fetch_safely(url: str, args):
    try:
        return fetch_core.fetch(url, args.ttl, args.force)
    except OSError, ValueError, TimeoutError:
        return None


FetchValue = TypeVar("FetchValue")
ReportValue = TypeVar("ReportValue")


def _fetch_ordered[FetchValue, ReportValue](
    urls: list[str],
    concurrency: int,
    fetch_one: Callable[[str], FetchValue],
    persist_one: Callable[[str, FetchValue], ReportValue],
) -> list[ReportValue]:
    """Fetch and persist within a bounded worker window, returning reports in URL
    order.
    """
    if not urls:
        return []
    workers = max(1, min(concurrency, len(urls)))
    results: list[ReportValue | None] = [None] * len(urls)
    next_index = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        pending: dict[concurrent.futures.Future[FetchValue], int] = {}

        def submit_next() -> bool:
            nonlocal next_index
            if next_index >= len(urls):
                return False
            index = next_index
            next_index += 1
            pending[pool.submit(fetch_one, urls[index])] = index
            return True

        for _ in range(workers):
            submit_next()
        while pending:
            done, _ = concurrent.futures.wait(
                pending, return_when=concurrent.futures.FIRST_COMPLETED
            )
            for future in done:
                index = pending.pop(future)
                results[index] = persist_one(urls[index], future.result())
            for _ in done:
                submit_next()
    return [result for result in results if result is not None]
