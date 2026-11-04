"""Argument parsing, source fan-out, result ordering, and search output."""

import argparse
import re
import sys
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import NoReturn

from varde_core.envelope import success

from .types import SearchHit, SearchQuery, SearchSource, SourceResult

SOURCE_ORDER = ("code", "docs", "knowledge", "plans", "output", "friction")
_SERIAL_SOURCES = frozenset({"docs", "plans"})
_USAGE = "Usage: varde search [OPTIONS] <query>"


class _SearchParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        source = re.search(r"invalid source: (.+)", message)
        limit = re.search(r"argument --limit: invalid value '([^']*)'", message)
        if source:
            error = (
                f"error: invalid value '{source.group(1)}' for '--in <in>'\n"
                f"  [possible values: {', '.join(SOURCE_ORDER)}]"
            )
        elif limit:
            value = limit.group(1)
            reason = (
                "0 is not in 1..=4294967295"
                if value.isdigit() and int(value) == 0
                else "invalid digit found in string"
                if not value.isdigit()
                else "number too large to fit in target type"
            )
            error = f"error: invalid value '{value}' for '--limit <limit>': {reason}"
        elif "unrecognized arguments:" in message:
            argument = (
                message.partition("unrecognized arguments:")[2].strip().split()[0]
            )
            error = f"error: unexpected argument '{argument}' found\n\n{_USAGE}"
        elif "required: query" in message:
            error = (
                "error: the following required arguments were not provided:\n  <query>"
            )
        else:
            error = f"error: {message}\n\n{_USAGE}"
        sys.stderr.write(f"{error}\n\nFor more information, try '--help'.\n")
        raise SystemExit(2)


def parse_search_args(args: Sequence[str]) -> tuple[SearchQuery, tuple[str, ...], bool]:
    """Parse arguments following `varde search` and preserve Rust source order."""
    parser = _SearchParser(prog="varde search")
    parser.add_argument("query", help="Text to search for")
    parser.add_argument("--in", dest="sources", help="Comma-separated sources")
    parser.add_argument(
        "--limit", type=_positive_limit, default=5, help="Most hits per source"
    )
    parser.add_argument(
        "--json", action="store_true", help="Print the machine-output envelope"
    )
    parsed = parser.parse_args(list(args))

    requested = tuple(parsed.sources.split(",")) if parsed.sources is not None else ()
    invalid = tuple(name for name in requested if name not in SOURCE_ORDER)
    if invalid:
        parser.error(f"invalid source: {', '.join(invalid)}")
    selected = tuple(
        name for name in SOURCE_ORDER if not requested or name in requested
    )
    return SearchQuery(parsed.query, parsed.limit), selected, parsed.json


def _positive_limit(value: str) -> int:
    try:
        limit = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"invalid value '{value}'") from error
    if limit < 1:
        raise argparse.ArgumentTypeError(f"invalid value '{value}'")
    return limit


def search_all(
    sources: Sequence[SearchSource], query: SearchQuery
) -> list[SourceResult]:
    """Search adapters concurrently, serializing docs and plans on their shared
    store.
    """
    serial = [source for source in sources if source.source() in _SERIAL_SOURCES]
    parallel = [source for source in sources if source.source() not in _SERIAL_SOURCES]
    results: list[SourceResult] = []
    with ThreadPoolExecutor(max_workers=max(1, len(parallel))) as executor:
        futures = [
            (source, executor.submit(_search, source, query)) for source in parallel
        ]
        results.extend(_search(source, query) for source in serial)
        results.extend(
            result for _, future in futures if (result := future.result()) is not None
        )
    results.sort(
        key=lambda result: (
            SOURCE_ORDER.index(result.source)
            if result.source in SOURCE_ORDER
            else len(SOURCE_ORDER)
        )
    )
    return results


def _search(source: SearchSource, query: SearchQuery) -> SourceResult:
    try:
        return source.search(query)
    except Exception as error:
        return SourceResult.unavailable(source.source(), str(error))


def _hit_json(hit: SearchHit) -> dict[str, object]:
    return {
        "source": hit.source,
        "title": hit.title,
        "location": hit.location,
        "snippet": hit.snippet,
        "score": hit.score,
    }


def _group_json(result: SourceResult) -> dict[str, object]:
    if result.reason is not None:
        return {
            "source": result.source,
            "status": "unavailable",
            "reason": result.reason,
            "hits": [],
        }
    return {
        "source": result.source,
        "status": "ok",
        "hits": [_hit_json(hit) for hit in result.hits or ()],
    }


def render_json(
    results: Sequence[SourceResult], query: SearchQuery
) -> dict[str, object]:
    """Build the success envelope used by `varde search --json`."""
    return success(
        {"groups": [_group_json(result) for result in results]},
        {"query": query.text, "limit": query.limit},
    )


def render_text(results: Sequence[SourceResult]) -> str:
    """Render grouped results with the Rust CLI's text layout."""
    output = []
    for result in results:
        if result.reason is not None:
            output.append(f"## {result.source} (unavailable)\n- {result.reason}\n")
            continue
        hits = result.hits or ()
        output.append(f"## {result.source} ({len(hits)})\n")
        for hit in hits:
            output.append(f"- {hit.title}  {hit.location}\n")
            snippet = hit.snippet.strip()
            if snippet:
                output.append(f"    {snippet.replace(chr(10), ' ')}\n")
    return "".join(output)
