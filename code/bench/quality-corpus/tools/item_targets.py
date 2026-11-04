"""Print one item's measured sizes and allowed size bands in one call.

For every variant file present in the item directory, print whole-file tokens,
function count, and per-function tokens and rows measured with the checker's
own extractor.  Then print the allowed band for each variant that is missing or
out of band.  Bands are measured by probing ``item_spec_rules``' own rule
functions with synthetic versions, so the numbers come from the checker and
cannot drift from it.

When all six variants exist, the checker's own findings are printed too (the
``missing_version`` findings are dropped).  A partially written item has no
cross-version findings, because ``check_item`` reports only the missing
versions then; the printed bands are its per-file targets.

Exit codes: ``0`` for every print run, ``2`` for a usage error.
"""

from __future__ import annotations

import argparse
import json
import textwrap
import tomllib
from dataclasses import dataclass
from pathlib import Path

from item_spec_check import select_language
from item_spec_extract import Function, SourceSyntaxError, extract
from item_spec_languages import ALT_VERSIONS, EXTENSIONS, VERSIONS
from item_spec_metrics import depth, graph, whole_file_tokens
from item_spec_rules import (
    ItemState,
    _entry,
    _rule_alt,
    _rule_forwarders,
    _rule_monolith,
    _rule_padded,
    _rule_sensible,
    _rule_sizematched,
    _rule_tree,
    check_item,
)

ENTRY = "solution"
UNBOUNDED = 10**9
PARSE_ERRORS = (SyntaxError, SourceSyntaxError, RuntimeError, OSError, ValueError)
WRAP = 150
INDENT = "  "


@dataclass(frozen=True)
class Band:
    """One allowed band: compared against measurements and shown as text."""

    field: str
    text: str
    low: float | None = None
    high: float | None = None


# --- band probes ------------------------------------------------------------


def _function(
    name: str, tokens: int, rows: int = 2, calls: list[str] | None = None
) -> Function:
    return Function(name, tokens, rows, list(calls or []), 0, f"sig({name})")


def _chain(links: int) -> list[Function]:
    names = [ENTRY, *(f"step{index}" for index in range(links))]
    return [
        _function(name, 20, 2, names[index + 1 : index + 2])
        for index, name in enumerate(names)
    ]


def _fanout(count: int) -> list[Function]:
    helpers = [f"step{index}" for index in range(count)]
    return [_function(ENTRY, 20, 2, helpers)] + [
        _function(name, 20) for name in helpers
    ]


def _tokens(entry_tokens: int, helper_tokens: int) -> list[Function]:
    return [_function(ENTRY, entry_tokens, 2, ["helper0"])] + [
        _function(f"helper{index}", helper_tokens) for index in range(3)
    ]


def _rows(rows: int) -> list[Function]:
    return [_function(ENTRY, 40, rows, ["helper0"]), _function("helper0", 40, rows)]


def _state(
    profile: str | None, language: str, versions: dict[str, tuple[list[Function], str]]
) -> ItemState:
    alts = tuple(name for name in versions if name in ALT_VERSIONS)
    functions = {name: [] for name in (*VERSIONS, *alts)}
    sources = dict.fromkeys((*VERSIONS, *alts), "")
    for name, (items, source) in versions.items():
        functions[name], sources[name] = items, source
    calls = {name: graph(items) for name, items in functions.items()}
    entries = {
        name: _entry(items, calls[name], ENTRY) for name, items in functions.items()
    }
    return ItemState(
        language=language,
        sources=sources,
        functions=functions,
        calls=calls,
        entries=entries,
        profile=profile,
        alts=alts,
    )


def _rule_findings(
    version: str, profile: str | None, language: str, versions
) -> list[dict]:
    state = _state(profile, language, versions)
    findings: list[dict] = []
    if version == "sensible":
        _rule_sensible(findings, state)
    elif version == "monolith":
        _rule_monolith(findings, state)
    elif version == "sizematched":
        _rule_sizematched(findings, state)
    elif version == "padded":
        _rule_padded(findings, state)
    elif version == "tiny":
        _rule_tree(findings, state, "tiny")
        _rule_forwarders(findings, state)
    elif version in ALT_VERSIONS:
        _rule_alt(findings, state)
    else:
        _rule_tree(findings, state, version)
    return findings


