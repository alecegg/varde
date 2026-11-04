"""Executable category (b) authoring rules.

``check_item`` loads an item once into an :class:`ItemState` and then runs one
short rule function per spec bullet, so each rule is directly testable.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from item_spec_comments import comment_shape
from item_spec_extract import ANONYMOUS, Function, extract
from item_spec_languages import ALT_VERSIONS, EXTENSIONS, VERSIONS
from item_spec_metrics import cyclic, depth, graph, reachable, row, whole_file_tokens
from item_spec_quality import source_findings

CATEGORY_WORDS = frozenset(
    {"hop", "core", "step", "stage", "tiny", "padded", "monolith", "sensible", "leaf"}
)
WORD_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Za-z])(?=[0-9])")
WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
IDENTITY_ASSIGNMENT = re.compile(
    r"^[ \t]*(?:[A-Za-z_][\w:<>,.\[\]?*& ]*[ \t]+)?([A-Za-z_]\w*)[ \t]*"
    r"(?::[^=\n]+)?=[ \t]*([A-Za-z_]\w*)[ \t]*;?[ \t]*$",
    re.MULTILINE,
)
TREE_VERSIONS = ("tiny", "padded", "namematched")
TREE_ROW_CAPS = {"default": 3, "go": 6}


def category_words(source: str) -> list[str]:
    """Return category words used as whole words in identifiers, comments or strings."""
    found = set()
    for token in WORD.findall(source):
        for word in WORD_BOUNDARY.sub(" ", token).replace("_", " ").split():
            normalized = word.lower()
            if normalized in CATEGORY_WORDS:
                found.add(normalized)
            elif normalized.rstrip("s") in CATEGORY_WORDS:
                found.add(normalized.rstrip("s"))
    return sorted(found)


@dataclass
class ItemState:
    language: str
    sources: dict[str, str]
    functions: dict[str, list[Function]]
    calls: dict[str, dict[str, list[str]]]
    entries: dict[str, Function | None]
    profile: str | None
    alts: tuple[str, ...] = ()

    @property
    def versions(self) -> tuple[str, ...]:
        return (*VERSIONS, *self.alts)


def declared_alts(item: Path, language: str) -> tuple[list[str], list[dict]]:
    """Return the alt version names whose files exist and declaration findings.

    ``spec-profile.toml`` ``alts`` lists the required alts; ``pair.json`` pairs
    whose side role is ``alt-good`` declare optional alts. Alts are optional, so
    only a profile-required alt that is missing is a finding.
    """
    findings: list[dict] = []
    required = _profile_alts(item, findings)
    names = list(dict.fromkeys([*required, *_pair_alts(item, findings)]))
    present: list[str] = []
    for name in names:
        if name not in ALT_VERSIONS:
            findings.append(
                _finding(
                    "unknown_alt",
                    name,
                    value=name,
                    limit=", ".join(ALT_VERSIONS),
                )
            )
            continue
        path = item / f"{name}{EXTENSIONS[language]}"
        if path.is_file():
            present.append(name)
            continue
        limit = "required" if name in required else "declared in pair.json"
        findings.append(_finding("missing_alt", name, str(path), limit))
    return present, findings


def _profile_alts(item: Path, findings: list[dict]) -> list[str]:
    path = item / "spec-profile.toml"
    if not path.is_file():
        return []
    try:
        names = tomllib.loads(path.read_text()).get("alts", [])
    except (tomllib.TOMLDecodeError, OSError) as error:
        findings.append(
            _finding("unreadable_profile", path.name, value=str(error), limit="TOML")
        )
        return []
    if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
        findings.append(
            _finding("invalid_alts", path.name, value=names, limit="list of alt names")
        )
        return []
    return names


def _pair_alts(item: Path, findings: list[dict]) -> list[str]:
    path = item / "pair.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as error:
        findings.append(
            _finding("unreadable_pair", path.name, value=str(error), limit="JSON")
        )
        return []
    pairs = data.get("pairs") if isinstance(data.get("pairs"), list) else [data]
    names: list[str] = []
    for entry in pairs:
        if not isinstance(entry, dict):
            continue
        for side in ("left", "right"):
            if entry.get(f"{side}_role") != "alt-good":
                continue
            name = Path(str(entry.get(side, ""))).stem
            if name == "sensible":
                findings.append(
                    _finding(
                        "alt_good_on_sensible",
                        path.name,
                        value=name,
                        limit="alt-good role on an alt version",
                    )
                )
                continue
            if name:
                names.append(name)
    return names


def check_item(item: Path, language: str) -> tuple[list[dict], list[str]]:
    paths = {name: item / f"{name}{EXTENSIONS[language]}" for name in VERSIONS}
    missing = [
        _finding("missing_version", name, value=str(path), limit="required")
        for name, path in paths.items()
        if not path.is_file()
    ]
    if missing:
        return missing, []
    alts, alt_findings = declared_alts(item, language)
    present = {
        **paths,
        **{name: item / f"{name}{EXTENSIONS[language]}" for name in alts},
    }
    state = _load(language, present, tuple(alts))
    return (
        alt_findings
        + _evaluate(state)
        + source_findings(item, language, state.sources, state.entries),
        _metrics(state),
    )


def _load(
    language: str, paths: dict[str, Path], alts: tuple[str, ...] = ()
) -> ItemState:
    profile_path = next(iter(paths.values())).parent / "spec-profile.toml"
    profile = (
        tomllib.loads(profile_path.read_text()).get("profile")
        if profile_path.is_file()
        else None
    )
    sources = {name: path.read_text() for name, path in paths.items()}
    functions = {name: extract(language, source) for name, source in sources.items()}
    calls = {name: graph(items) for name, items in functions.items()}
    entry_name = _shared_entry(functions, language)
    entries = {
        name: _entry(items, calls[name], entry_name)
        for name, items in functions.items()
    }
    return ItemState(language, sources, functions, calls, entries, profile, alts)


def _shared_entry(
    functions: dict[str, list[Function]], language: str = ""
) -> str | None:
    shared = set.intersection(
        *({f.name for f in items} for items in functions.values())
    )
    named = shared - {ANONYMOUS}
    preferred = ("Solution", "solution") if language == "go" else ("solution",)
    for name in preferred:
        if name in named:
            return name
    return next(iter(named)) if len(named) == 1 else None


def _entry(
    functions: list[Function], calls: dict[str, list[str]], preferred: str | None
) -> Function | None:
    named = next((f for f in functions if f.name == preferred), None)
    if named is None:
        named = next((f for f in functions if f.name == "solution"), None)
    if named:
        return named
    return max(functions, key=lambda f: len(calls.get(f.name, [])), default=None)


def _evaluate(state: ItemState) -> list[dict]:
    findings: list[dict] = []
    _rule_entry_names(findings, state)
    _rule_entry_signatures(findings, state)
    _rule_sensible(findings, state)
    _rule_alt(findings, state)
    _rule_monolith(findings, state)
    _rule_tree(findings, state, "tiny")
    _rule_tree(findings, state, "namematched")
    _rule_padded(findings, state)
    _rule_same_shape(findings, state, "namematched", "namematched_shape")
    _rule_helper_names(findings, state, "namematched", "namematched_names")
    _rule_forwarders(findings, state)
    _rule_sizematched(findings, state)
    _rule_redefinitions(findings, state)
    _rule_recursion(findings, state)
    _rule_comment_parity(findings, state)
    _rule_category_words(findings, state)
    return findings


def _rule_entry_names(findings: list[dict], state: ItemState) -> None:
    accepted_names = (
        {"solution", "Solution"} if state.language == "go" else {"solution"}
    )
    for version in state.versions:
        if any(f.name in accepted_names for f in state.functions[version]):
            continue
        entry = state.entries[version]
        findings.append(
            _finding(
                "entry_name",
                version,
                value=entry.name if entry else None,
                limit="solution or Solution" if state.language == "go" else "solution",
            )
        )


def _rule_entry_signatures(findings: list[dict], state: ItemState) -> None:
    signatures = {entry.signature for entry in state.entries.values() if entry}
    if len(signatures) <= 1:
        return
    findings.extend(
        _finding("entry_signature_parity", version, "solution", len(signatures), 1)
        for version in state.versions
    )


def _rule_sensible(findings: list[dict], state: ItemState) -> None:
    _rule_limits(findings, state, "sensible", state.profile == "layered", "sensible")


def _rule_alt(findings: list[dict], state: ItemState) -> None:
    for version in state.alts:
        _rule_limits(findings, state, version, True, "alt")
        entry = state.entries[version]
        calls = state.calls[version]
        if entry is None:
            continue
        dead = {name for name in calls if name not in reachable(calls, entry.name)}
        if dead:
            findings.append(
                _finding(
                    "alt_dead_code",
                    version,
                    ",".join(sorted(dead)),
                    sorted(dead),
                    "none",
                )
            )


def _rule_limits(
    findings: list[dict],
    state: ItemState,
    version: str,
    layered: bool,
    prefix: str,
) -> None:
    functions = state.functions[version]
    calls = state.calls[version]
    entry = state.entries[version]
    count_range = (7, 20) if layered else (2, 9) if state.language == "cpp" else (2, 6)
    if not count_range[0] <= len(functions) <= count_range[1]:
        findings.append(
            _finding(
                f"{prefix}_function_count",
                version,
                value=len(functions),
                limit=f"{count_range[0]}-{count_range[1]}",
            )
        )
    token_limit = 160 if layered else 100
    _check_tokens(
        findings,
        f"{prefix}_function_tokens",
        version,
        functions,
        30,
        token_limit,
    )
    if entry is not None and any(calls.get(name) for name in calls.get(entry.name, [])):
        depth_limit = 4 if layered else 2
        actual_depth = depth(calls, entry.name)
        if actual_depth > depth_limit:
            findings.append(
                _finding(
                    f"{prefix}_call_depth",
                    version,
                    entry.name,
                    actual_depth,
                    depth_limit,
                )
            )
    if layered and entry is not None:
        fanout = len(set(calls.get(entry.name, [])))
        if fanout > 6:
            findings.append(
                _finding(
                    f"{prefix}_entry_fanout",
                    version,
                    entry.name,
                    fanout,
                    "<=6",
                )
            )


def _rule_monolith(findings: list[dict], state: ItemState) -> None:
    functions = state.functions["monolith"]
    sensible_total = sum(f.tokens for f in state.functions["sensible"])
    sensible_file = whole_file_tokens(state.sources["sensible"])
    monolith_file = whole_file_tokens(state.sources["monolith"])
    layered = state.profile == "layered"
    minimum_ratio = 0.8 if layered else 1.3
    if monolith_file < sensible_file * minimum_ratio:
        findings.append(
            _finding(
                "monolith_file_tokens",
                "monolith",
                value=monolith_file,
                limit=f">={sensible_file * minimum_ratio:.1f}",
            )
        )
    if layered and monolith_file > sensible_file * 1.6:
        findings.append(
            _finding(
                "monolith_file_tokens_high",
                "monolith",
                value=monolith_file,
                limit=f"<={sensible_file * 1.6:.1f}",
            )
        )
    if len(functions) != 1:
        findings.append(
            _finding(
                "monolith_function_count", "monolith", value=len(functions), limit=1
            )
        )
        return
    only = functions[0]
    minimum_function_ratio = 0.75 if layered and state.language == "rust" else 1.0
    if only.tokens <= 200 or only.tokens <= sensible_total * minimum_function_ratio:
        findings.append(
            _finding(
                "monolith_tokens",
                "monolith",
                only.name,
                only.tokens,
                f">200 and >{sensible_total * minimum_function_ratio:.1f}",
            )
        )
    if only.complexity < 15:
        findings.append(
            _finding(
                "monolith_cognitive", "monolith", only.name, only.complexity, ">=15"
            )
        )


def _rule_tree(findings: list[dict], state: ItemState, version: str) -> None:
    functions = state.functions[version]
    calls = state.calls[version]
    entry = state.entries[version]
    count_range = (
        (28, 72)
        if state.profile == "layered" and version in {"tiny", "namematched"}
        else (12, 32)
    )
    if not count_range[0] <= len(functions) <= count_range[1]:
        findings.append(
            _finding(
                f"{version}_function_count",
                version,
                value=len(functions),
                limit=f"{count_range[0]}-{count_range[1]}",
            )
        )
    if state.profile == "layered" and entry is not None:
        helpers = [function for function in functions if function is not entry]
        helper_token_cap = 90 if version in {"tiny", "namematched"} else 45
        _check_tokens(
            findings,
            f"{version}_function_tokens",
            version,
            helpers,
            5,
            helper_token_cap,
        )
        entry_token_cap = 90
        _check_tokens(
            findings, f"{version}_function_tokens", version, [entry], 5, entry_token_cap
        )
    else:
        _check_tokens(findings, f"{version}_function_tokens", version, functions, 5, 45)
    row_cap = (
        10
        if state.profile == "layered" and version in {"tiny", "namematched"}
        else TREE_ROW_CAPS.get(state.language, TREE_ROW_CAPS["default"])
    )
    findings.extend(
        _finding(
            f"{version}_function_lines",
            version,
            function.name,
            function.lines,
            row_cap,
        )
        for function in functions
        if function.lines > row_cap
    )
    if entry is None:
        return
    if state.profile == "layered" and version in {"tiny", "namematched"}:
        depth_range = (3, 8)
    elif state.profile == "layered" and version == "padded":
        depth_range = (3, 6)
    else:
        depth_range = (3, 5)
    if not depth_range[0] <= depth(calls, entry.name) <= depth_range[1]:
        findings.append(
            _finding(
                f"{version}_chain_depth",
                version,
                entry.name,
                depth(calls, entry.name),
                f"{depth_range[0]}-{depth_range[1]}",
            )
        )
    _check_fanout(findings, state, version, entry.name)
    dead = {name for name in calls if name not in reachable(calls, entry.name)}
    if dead:
        findings.append(
            _finding(
                f"{version}_dead_code",
                version,
                ",".join(sorted(dead)),
                sorted(dead),
                "none",
            )
        )


def _check_fanout(
    findings: list[dict], state: ItemState, version: str, entry_name: str
) -> None:
    fanout = len(state.calls[version].get(entry_name, []))
    if not 4 <= fanout <= 10:
        findings.append(
            _finding(f"{version}_entry_fanout", version, entry_name, fanout, "4-10")
        )


def _rule_padded(findings: list[dict], state: ItemState) -> None:
    entry = state.entries["padded"]
    helpers = [
        function for function in state.functions["padded"] if function is not entry
    ]
    layered = state.profile == "layered"
    rust_layered = layered and state.language == "rust"
    if layered:
        if entry is not None:
            _check_tokens(
                findings,
                "padded_entry_tokens",
                "padded",
                [entry],
                5,
                160 if rust_layered else 10**9,
            )
    else:
        _check_tokens(
            findings,
            "padded_entry_tokens",
            "padded",
            [entry] if entry else [],
            5,
            45,
        )
    helper_token_cap = 160 if rust_layered else 130 if layered else 80
    _check_tokens(
        findings, "padded_function_tokens", "padded", helpers, 30, helper_token_cap
    )
    if state.profile == "layered":
        if not 14 <= len(state.functions["padded"]) <= 22:
            findings.append(
                _finding(
                    "padded_function_count",
                    "padded",
                    value=len(state.functions["padded"]),
                    limit="14-22",
                )
            )
        if entry is not None:
            calls = state.calls["padded"]
            chain_depth = depth(calls, entry.name)
            if not 3 <= chain_depth <= 6:
                findings.append(
                    _finding(
                        "padded_chain_depth", "padded", entry.name, chain_depth, "3-6"
                    )
                )
            _check_fanout(findings, state, "padded", entry.name)
            dead = set(calls) - set(reachable(calls, entry.name))
            if dead:
                findings.append(
                    _finding(
                        "padded_dead_code",
                        "padded",
                        ",".join(sorted(dead)),
                        sorted(dead),
                        "none",
                    )
                )
    else:
        _rule_same_shape(findings, state, "padded", "padded_shape")
        _rule_helper_names(findings, state, "padded", "padded_names")
    matches = IDENTITY_ASSIGNMENT.findall(state.sources["padded"])
    if matches:
        findings.append(
            _finding(
                "padded_identity_assignment", "padded", value=matches, limit="none"
            )
        )


def _rule_same_shape(
    findings: list[dict], state: ItemState, version: str, kind: str
) -> None:
    tiny, other = state.calls["tiny"], state.calls[version]
    tiny_name = _entry_name(state, "tiny")
    other_name = _entry_name(state, version)
    tiny_shape = (
        len(state.functions["tiny"]),
        depth(tiny, tiny_name),
        len(tiny.get(tiny_name, [])),
    )
    other_shape = (
        len(state.functions[version]),
        depth(other, other_name),
        len(other.get(other_name, [])),
    )
    if other_shape != tiny_shape:
        findings.append(_finding(kind, version, value=other_shape, limit=tiny_shape))
    if _tree_shape(other, other_name) != _tree_shape(tiny, tiny_name):
        findings.append(
            _finding(
                kind,
                version,
                value=_tree_shape(other, other_name),
                limit=_tree_shape(tiny, tiny_name),
            )
        )


def _rule_helper_names(
    findings: list[dict], state: ItemState, version: str, kind: str
) -> None:
    tiny_names = {f.name for f in state.functions["tiny"]}
    shared = sorted(
        {f.name for f in state.functions[version]}
        & (tiny_names - {_entry_name(state, "tiny"), _entry_name(state, version)})
    )
    if shared:
        findings.append(
            _finding(kind, version, value=shared, limit="different helper names")
        )


def _entry_name(state: ItemState, version: str) -> str:
    entry = state.entries[version]
    return entry.name if entry else ""


def _rule_forwarders(findings: list[dict], state: ItemState) -> None:
    calls = state.calls["tiny"]
    forwarders = [
        function
        for function in state.functions["tiny"]
        if len(calls.get(function.name, [])) == 1 and function.complexity == 0
    ]
    if len(forwarders) < 3:
        findings.append(
            _finding("tiny_forwarders", "tiny", value=len(forwarders), limit=">=3")
        )


def _rule_sizematched(findings: list[dict], state: ItemState) -> None:
    size = state.functions["sizematched"]
    sensible_total = sum(f.tokens for f in state.functions["sensible"])
    sensible_file = whole_file_tokens(state.sources["sensible"])
    size_file = whole_file_tokens(state.sources["sizematched"])
    tolerance = 0.10 if state.profile == "layered" else 0.03
    tolerance_label = "±10%" if state.profile == "layered" else "±3%"
    if abs(size_file - sensible_file) > sensible_file * tolerance:
        findings.append(
            _finding(
                "sizematched_file_tokens",
                "sizematched",
                value=size_file,
                limit=f"{sensible_file} {tolerance_label}",
            )
        )
    if len(size) != 1:
        findings.append(
            _finding(
                "sizematched_function_count", "sizematched", value=len(size), limit=1
            )
        )
        return
    if abs(size[0].tokens - sensible_total) > sensible_total * tolerance:
        findings.append(
            _finding(
                "sizematched_tokens",
                "sizematched",
                size[0].name,
                size[0].tokens,
                f"{sensible_total} {tolerance_label}",
            )
        )


def _rule_redefinitions(findings: list[dict], state: ItemState) -> None:
    for version in TREE_VERSIONS:
        names = [function.name for function in state.functions[version]]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            findings.append(
                _finding(
                    f"{version}_redefinitions",
                    version,
                    ",".join(duplicates),
                    duplicates,
                    "unique names",
                )
            )


def _rule_recursion(findings: list[dict], state: ItemState) -> None:
    for version in TREE_VERSIONS:
        cycles = cyclic(state.calls[version])
        if cycles:
            findings.append(
                _finding(
                    "recursion",
                    version,
                    ",".join(sorted(cycles)),
                    sorted(cycles),
                    "acyclic",
                )
            )


def _rule_comment_parity(findings: list[dict], state: ItemState) -> None:
    shapes = [
        comment_shape(state.language, state.sources[version]) for version in VERSIONS
    ]
    if len(set(shapes)) != 1:
        findings.append(
            _finding(
                "comment_parity",
                "all",
                value=shapes,
                limit="equal count and length class",
            )
        )


def _rule_category_words(findings: list[dict], state: ItemState) -> None:
    for version, source in state.sources.items():
        matches = category_words(source)
        if matches:
            findings.append(
                _finding("category_word", version, value=matches, limit="none")
            )


def _check_tokens(
    findings: list[dict],
    kind: str,
    version: str,
    functions: list[Function],
    low: int,
    high: int,
) -> None:
    findings.extend(
        _finding(kind, version, function.name, function.tokens, f"{low}-{high}")
        for function in functions
        if not low <= function.tokens <= high
    )


def _tree_shape(calls: dict[str, list[str]], entry: str):
    def shape(name: str, path: frozenset[str]):
        if name in path:
            return ("cycle",)
        return tuple(
            sorted(
                (shape(child, path | {name}) for child in calls.get(name, [])),
                key=repr,
            )
        )

    return shape(entry, frozenset())


def _metrics(state: ItemState) -> list[str]:
    return [
        row(
            version,
            state.sources[version],
            state.functions[version],
            _entry_name(state, version),
        )
        for version in state.versions
    ]


def _finding(
    kind: str, version: str, function: str = "", value=None, limit=None
) -> dict:
    return {
        "kind": kind,
        "version": version,
        "function": function,
        "value": value,
        "limit": limit,
    }
