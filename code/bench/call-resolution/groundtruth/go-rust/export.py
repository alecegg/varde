"""Export statically resolved Go and Rust call sites for the audit.

The frozen matching rule is the declaration directly reported by the static
language tool. Interface and trait declarations stay the target; the exporter
does not expand calls to possible runtime overrides or implementations. A target
is recorded only when its declaring line names the called symbol, so a rename or
a macro-generated definition that the tool cannot name stays unresolved.
Constructors of enum variants and tuple structs, Go builtins and Go type
conversions are not calls to a function and are dropped.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import time
from bisect import bisect_right
from collections import Counter
from functools import cache, lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

GO_HELPER = Path(__file__).parent / "go-types"
CALL_CLASSES = (
    "same_file",
    "imported",
    "member",
    "constructor",
    "higher_order",
    "dynamic",
)
NOT_A_CALL = {"if", "while", "for", "match", "loop", "return", "where", "assert"}
# Standard prelude variant constructors: `Some(x)`, `Ok(x)`, `Err(x)` are not calls.
VARIANT_CONSTRUCTORS = {"Some", "Ok", "Err"}
GO_NOT_CALLS = {"builtin", "conversion"}
REPO_SHARE = 0.4
IN_REPO_SHARE = 0.5


def export_go(
    repo_path: Path, repo_name: str, env: dict[str, str]
) -> list[dict[str, Any]]:
    command = ["go", "run", ".", str(repo_path), repo_name]
    result = subprocess.run(  # noqa: S603 - Runs the Go helper to extract benchmark ground truth.
        command, cwd=GO_HELPER, env=env, check=True, capture_output=True, text=True
    )
    return distinct_calls(
        filter_go_calls(
            [json.loads(line) for line in result.stdout.splitlines() if line]
        )
    )


def filter_go_calls(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop Go builtins (`len`, `make`, `append`, ...) and type conversions.

    Neither is a call to a function, so neither belongs in a call-resolution
    sample. The Go helper reports the kind it derived from ``go/types``.
    """
    kept: list[dict[str, Any]] = []
    for row in rows:
        if row.pop("_callee_kind", "function") in GO_NOT_CALLS:
            continue
        kept.append(row)
    return kept


def rust_candidates(repo_path: Path, repo_name: str) -> list[dict[str, Any]]:
    sites: list[dict[str, Any]] = []
    excluded = {"target", "vendor", "generated", "tests", "testdata"}
    for path in sorted(repo_path.rglob("*.rs")):
        if excluded.intersection(path.parts) or not path.is_file():
            continue
        if nested_checkout(path.parent, repo_path):
            continue
        sites.extend(rust_source_calls(path, repo_path, repo_name))
    return cap_rust_sites(distinct_calls(sites))


@cache
def nested_checkout(directory: Path, root: Path) -> bool:
    """True when a parent directory is its own git checkout.

    Build scripts clone vendored trees (grammars, generated sources) into the
    pinned checkout and leave a nested ``.git``; those files are not repository
    source and stay out of the sample.
    """
    if directory in (root, directory.parent):
        return False
    if (directory / ".git").exists():
        return True
    return nested_checkout(directory.parent, root)