def _limit(version: str, kind: str, profile: str | None, language: str, versions):
    findings = _rule_findings(version, profile, language, versions)
    return next(
        (finding["limit"] for finding in findings if finding["kind"] == kind), None
    )


def _number(value: float | None) -> str:
    if value is None:
        return "unknown"
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def _parse_span(limit) -> tuple[float | None, float | None]:
    if not isinstance(limit, str) or "-" not in limit:
        return None, None
    low, _, high = limit.partition("-")
    try:
        return float(low), float(high)
    except ValueError:
        return None, None


def _parse_tolerance(limit) -> tuple[float | None, float | None]:
    """Read a ``1180 ±10%`` limit as an inclusive range."""
    if not isinstance(limit, str) or "±" not in limit:
        return None, None
    value, _, percent = limit.partition(" ±")
    try:
        center, share = float(value), float(percent.rstrip("%")) / 100
    except ValueError:
        return None, None
    return center * (1 - share), center * (1 + share)


def _span_text(low: float | None, high: float | None) -> str:
    if low is None:
        return "unknown"
    if high is None or high >= UNBOUNDED:
        return f"{_number(low)} and up"
    return f"{_number(low)}-{_number(high)}"


def _span_band(name: str, limit, label: str) -> Band:
    """Band written by the checker as ``low-high``."""
    low, high = _parse_span(limit)
    return Band(name, f"{label} {_span_text(low, high)}", low, high)


def _least_band(name: str, limit, label: str) -> Band:
    """Band written by the checker as a single minimum, e.g. ``>=3``."""
    if not isinstance(limit, str) or not limit.startswith(">="):
        return Band(name, f"{label} unknown")
    low = float(limit.removeprefix(">="))
    return Band(name, f"{label} >={_number(low)}", low, None)


def _most_band(name: str, limit, label: str) -> Band:
    """Band written by the checker as a single inclusive maximum, e.g. ``<=6``."""
    value = limit.removeprefix("<=") if isinstance(limit, str) else limit
    try:
        high = float(value)
    except TypeError, ValueError:
        return Band(name, f"{label} unknown")
    return Band(name, f"{label} <={_number(high)}", None, high)


def _sensible_bands(profile: str | None, language: str) -> list[Band]:
    def probe(kind: str, functions: list[Function]):
        return _limit(
            "sensible", kind, profile, language, {"sensible": (functions, "")}
        )

    bands = [
        _span_band("count", probe("sensible_function_count", []), "functions"),
        _span_band(
            "functions",
            probe("sensible_function_tokens", [_function(ENTRY, 1)]),
            "tokens",
        ),
        _most_band("depth", probe("sensible_call_depth", _chain(10)), "depth"),
    ]
    if profile == "layered":
        bands.append(
            _most_band("fanout", probe("sensible_entry_fanout", _fanout(12)), "fanout")
        )
    return bands


def _tree_bands(version: str, profile: str | None, language: str) -> list[Band]:
    def probe(kind: str, functions: list[Function]):
        return _limit(version, kind, profile, language, {version: (functions, "")})

    bands = [
        _span_band("count", probe(f"{version}_function_count", []), "functions"),
        _span_band(
            "entry", probe(f"{version}_function_tokens", _tokens(1, 60)), "tokens"
        ),
        _span_band(
            "functions",
            probe(f"{version}_function_tokens", _tokens(60, 1)),
            "helper tokens",
        ),
        _most_band("rows", probe(f"{version}_function_lines", _rows(200)), "rows"),
        _span_band("depth", probe(f"{version}_chain_depth", _chain(20)), "depth"),
        _span_band("fanout", probe(f"{version}_entry_fanout", _fanout(12)), "fanout"),
    ]
    if version == "tiny":
        bands.append(
            _least_band(
                "forwarders",
                _limit(
                    "tiny", "tiny_forwarders", profile, language, {"tiny": ([], "")}
                ),
                "forwarders",
            )
        )
    return bands


def _padded_bands(profile: str | None, language: str) -> list[Band]:
    def probe(kind: str, functions: list[Function]):
        return _limit("padded", kind, profile, language, {"padded": (functions, "")})

    bands = []
    if profile == "layered":
        bands.append(
            _span_band("count", probe("padded_function_count", []), "functions")
        )
    bands.extend(
        [
            _span_band("entry", probe("padded_entry_tokens", _tokens(1, 60)), "tokens"),
            _span_band(
                "functions",
                probe("padded_function_tokens", _tokens(60, 1)),
                "helper tokens",
            ),
        ]
    )
    if profile == "layered":
        bands.append(
            _span_band("depth", probe("padded_chain_depth", _chain(20)), "depth")
        )
        bands.append(
            _span_band("fanout", probe("padded_entry_fanout", _fanout(12)), "fanout")
        )
    else:
        bands.append(Band("shape", "same shape and helper names as tiny"))
    return bands


def _monolith_bands(
    profile: str | None, language: str, sensible: tuple[list[Function], str] | None
) -> list[Band]:
    if sensible is None:
        return [Band("file", "file tokens need sensible first")]
    functions, source = sensible
    shared = {"sensible": (functions, source)}

    def probe(kind: str, versions):
        return _limit("monolith", kind, profile, language, {**shared, **versions})

    floor = probe("monolith_file_tokens", {"monolith": ([_function(ENTRY, 1)], "")})
    bands = [_least_band("file", floor, "file tokens")]
    if profile == "layered":
        wide = "a " * (3 * whole_file_tokens(source) + 1)
        ceiling = probe(
            "monolith_file_tokens_high",
            {"monolith": ([_function(ENTRY, UNBOUNDED, 500)], wide)},
        )
        bands.append(_most_band("ceiling", ceiling, "file ceiling"))
    floor_functions = probe(
        "monolith_tokens", {"monolith": ([_function(ENTRY, 1)], "")}
    )
    bands.append(
        Band("functions", f"function tokens {_checked_limit(floor_functions)}")
    )
    return bands


def _checked_limit(limit) -> str:
    return "unknown" if limit is None else str(limit)


def _sizematched_bands(
    profile: str | None, language: str, sensible: tuple[list[Function], str] | None
) -> list[Band]:
    if sensible is None:
        return [Band("file", "file tokens need sensible first")]
    functions, source = sensible
    shared = {"sensible": (functions, source)}

    def probe(kind: str, versions):
        return _limit("sizematched", kind, profile, language, {**shared, **versions})

    file_limit = probe("sizematched_file_tokens", {"sizematched": ([], "")})
    token_limit = probe(
        "sizematched_tokens", {"sizematched": ([_function(ENTRY, 1)], "")}
    )
    return [
        Band(
            "file",
            f"file tokens {_checked_limit(file_limit)}",
            *_parse_tolerance(file_limit),
        ),
        Band(
            "functions",
            f"function tokens {_checked_limit(token_limit)}",
            *_parse_tolerance(token_limit),
        ),
    ]


def _alt_bands(version: str, language: str) -> list[Band]:
    """Alt versions take the layered sensible limits, whatever the item profile."""

    def probe(kind: str, functions: list[Function]):
        return _limit(version, kind, "layered", language, {version: (functions, "")})

    return [
        _span_band("count", probe("alt_function_count", []), "functions"),
        _span_band(
            "functions",
            probe("alt_function_tokens", [_function(ENTRY, 1)]),
            "tokens",
        ),
        _most_band("depth", probe("alt_call_depth", _chain(10)), "depth"),
        _most_band("fanout", probe("alt_entry_fanout", _fanout(12)), "fanout"),
    ]