def distinct_calls(sites: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one site per (file, line, call_name) so records stay unique."""
    seen: set[tuple[str, int, str]] = set()
    unique: list[dict[str, Any]] = []
    for site in sites:
        key = (site["file"], site["line"], site["call_name"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(site)
    return unique


def rust_source_calls(
    path: Path, repo_path: Path, repo_name: str
) -> list[dict[str, Any]]:
    source = path.read_text(errors="replace")
    functions = re.compile(r"\bfn\s+(?P<name>[A-Za-z_]\w*)\s*\(")
    spans = function_spans(source, functions)
    spans.sort(key=lambda item: item["start"])
    rows: list[dict[str, Any]] = []
    relative = path.relative_to(repo_path).as_posix()
    uri = file_uri(path)
    module = module_name(path, repo_path)
    line_starts = [0]
    line_starts.extend(index + 1 for index, char in enumerate(source) if char == "\n")
    span_index = 0
    active: list[dict[str, Any]] = []
    for match in call_pattern().finditer(source):
        while span_index < len(spans) and spans[span_index]["start"] <= match.start():
            active.append(spans[span_index])
            span_index += 1
        while active and active[-1]["end"] <= match.start():
            active.pop()
        function = active[-1] if active else None
        if function is None or re.search(
            r"\bfn\s+$", source[max(0, match.start() - 8) : match.start()]
        ):
            continue
        callee, name, name_start = matched_callee(source, match)
        if name in NOT_A_CALL or name in VARIANT_CONSTRUCTORS:
            continue
        if inside_attribute(source, match.start()):
            continue
        row = bisect_right(line_starts, name_start) - 1
        col = name_start - line_starts[row]
        syntax_class = "member" if "." in callee else "same_file"
        if name == "new":
            syntax_class = "constructor"
        rows.append(
            {
                "repo": repo_name,
                "language": "rust",
                "file": relative,
                "line": row + 1,
                "call_name": name,
                "call_class": syntax_class,
                "ground_truth": "unknown",
                "measured_edge": None,
                "measured_status": "opaque",
                "truth_source": "rust-analyzer",
                "function_id": f"{relative}:{function['line']}:{function['name']}",
                "module": module,
                "_uri": uri,
                "_position": {"line": row, "character": col},
                "_identifier": name,
                "_syntax": syntax_class,
            }
        )
    return rows


@cache
def call_pattern() -> re.Pattern[str]:
    """Calls of a named function or method, including `(self.callback)(x)`."""
    return re.compile(
        r"(?P<callee>(?:[A-Za-z_]\w*::)*[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)\s*\("
        r"|\((?P<paren>(?:[A-Za-z_]\w*::)*[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)\)\s*\("
    )


def matched_callee(source: str, match: re.Match[str]) -> tuple[str, str, int]:
    """Return (callee path, called name, index of the name) for a call match."""
    callee = match.group("callee") or match.group("paren")
    name = callee.rsplit(".", 1)[-1].rsplit("::", 1)[-1]
    return callee, name, match.start() + len(callee) - len(name)


def inside_attribute(source: str, start: int) -> bool:
    """True when the candidate sits inside a `#[...]` attribute.

    `#[derive(Clone)]`, `#[cfg(test)]` and `#[serde(rename = "x")]` look like
    calls to a regex but are attribute invocations, and `cfg_attr` nests them.
    """
    depth = 0
    for index in range(start - 1, max(start - 2000, -1), -1):
        char = source[index]
        if char == "]":
            depth += 1
        elif char == "[":
            if depth == 0:
                return index > 0 and source[index - 1] == "#"
            depth -= 1
    return False


def function_spans(source: str, declaration: re.Pattern[str]) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for match in declaration.finditer(source):
        open_brace = source.find("{", match.end())
        if open_brace < 0:
            continue
        depth = 1
        end = open_brace + 1
        while end < len(source) and depth:
            if source[end] == "{":
                depth += 1
            elif source[end] == "}":
                depth -= 1
            end += 1
        spans.append(
            {
                "start": open_brace + 1,
                "end": end,
                "line": source.count("\n", 0, match.start()) + 1,
                "name": match.group("name"),
            }
        )
    return spans


def cap_rust_sites(
    sites: list[dict[str, Any]], limit: int = 4000
) -> list[dict[str, Any]]:
    """Bound the resolution work per repository, keeping every call class."""
    if len(sites) <= limit:
        return sites
    rng = random.Random(sites[0]["repo"])  # noqa: S311 - Reproducible benchmark sampling is not cryptographic.
    groups = {
        kind: [site for site in sites if site["_syntax"] == kind]
        for kind in ("constructor", "member", "same_file")
    }
    for candidates in groups.values():
        candidates.sort(
            key=lambda site: (site["file"], site["line"], site["_identifier"])
        )
        rng.shuffle(candidates)
    selected: list[dict[str, Any]] = []
    quotas = {"constructor": limit // 5, "member": limit * 3 // 5}
    quotas["same_file"] = limit - sum(quotas.values())
    for kind, quota in quotas.items():
        selected.extend(groups[kind][:quota])
    return selected


def select_rust_target(
    symbols: list[str],
    definitions: dict[str, list[tuple[str, int, int]]],
    source_lines: Any,
    call_name: str,
) -> tuple[str, int, str] | None:
    """Pick the declaration the call resolves to, requiring the called name.

    A symbol whose declaring line does not name the called symbol (a rename, a
    macro-generated definition, or an index position that points at another
    occurrence) is not a target. When only a non-callable declaration is found
    the kind is ``other`` and the caller drops the site.
    """
    fallback: tuple[str, int, str] | None = None
    for symbol in symbols:
        for path, line, _ in definitions.get(symbol, []):
            lines = source_lines(path)
            line_text = lines[line] if line < len(lines) else ""
            kind = target_kind(line_text, call_name)
            if kind in {"function", "higher_order"}:
                return path, line, kind
            if kind == "other" and fallback is None:
                fallback = path, line, kind
    return fallback


def target_kind(line: str, name: str) -> str:
    """Classify the declaration of ``name`` on ``line``.

    ``function`` is a function or method declaration, ``higher_order`` a callable
    value binding (local, parameter, struct field), ``other`` a named declaration
    that cannot be called (tuple-struct or enum-variant constructor), and
    ``missing`` a line that does not declare the name at all.
    """
    escaped = re.escape(name)
    if re.search(rf"\bfn\s+{escaped}\b", line):
        return "function"
    if is_value_binding(line, name):
        return "higher_order"
    if re.search(rf"^\s*(?:pub\s+)?{escaped}\s*[\(<{{]", line) or re.search(
        rf"\b(?:struct|enum|type|const|static)\s+{escaped}\b", line
    ):
        return "other"
    return "missing"


def apply_rust_target(
    site: dict[str, Any], path: str, line: int, kind: str, repo_path: Path
) -> None:
    """Record a name-matched target on ``site``."""
    if kind == "higher_order":
        site.update(
            call_class="higher_order",
            ground_truth="unknown",
            ground_truth_module=None,
            measured_status="opaque",
        )
        return
    target_path = repo_path / path
    site.update(
        ground_truth=f"{path}:{line + 1}:{site['call_name']}",
        ground_truth_module=module_name(target_path, repo_path),
        measured_status="unresolved",
    )
    if site["_syntax"] == "constructor":
        site["call_class"] = "constructor"
    elif target_path == repo_path / site["file"]:
        site["call_class"] = "member" if site["_syntax"] == "member" else "same_file"
    else:
        site["call_class"] = "member" if site["_syntax"] == "member" else "imported"


def name_mismatches(
    records: list[dict[str, Any]], repos_root: Path
) -> list[dict[str, Any]]:
    """Records whose resolved target line does not declare the called name.

    Every in-repo target in the exported dataset must satisfy this; it is the
    consistency check for the SCIP position/symbol join.
    """
    failures: list[dict[str, Any]] = []
    for record in records:
        truth = record["ground_truth"]
        if truth in {"external", "unknown"}:
            continue
        path, line, _ = truth.rsplit(":", 2)
        source = repos_root / record["repo"].rsplit("/", 1)[-1] / path
        if not source.is_file():
            failures.append(record)
            continue
        lines = source.read_text(errors="replace").splitlines()
        line_text = lines[int(line) - 1] if int(line) <= len(lines) else ""
        if not declares_name(line_text, record["call_name"]):
            failures.append(record)
    return failures


def declares_name(line: str, name: str) -> bool:
    """True when ``line`` declares ``name`` as a function, method or value.

    Go interface methods are declared without a ``func`` keyword, so a bare
    ``Name(...)`` signature counts as well.
    """
    escaped = re.escape(name)
    patterns = (
        rf"\bfn\s+{escaped}\b",
        rf"\bfunc\s+(?:\([^)]*\)\s*)?{escaped}\b",
        rf"\b(?:let|const|static|var)\s+(?:mut\s+)?{escaped}\b",
        rf"(?:^|[,(])\s*{escaped}\s*:",
        rf"^\s*{escaped}\s*\(",
    )
    return any(re.search(pattern, line) for pattern in patterns)


def resolve_rust(
    repo_path: Path, sites: list[dict[str, Any]], env: dict[str, str]
) -> list[dict[str, Any]]:
    if not sites:
        return []
    rust_analyzer = Path(env["RUST_ANALYZER"])
    client = LspClient(rust_analyzer, repo_path, env)
    try:
        client.initialize()
        for uri in sorted({site["_uri"] for site in sites}):
            path = Path(unquote(uri.removeprefix("file://")))
            client.notify(
                "textDocument/didOpen",
                {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "rust",
                        "version": 1,
                        "text": path.read_text(),
                    }
                },
            )
        time.sleep(15)
        for index, site in enumerate(sites, start=1):
            target = client.definition(index, site)
            finalize_rust_site(site, target, repo_path)
        return sites
    finally:
        client.close()


def protobuf_fields(data: bytes) -> list[tuple[int, int, int | bytes]]:
    fields: list[tuple[int, int, int | bytes]] = []
    offset = 0
    while offset < len(data):
        tag, offset = read_varint(data, offset)
        number, wire = tag >> 3, tag & 7
        if wire == 0:
            value, offset = read_varint(data, offset)
        elif wire == 2:
            size, offset = read_varint(data, offset)
            value = data[offset : offset + size]
            offset += size
        elif wire == 1:
            value = data[offset : offset + 8]
            offset += 8
        elif wire == 5:
            value = data[offset : offset + 4]
            offset += 4
        else:
            raise ValueError(f"unsupported SCIP protobuf wire type: {wire}")
        fields.append((number, wire, value))
    return fields


def read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = shift = 0
    while offset < len(data):
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
    raise ValueError("truncated SCIP varint")


def field_bytes(data: bytes, number: int) -> list[bytes]:
    return [
        value
        for field, wire, value in protobuf_fields(data)
        if field == number and wire == 2 and isinstance(value, bytes)
    ]


def field_text(data: bytes, number: int) -> str:
    values = field_bytes(data, number)
    return values[0].decode() if values else ""


def field_int(data: bytes, number: int) -> int:
    return next(
        (
            value
            for field, wire, value in protobuf_fields(data)
            if field == number and wire == 0 and isinstance(value, int)
        ),
        0,
    )


def occurrence_position(occurrence: bytes) -> tuple[int, int]:
    fields = protobuf_fields(occurrence)
    for number, wire, value in fields:
        if number in {8, 9} and wire == 2 and isinstance(value, bytes):
            coordinates = [
                field
                for _, nested_wire, field in protobuf_fields(value)
                if nested_wire == 0 and isinstance(field, int)
            ]
            return (coordinates[0], coordinates[1]) if len(coordinates) >= 2 else (0, 0)
    packed = next(
        (
            value
            for number, wire, value in fields
            if number == 1 and wire == 2 and isinstance(value, bytes)
        ),
        b"",
    )
    coordinates: list[int] = []
    offset = 0
    while offset < len(packed):
        value, offset = read_varint(packed, offset)
        coordinates.append(value)
    return (coordinates[0], coordinates[1]) if len(coordinates) >= 2 else (0, 0)


def parse_scip_index(
    data: bytes,
) -> tuple[
    dict[tuple[str, int, int], list[tuple[str, int]]],
    dict[str, list[tuple[str, int, int]]],
    set[str],
]:
    occurrences: dict[tuple[str, int, int], list[tuple[str, int]]] = {}
    definitions: dict[str, list[tuple[str, int, int]]] = {}
    for document in field_bytes(data, 2):
        path = field_text(document, 1)
        for occurrence in field_bytes(document, 2):
            symbol = field_text(occurrence, 2)
            if not symbol:
                continue
            line, character = occurrence_position(occurrence)
            roles = field_int(occurrence, 3)
            occurrences.setdefault((path, line, character), []).append((symbol, roles))
            if roles & 1:  # SCIP SymbolRole.Definition.
                definitions.setdefault(symbol, []).append((path, line, character))
    external = {
        field_text(symbol, 1)
        for symbol in field_bytes(data, 3)
        if field_text(symbol, 1)
    }
    return occurrences, definitions, external


def resolve_rust_scip(
    repo_path: Path,
    sites: list[dict[str, Any]],
    index_path: Path,
) -> list[dict[str, Any]]:
    occurrences, definitions, external = parse_scip_index(index_path.read_bytes())
    lines_by_path: dict[str, list[str]] = {}

    def source_lines(path: str) -> list[str]:
        if path not in lines_by_path:
            lines_by_path[path] = (
                (repo_path / path).read_text(errors="replace").splitlines()
            )
        return lines_by_path[path]

    resolved: list[dict[str, Any]] = []
    for site in sites:
        site["call_name"] = site["_identifier"]
        candidate_line = source_lines(site["file"])[site["_position"]["line"]]
        byte_character = len(
            candidate_line[: site["_position"]["character"]].encode("utf-8")
        )
        key = (
            site["file"],
            site["_position"]["line"],
            byte_character,
        )
        symbols = [
            symbol for symbol, roles in occurrences.get(key, []) if not roles & 1
        ]
        target = select_rust_target(
            symbols, definitions, source_lines, site["call_name"]
        )
        if target is not None:
            path, line, kind = target
            if kind == "other":
                # Tuple-struct or enum-variant constructor: not a function call.
                continue
            apply_rust_target(site, path, line, kind, repo_path)
            resolved.append(site)
            continue
        if any(symbol in external for symbol in symbols) or any(
            not symbol.startswith("local ") for symbol in symbols
        ):
            site.update(
                ground_truth="external",
                measured_status="external",
                call_class=(
                    "constructor"
                    if site["_syntax"] == "constructor"
                    else "member"
                    if site["_syntax"] == "member"
                    else "imported"
                ),
            )
            resolved.append(site)
            continue
        site.update(
            call_class="dynamic",
            ground_truth="unknown",
            measured_status="opaque",
        )
        resolved.append(site)
    return resolved


class LspClient:
    def __init__(self, executable: Path, root: Path, env: dict[str, str]) -> None:
        self.process = subprocess.Popen(  # noqa: S603 - Starts the language server process used for benchmark extraction.
            [str(executable)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        self.root = root

    def initialize(self) -> None:
        uri = file_uri(self.root)
        self.send(
            {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "processId": None,
                    "rootUri": uri,
                    "rootPath": str(self.root),
                    "capabilities": {},
                    "workspaceFolders": [{"uri": uri, "name": self.root.name}],
                },
            }
        )
        self.wait_for_response(0)
        self.notify("initialized", {})

    def request(self, request_id: int, method: str, params: dict[str, Any]) -> Any:
        self.send(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        return self.wait_for_response(request_id).get("result")

    def wait_for_response(self, request_id: int) -> dict[str, Any]:
        while True:
            response = self.receive()
            if "method" in response and "id" in response:
                self.respond_to_request(response)
                continue
            if response.get("id") == request_id:
                return response

    def respond_to_request(self, request: dict[str, Any]) -> None:
        method = request["method"]
        params = request.get("params", {})
        if method == "workspace/configuration":
            result = [{} for _ in params.get("items", [])]
        elif method == "workspace/workspaceFolders":
            result = [{"uri": file_uri(self.root), "name": self.root.name}]
        elif method == "workspace/applyEdit":
            result = {"applied": False}
        else:
            result = None
        self.send({"jsonrpc": "2.0", "id": request["id"], "result": result})

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self.send({"jsonrpc": "2.0", "method": method, "params": params})

    def definition(self, request_id: int, site: dict[str, Any]) -> Any:
        result = self.request(
            request_id,
            "textDocument/definition",
            {"textDocument": {"uri": site["_uri"]}, "position": site["_position"]},
        )
        return definition_location(result)

    def send(self, message: dict[str, Any]) -> None:
        assert self.process.stdin is not None  # noqa: S101 - The process is started with stdin=PIPE.
        body = json.dumps(message).encode()
        self.process.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
        self.process.stdin.flush()

    def receive(self) -> dict[str, Any]:
        assert self.process.stdout is not None  # noqa: S101 - The process is started with stdout=PIPE.
        headers: dict[str, str] = {}
        while True:
            line = self.process.stdout.readline()
            if line in (b"\r\n", b"\n", b""):
                break
            key, value = line.decode().split(":", 1)
            headers[key.lower()] = value.strip()
        if not headers:
            raise RuntimeError("rust-analyzer stopped before returning an LSP message")
        return json.loads(self.process.stdout.read(int(headers["content-length"])))

    def close(self) -> None:
        self.process.terminate()
        self.process.wait(timeout=10)


def finalize_rust_site(site: dict[str, Any], target: Any, repo_path: Path) -> None:
    site["call_name"] = site["_identifier"]
    if target is None:
        site["call_class"] = (
            "dynamic" if site["_syntax"] != "constructor" else "constructor"
        )
        site["ground_truth"] = "unknown"
        site["measured_status"] = "opaque"
        return
    uri = target.get("uri", "")
    target_path = (
        Path(unquote(uri.removeprefix("file://")))
        if uri.startswith("file://")
        else None
    )
    if target_path is None or not target_path.is_relative_to(repo_path):
        site["ground_truth"] = "external"
        site["measured_status"] = "external"
        return
    line = target["range"]["start"]["line"]
    target_lines = target_path.read_text().splitlines()
    target_line = target_lines[line] if line < len(target_lines) else ""
    kind = target_kind(target_line, site["_identifier"])
    if kind in {"missing", "other"}:
        site.update(
            call_class="dynamic",
            ground_truth="unknown",
            ground_truth_module=None,
            measured_status="opaque",
        )
        return
    apply_rust_target(
        site, target_path.relative_to(repo_path).as_posix(), line, kind, repo_path
    )


def class_quotas(size: int) -> dict[str, int]:
    return {
        kind: size // len(CALL_CLASSES) + (i < size % len(CALL_CLASSES))
        for i, kind in enumerate(CALL_CLASSES)
    }


def repo_cap(size: int) -> int:
    """Largest number of sites one repository may contribute to a set."""
    return max(1, int(size * REPO_SHARE))


def draw(
    pools: dict[str, dict[str, list[dict[str, Any]]]],
    repos: list[str],
    want: int,
    counts: Counter[str],
    cap: int,
    buckets: tuple[str, ...] = ("in_repo", "rest"),
) -> list[dict[str, Any]]:
    """Draw up to ``want`` sites, least-used repository first, under ``cap``."""
    chosen: list[dict[str, Any]] = []
    while len(chosen) < want:
        drawn = False
        for repo in sorted(repos, key=lambda name: counts[name]):
            if counts[repo] >= cap:
                continue
            for bucket in buckets:
                if pools[repo][bucket]:
                    chosen.append(pools[repo][bucket].pop())
                    counts[repo] += 1
                    drawn = True
                    break
            if len(chosen) >= want:
                break
        if not drawn:
            break
    return chosen


def fill_from_surplus(
    pools: dict[str, dict[str, dict[str, list[dict[str, Any]]]]],
    repos: list[str],
    size: int,
    counts: Counter[str],
    cap: int,
    taken: Counter[str],
) -> list[dict[str, Any]]:
    """Take the remaining slots from the classes that still have supply.

    One site at a time, into the class with the fewest sites so far (largest
    supply breaks the tie), so the extras spread evenly over the classes that can
    supply them. A class whose pool is exhausted after the quota pass (one that
    could not fill its quota) contributes nothing here, so a scarce class keeps
    its honest count.
    """
    chosen: list[dict[str, Any]] = []
    while sum(taken.values()) < size:
        supply = {
            kind: sum(
                len(pools[kind][repo][bucket])
                for repo in repos
                for bucket in ("in_repo", "rest")
            )
            for kind in CALL_CLASSES
        }
        candidates = [kind for kind in CALL_CLASSES if supply[kind] > 0]
        if not candidates:
            break
        kind = min(candidates, key=lambda name: (taken[name], -supply[name]))
        drawn = draw(pools[kind], repos, 1, counts, cap)
        if not drawn:
            break
        taken[kind] += 1
        chosen.extend(drawn)
    return chosen


def sample_sites(
    sites: list[dict[str, Any]],
    roles: dict[str, str],
    language: str,
    split: str,
    seed: int,
    size: int = 300,
) -> list[dict[str, Any]]:
    """Stratified sample of ``size`` sites.

    Each class gets an equal quota, half of it drawn from in-repo targets where
    available, and no repository contributes more than ``REPO_SHARE`` of the set.
    A class that cannot fill its quota keeps its honest count; the remaining slots
    are drawn one at a time into the classes with the fewest sites so far that
    still have supply (never relabelling a site), so the set still reaches ``size``.
    """
    repos = sorted(repo for repo, role in roles.items() if role == split)
    quotas = class_quotas(size)
    pools = {
        kind: {repo: {"in_repo": [], "rest": []} for repo in repos}
        for kind in CALL_CLASSES
    }
    for site in sites:
        if site["language"] != language or site["repo"] not in repos:
            continue
        call_class = site["call_class"]
        if call_class not in CALL_CLASSES:
            continue
        bucket = "in_repo"
        if site["ground_truth"] in {"external", "unknown"}:
            bucket = "rest"
        pools[call_class][site["repo"]][bucket].append(site)
    for call_class in CALL_CLASSES:
        rng = random.Random(f"{seed}:{language}:{split}:{call_class}")  # noqa: S311 - Reproducible benchmark sampling is not cryptographic.
        for buckets in pools[call_class].values():
            for candidates in buckets.values():
                candidates.sort(key=lambda row: (row["file"], row["line"]))
                rng.shuffle(candidates)
    counts: Counter[str] = Counter()
    selected: list[dict[str, Any]] = []
    cap = repo_cap(size)
    for call_class in CALL_CLASSES:
        quota = quotas[call_class]
        available = sum(len(pools[call_class][repo]["in_repo"]) for repo in repos)
        in_repo_want = min(int(quota * IN_REPO_SHARE), available)
        chosen = draw(pools[call_class], repos, in_repo_want, counts, cap, ("in_repo",))
        chosen += draw(
            pools[call_class],
            repos,
            quota - len(chosen),
            counts,
            cap,
            ("rest", "in_repo"),
        )
        selected.extend(chosen)
    taken = Counter(site["call_class"] for site in selected)
    selected.extend(fill_from_surplus(pools, repos, size, counts, cap, taken))
    selected = [dict(site) for site in selected]
    for site in selected:
        for key in tuple(site):
            if key.startswith("_"):
                del site[key]
    return sorted(
        selected,
        key=lambda row: (row["repo"], row["file"], row["line"], row["call_class"]),
    )


def definition_location(result: Any) -> dict[str, Any] | None:
    if isinstance(result, list):
        return result[0] if len(result) == 1 else None
    return result if isinstance(result, dict) else None


def is_value_binding(line: str, identifier: str) -> bool:
    """True when ``line`` binds ``name`` to a callable value.

    Local bindings, parameters (`f: F`, `mut f: F`) and struct fields are where a
    call through a function value or closure resolves to.
    """
    name = re.escape(identifier)
    binding = rf"\b(?:let|const|static)\s+(?:mut\s+)?{name}\b"
    parameter = rf"(?:^|[,(])\s*(?:pub\s+)?(?:mut\s+)?{name}\s*:"
    return bool(re.search(binding, line) or re.search(parameter, line))


def module_name(path: Path, root: Path) -> str:
    for parent in path.parents:
        if parent == root.parent:
            break
        manifest = parent / "Cargo.toml"
        if manifest.is_file():
            package = cargo_package_name(manifest)
            if package:
                return package
    relative = path.relative_to(root)
    return relative.parts[0] if relative.parts else root.name


@lru_cache(maxsize=512)
def cargo_package_name(manifest: Path) -> str | None:
    import tomllib

    try:
        with manifest.open("rb") as stream:
            data = tomllib.load(stream)
    except tomllib.TOMLDecodeError, OSError:
        return None
    package = data.get("package", {}).get("name")
    return str(package) if package else None


def file_uri(path: Path) -> str:
    return "file://" + quote(str(path.resolve()))


def definition_location_from_lsp(result: Any) -> Any:
    return definition_location(result)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("language", choices=("go", "rust"))
    parser.add_argument("repo_path", type=Path)
    parser.add_argument("repo_name")
    args = parser.parse_args()
    env = os.environ.copy()
    if args.language == "go":
        output = export_go(args.repo_path.resolve(), args.repo_name, env)
    else:
        output = resolve_rust(
            args.repo_path.resolve(),
            rust_candidates(args.repo_path.resolve(), args.repo_name),
            env,
        )
    for site in output:
        if site["call_class"] not in CALL_CLASSES:
            continue
        for key in tuple(site):
            if key.startswith("_"):
                del site[key]
        print(json.dumps(site, sort_keys=True))


if __name__ == "__main__":
    main()