def variant_bands(
    language: str,
    profile: str | None,
    sensible: tuple[list[Function], str] | None,
    alts: tuple[str, ...] = (),
) -> dict[str, list[Band]]:
    bands = {
        "sensible": _sensible_bands(profile, language),
        "monolith": _monolith_bands(profile, language, sensible),
        "tiny": _tree_bands("tiny", profile, language),
        "padded": _padded_bands(profile, language),
        "sizematched": _sizematched_bands(profile, language, sensible),
        "namematched": _tree_bands("namematched", profile, language),
    }
    for name in alts:
        bands[name] = _alt_bands(name, language)
    forwarders = next(
        (band for band in bands["tiny"] if band.field == "forwarders"), None
    )
    if forwarders is not None:
        bands["namematched"].append(forwarders)
    return bands


# --- item loading -----------------------------------------------------------


def _language(item: Path) -> str | None:
    selected = select_language(item, None)
    if selected is not None:
        return selected
    for name, extension in EXTENSIONS.items():
        if any((item / f"{version}{extension}").is_file() for version in VERSIONS):
            return name
    return None


def _profile(item: Path) -> str | None:
    path = item / "spec-profile.toml"
    if not path.is_file():
        return None
    try:
        return tomllib.loads(path.read_text()).get("profile")
    except tomllib.TOMLDecodeError, OSError:
        return None


def _measured(functions: list[Function]) -> list[dict]:
    return [
        {"name": function.name, "tokens": function.tokens, "rows": function.lines}
        for function in functions
    ]


def _measure(
    item: Path, language: str, alts: tuple[str, ...] = ()
) -> tuple[dict[str, dict], dict, dict]:
    """Return per-variant measurements, parsed functions, and sources."""
    variants: dict[str, dict] = {}
    parsed: dict[str, list[Function]] = {}
    sources: dict[str, str] = {}
    for name in (*VERSIONS, *alts):
        path = item / f"{name}{EXTENSIONS[language]}"
        variant = {"present": path.is_file(), "file_tokens": None, "functions": []}
        if variant["present"]:
            try:
                source = path.read_text()
                functions = extract(language, source)
            except PARSE_ERRORS as error:
                variant["error"] = f"{type(error).__name__}: {error}"
            else:
                parsed[name] = functions
                sources[name] = source
                variant["file_tokens"] = whole_file_tokens(source)
                variant["functions"] = _measured(functions)
                calls = graph(functions)
                entry = _entry(functions, calls, ENTRY)
                variant["entry"] = entry.name if entry else ""
                variant["depth"] = depth(calls, entry.name) if entry else 0
                variant["fanout"] = len(calls.get(entry.name, [])) if entry else 0
        variants[name] = variant
    return variants, parsed, sources


def _violations(variant: dict, bands: list[Band]) -> list[str]:
    found: list[str] = []

    def outside(name: str, value: float | None) -> bool:
        band = next((item for item in bands if item.field == name), None)
        if band is None or value is None or (band.low is None and band.high is None):
            return False
        return (band.low is not None and value < band.low) or (
            band.high is not None and value > band.high
        )

    def flag(text: str) -> None:
        found.append(text)

    if outside("file", variant["file_tokens"]):
        flag(f"file tokens {variant['file_tokens']}")
    if outside("count", len(variant["functions"])):
        flag(f"functions {len(variant['functions'])}")
    if outside("depth", variant["depth"]):
        flag(f"depth {variant['depth']}")
    if outside("fanout", variant["fanout"]):
        flag(f"fanout {variant['fanout']}")
    for function in variant["functions"]:
        name = "entry" if function["name"] == variant["entry"] else "functions"
        if outside(name, function["tokens"]) or outside(
            "functions", function["tokens"]
        ):
            flag(f"{function['name']} tokens {function['tokens']}")
        if outside("rows", function["rows"]):
            flag(f"{function['name']} rows {function['rows']}")
    return found


# --- report -----------------------------------------------------------------


def _alt_names(item: Path, language: str) -> tuple[str, ...]:
    """Read every alt version file present, declared or not, so it can be sized."""
    return tuple(
        name
        for name in ALT_VERSIONS
        if (item / f"{name}{EXTENSIONS[language]}").is_file()
    )


def build_report(item: Path) -> dict:
    language = _language(item)
    profile = _profile(item)
    alts = _alt_names(item, language)
    variants, parsed, sources = _measure(item, language, alts)
    sensible = (
        (parsed["sensible"], sources["sensible"]) if "sensible" in parsed else None
    )
    bands = variant_bands(language, profile, sensible, alts)
    for name, variant in variants.items():
        variant["bands"] = [band.text for band in bands[name]]
        variant["violations"] = (
            _violations(variant, bands[name]) if name in parsed else []
        )
    complete = all(
        variant["present"] and "error" not in variant for variant in variants.values()
    )
    findings = []
    if complete:
        found, _ = check_item(item, language)
        findings = [
            finding for finding in found if finding["kind"] != "missing_version"
        ]
    return {
        "item": str(item),
        "language": language,
        "profile": profile or "small",
        "variants": variants,
        "findings": findings,
        "findings_complete": complete,
    }


def _status(variant: dict) -> str:
    if not variant["present"]:
        return "missing"
    if "error" in variant:
        return "unparsable"
    return "drift" if variant["violations"] else "ok"


def _print_table(report: dict) -> None:
    print(
        f"item {report['item']}  language={report['language']}"
        f"  profile={report['profile']}"
    )
    print(f"{'VARIANT':<13}{'TOKENS':>7}{'FUNCS':>7}  STATUS")
    for name, variant in report["variants"].items():
        tokens = variant["file_tokens"]
        count = len(variant["functions"]) if "error" not in variant else None
        count = count if variant["present"] else None
        print(
            f"{name:<13}{tokens if tokens is not None else '-':>7}"
            f"{count if count is not None else '-':>7}  {_status(variant)}"
        )


def _print_bands(report: dict) -> None:
    lines = [
        _band_line(name, variant)
        for name, variant in report["variants"].items()
        if _status(variant) in {"missing", "drift"}
    ]
    if not lines:
        return
    print("targets:")
    print("\n".join(textwrap.fill(line, WRAP) for line in lines))


def _band_line(name: str, variant: dict) -> str:
    found = variant["violations"]
    now = ""
    if found:
        more = f" +{len(found) - 3} more" if len(found) > 3 else ""
        now = f"  (now: {', '.join(found[:3])}{more})"
    return f"{INDENT}{name}: {'; '.join(variant['bands'])}{now}"


def _print_functions(report: dict) -> None:
    lines = []
    for name, variant in report["variants"].items():
        if not variant["functions"]:
            continue
        parts = [
            f"{f['name']} {f['tokens']}t/{f['rows']}r" for f in variant["functions"]
        ]
        lines.append(textwrap.fill(f"{INDENT}{name}: {' '.join(parts)}", WRAP))
    if lines:
        print("functions:")
        print("\n".join(lines))


def _print_findings(report: dict) -> None:
    if not report["findings_complete"]:
        print("checker: findings need all six variants; bands above are the targets")
        return
    if not report["findings"]:
        print("checker: all six variants clean")
        return
    for name in report["variants"]:
        found = [f for f in report["findings"] if f["version"] == name]
        if not found:
            continue
        shown = "; ".join(_finding_text(finding) for finding in found[:3])
        more = f" +{len(found) - 3} more" if len(found) > 3 else ""
        print(textwrap.fill(f"{INDENT}{name}: {shown}{more}", WRAP))


def _finding_text(finding: dict) -> str:
    target = (
        f"{finding['kind']}({finding['function']})"
        if finding["function"]
        else finding["kind"]
    )
    text = f"{target} {finding['value']} limits {finding['limit']}"
    return text if len(text) <= 60 else f"{text[:57]}..."


def print_report(report: dict) -> None:
    _print_table(report)
    _print_bands(report)
    _print_functions(report)
    _print_findings(report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("item", type=Path, help="item directory holding the variants")
    parser.add_argument("--json", action="store_true", help="print one JSON document")
    args = parser.parse_args(argv)
    if not args.item.is_dir():
        parser.error(f"item directory does not exist: {args.item}")
    if _language(args.item) is None:
        parser.error(f"no variant files found in: {args.item}")
    report = build_report(args.item)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
