"""Export source-call matches and clangd targets for C++.

Match rule: a call targets the symbol clangd reports for the call site and the
location clangd marks for it (its selection range), so a declaration in a
header and a definition in a source file are two different reported locations
and the one clangd selected is recorded verbatim. Virtual calls use the
statically selected declaration; a runtime override is never guessed.
Overloads and template specializations follow clangd's resolution from the
compile database entry for the file. Macro invocations are not project calls:
gtest, doctest, Catch2, Boost.Test and assert-style macros (``EXPECT_EQ``,
``ASSERT_TRUE``, ``TEST_F``, ``CHECK``) are excluded, while a call to a project
function whose name merely contains such a word is kept. Callable objects
(function pointers, ``std::function``/``absl::FunctionRef``, lambda variables,
callback parameters) are classified from syntax as ``higher_order`` and kept
even when their target is unknown. Vendored and third-party source paths are
skipped so a match is always a project call. Other unresolved sites receive
review stubs.

Call classes: ``same_file`` (callee in the caller's file), ``imported``
(callee in another project file), ``member`` (call through a receiver
expression), ``constructor`` (type construction), ``higher_order`` (call
through a callable value: a function pointer, a ``std::function``/absl
callable, a lambda variable, a callback parameter, a functor or a
member-function pointer), and ``dynamic`` (dispatch decided at run time: a call
of a virtual method reached through a base pointer or reference, or a call
through a pointer obtained from ``dlsym``/``dlopen``). Keywords and operators
that precede ``(`` (``if``, ``for``, ``while``, ``switch``, ``return``,
``sizeof``, ``decltype``, ``static_assert``, casts and similar) are not calls
and never become records, and a namespace-qualified callee such as
``std::min`` is a plain function call rather than a callable value.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote, urlparse

from audit.records import validate_record

CALL = re.compile(
    r"(?P<name>[A-Za-z_]\w+(?:(?:\s*::\s*|\s*->\s*|\s*\.\s*)[A-Za-z_]\w+)*)\s*\("
)
INDIRECT_CALL = re.compile(r"\(\s*\*\s*(?P<name>[A-Za-z_]\w*)\s*\)\s*\(")
MEMBER_CALL = re.compile(
    r"(?P<receiver>[A-Za-z_]\w*)[ \t]*(?:->|\.)[ \t]*(?P<name>[A-Za-z_]\w*)[ \t]*\("
)
RUNTIME_LOOKUP = re.compile(
    r"\b(?P<name>[A-Za-z_]\w*)\s*=\s*[^;]*\b(?:dlsym|dlopen)\s*\("
)
CONTROL = {"if", "for", "while", "switch", "catch", "sizeof", "alignof", "decltype"}
KEYWORDS = CONTROL | {
    "alignas",
    "asm",
    "case",
    "class",
    "co_await",
    "co_return",
    "co_yield",
    "concept",
    "const_cast",
    "consteval",
    "constexpr",
    "default",
    "defined",
    "delete",
    "do",
    "dynamic_cast",
    "else",
    "enum",
    "explicit",
    "export",
    "extern",
    "goto",
    "inline",
    "mutable",
    "namespace",
    "new",
    "noexcept",
    "operator",
    "private",
    "protected",
    "public",
    "reinterpret_cast",
    "requires",
    "return",
    "static_assert",
    "static_cast",
    "struct",
    "template",
    "throw",
    "try",
    "typeid",
    "typedef",
    "typename",
    "typeof",
    "union",
    "using",
    "virtual",
    "volatile",
}
MACRO_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
TYPE_DECLARATION = re.compile(
    r"\b(?:class|struct|union)\s+(?:[A-Za-z_]\w*\s+)?(?P<name>[A-Za-z_]\w*)"
    r"|\busing\s+(?P<using>[A-Za-z_]\w*)\s*="
    r"|\btypedef\s+[^;{}]*?(?P<typedef>[A-Za-z_]\w*)\s*;"
)
FUNCTION_KINDS = {6, 9, 12}
CLASS_NAMES = (
    "same_file",
    "imported",
    "member",
    "constructor",
    "higher_order",
    "dynamic",
)
MAX_SOURCE_BYTES = 512_000
MAX_SOURCE_FILES = 40
MAX_FUNCTIONS_PER_FILE = 10_000
MAX_MEMBER_CHECKS_PER_FILE = 100
EXCLUDED_PATH_PARTS = {
    "3rd_party",
    "3rdparty",
    "_deps",
    "build",
    "deps",
    "doctest",
    "external",
    "gtest",
    "googletest",
    "third_party",
    "thirdparty",
    "third-party",
    "vendor",
    "vendors",
}
TEST_MACRO = re.compile(
    r"^(?:ASSERT(?:_[A-Z0-9]+)*|EXPECT(?:_[A-Z0-9]+)*|GTEST_[A-Z0-9_]+|"
    r"TEST(?:_[A-Z0-9]+)*|TYPED_TEST(?:_[A-Z0-9]+)*|"
    r"INSTANTIATE_TEST_SUITE_P|DOCTEST_[A-Z0-9_]+|"
    r"CHECK(?:_[A-Z0-9]+)*|REQUIRE(?:_[A-Z0-9]+)*|"
    r"SECTION|SCENARIO|CATCH_[A-Z0-9_]+|BOOST_[A-Z0-9_]+|"
    r"SUCCEED|FAIL|ADD_FAILURE|CAPTURE|INFO|assert)$"
)
CALLABLE_TYPE = re.compile(
    r"\b(?:(?:std|absl)::)?(?:function|FunctionRef|AnyInvocable|"
    r"OnceCallback|RepeatingCallback)\s*<"
)
LAMBDA_VARIABLE = re.compile(r"\b(?P<name>[A-Za-z_]\w*)\s*=\s*\[")
MEMBER_FUNCTION_POINTER = re.compile(
    r"\(\s*[A-Za-z_]\w*::\s*\*\s*(?P<name>[A-Za-z_]\w*)\s*\)\s*\("
)
MEMBER_INDIRECT_CALL = re.compile(
    r"\(\s*[A-Za-z_]\w*\s*(?:->|\.)\s*\*\s*(?P<name>[A-Za-z_]\w*)\s*\)\s*\("
)
FUNCTION_POINTER_ALIAS = re.compile(
    r"\busing\s+(?P<using>[A-Za-z_]\w*)\s*=\s*[^;()]*\(\s*\*[^;)]*\)\s*\([^;]*;"
    r"|\btypedef\s+[^;()]*\(\s*\*\s*(?P<typedef>[A-Za-z_]\w*)\s*\)\s*\([^;]*;"
)
CALLABLE_ALIAS = re.compile(
    r"\busing\s+(?P<name>[A-Za-z_]\w*)\s*=\s*(?:(?:std|absl)::)?"
    r"(?:function|FunctionRef|AnyInvocable|OnceCallback|RepeatingCallback|"
    r"move_only_function)\s*<"
)
CALLBACK_TYPE = re.compile(
    r"\b(?:[A-Za-z_]\w*(?:Callback|Handler|Function|Functor|Predicate|"
    r"Visitor|Invocable|Delegate|Task|Closure)|FunctionRef|OnceCallback|"
    r"RepeatingCallback)\s*(?:<[^;{}]*>)?\s*(?:&&|&)?\s*"
    r"(?P<name>[A-Za-z_]\w*)\s*(?=[,)=])"
)


@dataclass(frozen=True)
class RepoContext:
    root: Path
    repo: str


@dataclass(frozen=True)
class LspDocument:
    uri: str
    request: Callable[[str, dict[str, object]], object]


class Clangd:
    """Small synchronous LSP client for clangd definition and symbol requests."""

    def __init__(self, root: Path, compile_commands: Path) -> None:
        self.root = root.resolve()
        self.process = subprocess.Popen(  # noqa: S603 - Starts clangd as the language server used for benchmark extraction.
            [  # noqa: S607 - Starts the clangd executable available to the benchmark environment.
                "clangd",
                f"--compile-commands-dir={compile_commands}",
                "--background-index=false",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self._next_id = 1
        self.request(
            "initialize",
            {
                "processId": None,
                "rootUri": self.root.as_uri(),
                "capabilities": {"general": {"positionEncodings": ["utf-16"]}},
            },
        )
        self.notify("initialized", {})

    def request(self, method: str, params: dict[str, object]) -> object:
        request_id = self._next_id
        self._next_id += 1
        self._send(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        while True:
            response = self._receive()
            if response.get("id") == request_id:
                if "error" in response:
                    raise RuntimeError(f"clangd {method}: {response['error']}")
                return response.get("result")

    def notify(self, method: str, params: dict[str, object]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def open(self, file: Path) -> str:
        uri = file.resolve().as_uri()
        self.notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": "cpp",
                    "version": 1,
                    "text": file.read_text(encoding="utf-8", errors="replace"),
                }
            },
        )
        return uri

    def close(self) -> None:
        if self.process.poll() is None:
            try:
                self.request("shutdown", {})
                self.notify("exit", {})
                self.process.wait(timeout=5)
            except BrokenPipeError, RuntimeError, subprocess.TimeoutExpired:
                self.process.terminate()

    def _send(self, message: dict[str, object]) -> None:
        if self.process.stdin is None:
            raise RuntimeError("clangd stdin is unavailable")
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
        self.process.stdin.write(f"Content-Length: {len(payload)}\r\n\r\n".encode())
        self.process.stdin.write(payload)
        self.process.stdin.flush()

    def _receive(self) -> dict[str, object]:
        if self.process.stdout is None:
            raise RuntimeError("clangd stdout is unavailable")
        headers: dict[str, str] = {}
        while True:
            line = self.process.stdout.readline()
            if not line:
                raise RuntimeError("clangd closed its output")
            if line in {b"\r\n", b"\n"}:
                break
            key, value = line.decode("ascii").split(":", 1)
            headers[key.lower()] = value.strip()
        size = int(headers["content-length"])
        return json.loads(self.process.stdout.read(size))


def _is_excluded_source_path(file: Path, root: Path) -> bool:
    try:
        parts = file.resolve().relative_to(root.resolve()).parts
    except ValueError:
        return True
    return any(part.lower() in EXCLUDED_PATH_PARTS for part in parts)


def _is_test_macro_call(name: str) -> bool:
    return TEST_MACRO.fullmatch(name.rsplit("::", maxsplit=1)[-1]) is not None


def _matching_angle(source: str, opening: int) -> int | None:
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "<":
            depth += 1
        elif source[index] == ">":
            depth -= 1
            if depth == 0:
                return index
    return None


def _higher_order_names(source: str) -> set[str]:
    names = {match.group("name") for match in LAMBDA_VARIABLE.finditer(source)}
    names.update(match.group("name") for match in CALLBACK_TYPE.finditer(source))
    for match in CALLABLE_TYPE.finditer(source):
        closing = _matching_angle(source, match.end() - 1)
        if closing is None:
            continue
        declaration = re.match(r"\s*(?P<name>[A-Za-z_]\w*)\b", source[closing + 1 :])
        if declaration:
            names.add(declaration.group("name"))
    alias_types = _alias_names(source)
    names.update(_typed_names(source, alias_types, require_parameter=False))
    names.update(
        _typed_names(
            source,
            set(re.findall(r"\b(?:typename|class)\s+([A-Za-z_]\w*)", source)),
            require_parameter=True,
        )
    )
    for pattern in (INDIRECT_CALL, MEMBER_FUNCTION_POINTER):
        names.update(match.group("name") for match in pattern.finditer(source))
    return {
        name
        for name in names
        if not _is_keyword(name)
        and not _looks_like_macro(name)
        and name not in _declared_type_names(source)
    }


def _is_keyword(name: str) -> bool:
    return name in KEYWORDS


def _looks_like_macro(name: str) -> bool:
    return MACRO_NAME.fullmatch(name) is not None


def _declared_type_names(source: str) -> set[str]:
    return {
        match.group("name") or match.group("using") or match.group("typedef")
        for match in TYPE_DECLARATION.finditer(source)
        if match.group("name") or match.group("using") or match.group("typedef")
    }


@lru_cache(maxsize=64)
def _source_lines(path: Path) -> tuple[str, ...]:
    return tuple(path.read_text(encoding="utf-8", errors="replace").splitlines())


def _declaration_is_virtual(path: Path, line: int) -> bool:
    """Report whether the declaration around a target line is virtual."""
    if not path.is_file():
        return False
    lines = _source_lines(path)
    window = lines[max(0, line - 3) : line + 2]
    return any(re.search(r"\bvirtual\b", text) for text in window)


def _runtime_callable_names(source: str) -> set[str]:
    return {match.group("name") for match in RUNTIME_LOOKUP.finditer(source)}


def _is_initializer_site(source: str, offset: int) -> bool:
    """Report whether a site opens a constructor initializer list
    (``: member(...)``)."""
    line_start = source.rfind("\n", 0, offset) + 1
    return source[line_start:offset].lstrip().startswith(":")


def _is_comment_or_directive(source: str, offset: int) -> bool:
    line_start = source.rfind("\n", 0, offset) + 1
    return source[line_start:offset].lstrip().startswith(("//", "/*", "*", "#"))


def _last_identifier(name: str) -> str:
    return re.split(r"::|->|\.", name)[-1].strip()


def _alias_names(source: str) -> set[str]:
    names = {
        alias
        for match in FUNCTION_POINTER_ALIAS.finditer(source)
        for alias in [match.group("using") or match.group("typedef")]
        if alias
    }
    names.update(match.group("name") for match in CALLABLE_ALIAS.finditer(source))
    return names


PARAMETER_PREFIX = re.compile(r"[,(]\s*$")
TYPE_ALIAS_PREFIX = re.compile(r"\b(?:typedef|using)\b[^;{}]*$")


def _typed_names(
    source: str, type_names: set[str], *, require_parameter: bool
) -> set[str]:
    """Names declared with one of ``type_names`` (parameters, locals or fields)."""
    names: set[str] = set()
    for type_name in type_names:
        pattern = re.compile(
            rf"\b{re.escape(type_name)}\s*(?:&&|&)?\s*"
            rf"(?P<name>[A-Za-z_]\w*)\s*(?=[,)=;{{])"
        )
        for match in pattern.finditer(source):
            prefix = source[max(0, match.start() - 60) : match.start()]
            if require_parameter and not PARAMETER_PREFIX.search(prefix):
                continue
            if TYPE_ALIAS_PREFIX.search(prefix):
                continue
            names.add(match.group("name"))
    return names


def export_sites(
    root: Path,
    compile_database: Path,
    repo: str,
    invoke: Callable[[str, dict[str, object]], object] | None = None,
    *,
    max_files: int = MAX_SOURCE_FILES,
    higher_order_files: int = 0,
) -> list[dict[str, object]]:
    """Export call records from compile-database files using clangd definitions."""
    root = root.resolve()
    context = RepoContext(root, repo)
    database = json.loads(compile_database.read_text(encoding="utf-8"))
    files = sorted(
        {
            file
            for entry in database
            if Path(str(entry.get("file", ""))).suffix.lower()
            in {".cc", ".cpp", ".cxx", ".c++", ".mm"}
            for file in [_compile_file(root, entry)]
            if not _is_excluded_source_path(file, root)
        }
    )
    files = [
        file
        for file in files
        if file.is_file() and file.stat().st_size <= MAX_SOURCE_BYTES
    ]
    candidates = files
    files = _evenly_spaced(candidates, max_files)
    extra_files = _evenly_spaced(
        [file for file in candidates if file not in files], higher_order_files
    )
    client = None
    if invoke is None:
        client = Clangd(root, compile_database.parent)
        invoke = client.request
    records: list[dict[str, object]] = []
    try:
        for index, file in enumerate(files, start=1):
            if not file.is_file() or not file.resolve().is_relative_to(root):
                continue
            print(
                f"clangd file {index}/{len(files)}: {file.relative_to(root)}",
                file=sys.stderr,
                flush=True,
            )
            uri = client.open(file) if client else file.resolve().as_uri()
            source = file.read_text(encoding="utf-8", errors="replace")
            function_symbols = _function_symbols(
                invoke("textDocument/documentSymbol", {"textDocument": {"uri": uri}})
            )
            records.extend(
                _hierarchy_records(
                    context,
                    file,
                    source,
                    _evenly_spaced(function_symbols, MAX_FUNCTIONS_PER_FILE),
                    LspDocument(uri, invoke),
                )
            )
            records.extend(
                _member_records(
                    context,
                    file,
                    source,
                    function_symbols,
                    LspDocument(uri, invoke),
                    records,
                )
            )
            records.extend(
                _higher_order_records(context, file, source, function_symbols, records)
            )
        for index, file in enumerate(extra_files, start=1):
            if not file.is_file() or not file.resolve().is_relative_to(root):
                continue
            print(
                f"clangd callback file {index}/{len(extra_files)}: "
                f"{file.relative_to(root)}",
                file=sys.stderr,
                flush=True,
            )
            uri = client.open(file) if client else file.resolve().as_uri()
            source = file.read_text(encoding="utf-8", errors="replace")
            function_symbols = _function_symbols(
                invoke("textDocument/documentSymbol", {"textDocument": {"uri": uri}})
            )
            records.extend(
                _higher_order_records(context, file, source, function_symbols, records)
            )
    finally:
        if client:
            client.close()
    unique = _unique_sites(records)
    counts = {
        call_class: sum(record["call_class"] == call_class for record in unique)
        for call_class in CLASS_NAMES
    }
    print(f"classes: {counts}", file=sys.stderr, flush=True)
    return sorted(
        unique,
        key=lambda record: (record["file"], record["line"], record["call_class"]),
    )


def _unique_sites(
    records: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Keep one record per ``(repo, file, line, call_name)`` call site."""
    best: dict[tuple[str, str, int, str], dict[str, object]] = {}
    for record in records:
        item = dict(record)
        key = (
            str(item["repo"]),
            str(item["file"]),
            int(item["line"]),
            str(item["call_name"]),
        )
        current = best.get(key)
        if current is None or _truth_rank(item) < _truth_rank(current):
            best[key] = item
    return list(best.values())


def _truth_rank(record: Mapping[str, object]) -> tuple[bool, str, str, str]:
    """Prefer clangd-resolved records over syntactically classified ones."""
    return (
        record["ground_truth"] == "unknown",
        str(record["truth_source"]),
        str(record["call_class"]),
        str(record["ground_truth"]),
    )


def export_unresolved_member_candidates(
    root: Path, repo: str
) -> list[dict[str, object]]:
    """Create explicit unknown review candidates when a compile database is
    unavailable."""
    root = root.resolve()
    records = []
    files = sorted(
        file
        for suffix in ("*.cc", "*.cpp", "*.cxx")
        for file in (root / "src").rglob(suffix)
    )
    for file in files:
        if file.stat().st_size > MAX_SOURCE_BYTES or _is_excluded_source_path(
            file, root
        ):
            continue
        source = file.read_text(encoding="utf-8", errors="replace")
        for match in MEMBER_CALL.finditer(source):
            call_name = match.group("name")
            if (
                _is_keyword(call_name)
                or _looks_like_macro(call_name)
                or _is_comment_or_directive(source, match.start())
            ):
                continue
            line_number = source.count("\n", 0, match.start())
            relative = file.relative_to(root)
            record = {
                "repo": repo,
                "language": "cpp",
                "file": relative.as_posix(),
                "line": line_number + 1,
                "call_name": call_name,
                "call_class": "member",
                "ground_truth": "unknown",
                "measured_edge": None,
                "measured_status": "opaque",
                "truth_source": "source-only-partial",
                "function_id": None,
                "module": relative.parent.as_posix(),
                "ground_truth_module": None,
                "measured_module": None,
            }
            validate_record(record)
            records.append(record)
    unique = {(row["file"], row["line"], row["call_name"]): row for row in records}
    return [unique[key] for key in sorted(unique)]


def _evenly_spaced[T](items: list[T], limit: int) -> list[T]:
    if len(items) <= limit:
        return items
    step = len(items) / limit
    return [items[int(index * step)] for index in range(limit)]


def iter_calls(source: str) -> Iterable[re.Match[str]]:
    """Yield plausible call expressions, excluding keywords, macros and control flow."""
    for match in CALL.finditer(source):
        name = match.group("name").replace(" ", "")
        simple_name = _last_identifier(name)
        if (
            _is_keyword(simple_name)
            or _looks_like_macro(simple_name)
            or _is_test_macro_call(simple_name)
        ):
            continue
        line_start = source.rfind("\n", 0, match.start()) + 1
        if source[line_start : match.start()].lstrip().startswith(("#", "//", "*")):
            continue
        if _is_function_definition(source, match.end() - 1):
            continue
        yield match


def _is_function_definition(source: str, opening: int) -> bool:
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "(":
            depth += 1
        elif source[index] == ")":
            depth -= 1
            if depth == 0:
                suffix = source[index + 1 :]
                return (
                    re.match(r"\s*(?:const\s*)?(?:noexcept\s*)?\{", suffix) is not None
                )
    return False


def review_stub(record: Mapping[str, object]) -> dict[str, object]:
    """Return a two-reviewer verification stub for an unresolved call site."""
    return {
        "repo": record["repo"],
        "file": record["file"],
        "line": record["line"],
        "call_name": record["call_name"],
        "call_class": record["call_class"],
        "reviewer_1": {"target": None, "reason": None},
        "reviewer_2": {"target": None, "reason": None},
        "agreement": None,
    }


def _compile_file(root: Path, entry: Mapping[str, object]) -> Path:
    directory = Path(str(entry.get("directory", root)))
    file = Path(str(entry["file"]))
    return (directory / file).resolve() if not file.is_absolute() else file.resolve()


def _function_symbols(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, object]] = []
    for symbol in value:
        if not isinstance(symbol, dict):
            continue
        if symbol.get("kind") in FUNCTION_KINDS:
            location = symbol.get("location")
            item_range = symbol.get("range")
            if isinstance(location, dict) and isinstance(location.get("range"), dict):
                item_range = location["range"]
            if isinstance(item_range, dict):
                result.append({**symbol, "range": item_range})
        result.extend(_function_symbols(symbol.get("children")))
    return result


@lru_cache(maxsize=4)
def _cached_higher_order_names(source: str) -> frozenset[str]:
    return frozenset(_higher_order_names(source))


def _hierarchy_records(
    context: RepoContext,
    file: Path,
    source: str,
    symbols: list[dict[str, object]],
    document: LspDocument,
) -> list[dict[str, object]]:
    records = []
    for symbol in symbols:
        position = _symbol_position(source, symbol)
        if position is None:
            continue
        prepared = document.request(
            "textDocument/prepareCallHierarchy",
            {"textDocument": {"uri": document.uri}, "position": position},
        )
        if not isinstance(prepared, list):
            continue
        for caller in prepared:
            outgoing = document.request("callHierarchy/outgoingCalls", {"item": caller})
            if not isinstance(outgoing, list):
                continue
            for call in outgoing:
                if not isinstance(call, dict):
                    continue
                target = call.get("to")
                ranges = call.get("fromRanges")
                if not isinstance(target, dict) or not isinstance(ranges, list):
                    continue
                for call_range in ranges:
                    if not isinstance(call_range, dict):
                        continue
                    record = _hierarchy_record(
                        context,
                        file,
                        source,
                        caller,
                        target,
                        call_range,
                    )
                    if record is not None:
                        validate_record(record)
                        records.append(record)
    return records


def _member_records(
    context: RepoContext,
    file: Path,
    source: str,
    symbols: list[dict[str, object]],
    document: LspDocument,
    known_records: list[dict[str, object]],
) -> list[dict[str, object]]:
    known_sites = {
        (int(record["line"]), str(record["call_name"]))
        for record in known_records
        if record["file"] == file.resolve().relative_to(context.root).as_posix()
    }
    matches = _evenly_spaced(
        list(MEMBER_CALL.finditer(source)), MAX_MEMBER_CHECKS_PER_FILE
    )
    rows = []
    for match in matches:
        offset = match.start()
        line_number = source.count("\n", 0, offset)
        call_name = match.group("name")
        if (
            (line_number + 1, call_name) in known_sites
            or _is_keyword(call_name)
            or _looks_like_macro(call_name)
            or _is_test_macro_call(call_name)
            or _is_comment_or_directive(source, offset)
        ):
            continue
        caller = _enclosing_function(symbols, line_number)
        if caller is None:
            continue
        definitions = document.request(
            "textDocument/definition",
            {
                "textDocument": {"uri": document.uri},
                "position": _position(source, match.start("name")),
            },
        )
        row = _member_record(context, file, source, match, caller, definitions)
        if row is None:
            continue
        validate_record(row)
        rows.append(row)
    return rows


def _higher_order_records(
    context: RepoContext,
    file: Path,
    source: str,
    symbols: list[dict[str, object]],
    known_records: list[dict[str, object]],
) -> list[dict[str, object]]:
    known_sites = {
        (int(record["line"]), str(record["call_name"]))
        for record in known_records
        if record["file"] == file.resolve().relative_to(context.root).as_posix()
    }
    rows = []
    matches: list[tuple[re.Match[str], str, int, bool]] = []
    for pattern in (INDIRECT_CALL, MEMBER_FUNCTION_POINTER, MEMBER_INDIRECT_CALL):
        matches.extend(
            (match, _last_identifier(match.group("name")), match.start(), False)
            for match in pattern.finditer(source)
        )
    callable_names = _higher_order_names(source)
    matches.extend(
        (
            match,
            _last_identifier(match.group("name")),
            match.start("name"),
            "::" in match.group("name"),
        )
        for match in iter_calls(source)
        if _last_identifier(match.group("name")) in callable_names
    )
    runtime_names = _runtime_callable_names(source)
    emitted_sites = set(known_sites)
    for _match, call_name, offset, qualified in matches:
        if qualified or _is_keyword(call_name) or _looks_like_macro(call_name):
            continue
        if _looks_like_indirect_declaration(source, offset) or _is_initializer_site(
            source, offset
        ):
            continue
        line_number = source.count("\n", 0, offset)
        site = (line_number + 1, call_name)
        if site in emitted_sites or _is_test_macro_call(call_name):
            continue
        caller = _enclosing_function(symbols, line_number)
        if caller is None:
            continue
        call_class = "dynamic" if call_name in runtime_names else "higher_order"
        row = _unknown_record(context, file, line_number, call_class, caller, call_name)
        validate_record(row)
        rows.append(row)
        emitted_sites.add(site)
    return rows


def _member_record(
    context: RepoContext,
    file: Path,
    source: str,
    match: re.Match[str],
    caller: Mapping[str, object],
    definitions: object,
) -> dict[str, object] | None:
    line_number = source.count("\n", 0, match.start())
    location = _first_location(definitions)
    target_path = _uri_path(location.get("uri")) if location else None
    if target_path is None:
        return None
    in_repo = target_path.is_relative_to(context.root) and not _is_excluded_source_path(
        target_path, context.root
    )
    target_range = location.get("range")
    target_start = target_range.get("start") if isinstance(target_range, dict) else {}
    target_line = int(target_start.get("line", 0)) + 1
    target_name = match.group("name")
    target_id = (
        f"{target_path.relative_to(context.root).as_posix()}:{target_line}:{target_name}"
        if in_repo
        else "external"
    )
    caller_path = file.resolve().relative_to(context.root)
    caller_range = caller.get("selectionRange") or caller.get("range")
    caller_start = caller_range.get("start") if isinstance(caller_range, dict) else {}
    caller_id = (
        f"{caller_path.as_posix()}:{int(caller_start.get('line', 0)) + 1}:"
        f"{caller.get('name', '<anonymous>')}"
    )
    call_class = "member"
    if in_repo and _declaration_is_virtual(target_path, target_line - 1):
        call_class = "dynamic"
    return {
        "repo": context.repo,
        "language": "cpp",
        "file": caller_path.as_posix(),
        "line": line_number + 1,
        "call_name": target_name,
        "call_class": call_class,
        "ground_truth": target_id,
        "measured_edge": None,
        "measured_status": "unresolved" if in_repo else "external",
        "truth_source": "clangd-21",
        "function_id": caller_id,
        "module": caller_path.parent.as_posix(),
        "ground_truth_module": (
            target_path.relative_to(context.root).parent.as_posix() if in_repo else None
        ),
        "measured_module": None,
    }


DECLARATION_TAIL = re.compile(
    r"(?:[A-Za-z_]\w*(?:::\w+)*(?:\s*<[^<>;()]*>)?\s*[&*]*)\s*$"
)
CALL_PREFIX_TOKENS = set("([{,;=+-/%|^!?:")
CALL_PREFIX_KEYWORDS = {"return", "co_return", "throw", "case", "else", "do"}


def _looks_like_indirect_declaration(source: str, offset: int) -> bool:
    """Report whether an indirect site is a declaration such as ``void (*cb)(int)``."""
    line_start = source.rfind("\n", 0, offset) + 1
    prefix = source[line_start:offset].rstrip()
    if not prefix:
        return False
    if "=" in prefix or prefix[-1] in CALL_PREFIX_TOKENS:
        return False
    token = re.search(r"([A-Za-z_]\w*)\s*[&*]*\s*$", prefix)
    if token and token.group(1) in CALL_PREFIX_KEYWORDS:
        return False
    return DECLARATION_TAIL.search(prefix) is not None


def _unknown_record(
    context: RepoContext,
    file: Path,
    line_number: int,
    call_class: str,
    caller: Mapping[str, object],
    call_name: str,
) -> dict[str, object]:
    caller_path = file.resolve().relative_to(context.root)
    caller_range = caller.get("selectionRange") or caller.get("range")
    caller_start = caller_range.get("start") if isinstance(caller_range, dict) else {}
    function_id = (
        f"{caller_path.as_posix()}:{int(caller_start.get('line', 0)) + 1}:"
        f"{caller.get('name', '<anonymous>')}"
    )
    return {
        "repo": context.repo,
        "language": "cpp",
        "file": caller_path.as_posix(),
        "line": line_number + 1,
        "call_name": call_name,
        "call_class": call_class,
        "ground_truth": "unknown",
        "measured_edge": None,
        "measured_status": "opaque",
        "truth_source": "two_human_stub",
        "function_id": function_id,
        "module": caller_path.parent.as_posix(),
        "ground_truth_module": None,
        "measured_module": None,
    }


def _symbol_position(
    source: str, symbol: Mapping[str, object]
) -> dict[str, int] | None:
    selection = symbol.get("selectionRange")
    if isinstance(selection, dict) and isinstance(selection.get("start"), dict):
        return selection["start"]
    item_range = symbol.get("range")
    if not isinstance(item_range, dict):
        return None
    start = item_range.get("start")
    if not isinstance(start, dict):
        return None
    line_number = int(start["line"])
    lines = source.splitlines()
    if line_number >= len(lines):
        return None
    name = str(symbol.get("name", ""))
    column = lines[line_number].find(name)
    if column < 0:
        return None
    return {"line": line_number, "character": column}


def _hierarchy_record(
    context: RepoContext,
    file: Path,
    source: str,
    caller: Mapping[str, object],
    target: Mapping[str, object],
    call_range: Mapping[str, object],
) -> dict[str, object] | None:
    target_path = _uri_path(target.get("uri"))
    if target_path is None:
        return None
    start = call_range.get("start")
    target_range = target.get("selectionRange") or target.get("range")
    if not isinstance(start, dict) or not isinstance(target_range, dict):
        return None
    target_start = target_range.get("start")
    caller_range = caller.get("selectionRange") or caller.get("range")
    if not isinstance(target_start, dict) or not isinstance(caller_range, dict):
        return None
    caller_start = caller_range.get("start")
    if not isinstance(caller_start, dict):
        return None
    caller_path = file.resolve().relative_to(context.root)
    target_inside = target_path.is_relative_to(
        context.root
    ) and not _is_excluded_source_path(target_path, context.root)
    line_number = int(start["line"])
    source_line = source.splitlines()[line_number]
    column = int(start["character"])
    target_name = str(target.get("name", "<anonymous>"))
    callee = _site_callee(source_line, column, target_name)
    call_name = _site_call_name(source_line, column, target_name)
    if (
        _is_test_macro_call(call_name)
        or _is_keyword(call_name)
        or _looks_like_macro(call_name)
    ):
        return None
    callable_names = _cached_higher_order_names(source)
    qualified = "::" in callee
    is_member = "->" in callee or "." in callee
    if target_name == "operator()" or (
        call_name in callable_names and not qualified and target_name != call_name
    ):
        call_class = "higher_order"
    elif int(target.get("kind", 0)) == 9:
        call_class = "constructor"
    elif is_member:
        call_class = "member"
    elif target_inside and target_path != file.resolve():
        call_class = "imported"
    else:
        call_class = "same_file"
    if (
        call_class == "member"
        and target_inside
        and _declaration_is_virtual(target_path, int(target_start["line"]))
    ):
        call_class = "dynamic"
    target_line = int(target_start["line"]) + 1
    target_id = (
        f"{target_path.relative_to(context.root).as_posix()}:{target_line}:{target_name}"
        if target_inside
        else "external"
    )
    caller_name = str(caller.get("name", "<anonymous>"))
    caller_id = (
        f"{caller_path.as_posix()}:{int(caller_start['line']) + 1}:{caller_name}"
    )
    return {
        "repo": context.repo,
        "language": "cpp",
        "file": caller_path.as_posix(),
        "line": line_number + 1,
        "call_name": call_name,
        "call_class": call_class,
        "ground_truth": target_id,
        "measured_edge": None,
        "measured_status": "unresolved" if target_inside else "external",
        "truth_source": "clangd-21",
        "function_id": caller_id,
        "module": caller_path.parent.as_posix(),
        "ground_truth_module": (
            target_path.relative_to(context.root).parent.as_posix()
            if target_inside
            else None
        ),
        "measured_module": None,
    }


def _site_call_name(source_line: str, utf16_column: int, fallback: str) -> str:
    callee = _site_callee(source_line, utf16_column, fallback)
    name = _last_identifier(callee) or fallback
    if _is_keyword(name):
        return _last_identifier(fallback) or fallback
    return name


def _site_callee(source_line: str, utf16_column: int, fallback: str) -> str:
    """Return the callee expression clangd marked, e.g. ``obj->handler``."""
    column = 0
    index = 0
    while index < len(source_line) and column < utf16_column:
        column += 2 if ord(source_line[index]) > 0xFFFF else 1
        index += 1
    expression = source_line[index:].split("(", maxsplit=1)[0]
    match = re.search(
        r"([A-Za-z_]\w*(?:(?:\s*::\s*|\s*->\s*|\s*\.\s*)[A-Za-z_]\w*)*)\s*$",
        expression,
    )
    return match.group(1).replace(" ", "") if match else fallback


def _enclosing_function(
    symbols: list[dict[str, object]], line: int
) -> dict[str, object] | None:
    candidates = []
    for symbol in symbols:
        item_range = symbol["range"]
        start = item_range["start"]["line"]
        end = item_range["end"]["line"]
        if start <= line <= end:
            candidates.append((end - start, symbol))
    return min(candidates, default=(0, None), key=lambda entry: entry[0])[1]


def _record(
    context: RepoContext,
    file: Path,
    source: str,
    match: re.Match[str],
    caller: dict[str, object],
    definitions: object,
) -> dict[str, object] | None:
    start = match.start("name")
    line_no = source.count("\n", 0, start)
    target = _first_location(definitions)
    target_path = _uri_path(target.get("uri")) if target else None
    if (
        target_path == file.resolve()
        and int(target["range"]["start"]["line"]) == line_no
    ):
        return None
    if target_path is None:
        call_class = "higher_order" if _is_indirect(source, match) else "dynamic"
        truth = "unknown"
        truth_source = "two_human_stub"
        target_id = None
        target_module = None
        status = "opaque" if call_class == "dynamic" else "unresolved"
    elif not target_path.is_relative_to(context.root) or _is_excluded_source_path(
        target_path, context.root
    ):
        call_class = "member" if _is_member_call(source, match) else "same_file"
        truth = "external"
        truth_source = "clangd-21"
        target_id = None
        target_module = None
        status = "external"
    else:
        target_range = target["range"]["start"]
        target_line = int(target_range["line"]) + 1
        target_id = (
            f"{target_path.relative_to(context.root).as_posix()}:{target_line}:"
            f"{match.group('name')}"
        )
        if _is_constructor(match, caller):
            call_class = "constructor"
        elif _is_member_call(source, match):
            call_class = "member"
        elif target_path.resolve() != file.resolve():
            call_class = "imported"
        else:
            call_class = "same_file"
        truth = target_id
        truth_source = "clangd-21"
        target_module = target_path.relative_to(context.root).parent.as_posix()
        status = "unresolved"
    caller_path = file.resolve().relative_to(context.root)
    caller_range = caller["range"]["start"]
    name = str(caller.get("name", "<anonymous>"))
    return {
        "repo": context.repo,
        "language": "cpp",
        "file": caller_path.as_posix(),
        "line": line_no + 1,
        "call_name": match.group("name"),
        "call_class": call_class,
        "ground_truth": truth,
        "measured_edge": None,
        "measured_status": status,
        "truth_source": truth_source,
        "function_id": (
            f"{caller_path.as_posix()}:{int(caller_range['line']) + 1}:{name}"
        ),
        "module": caller_path.parent.as_posix(),
        "ground_truth_module": target_module,
        "measured_module": None,
    }


def _first_location(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        return value if isinstance(value.get("uri"), str) else None
    if isinstance(value, list):
        return next((item for item in value if isinstance(item, dict)), None)
    return None


def _uri_path(uri: object) -> Path | None:
    if not isinstance(uri, str):
        return None
    parsed = urlparse(uri)
    return Path(unquote(parsed.path)).resolve() if parsed.scheme == "file" else None


def _position(source: str, offset: int) -> dict[str, int]:
    prefix = source[:offset]
    line = prefix.count("\n")
    column = len(prefix.rsplit("\n", 1)[-1].encode("utf-16-le")) // 2
    return {"line": line, "character": column}


def _is_member_call(source: str, match: re.Match[str]) -> bool:
    prefix = source[
        match.start("name") : match.start("name") + len(match.group("name"))
    ]
    return "." in prefix or "->" in prefix


def _is_indirect(source: str, match: re.Match[str]) -> bool:
    prefix = source[max(0, match.start() - 4) : match.start()]
    return "(*" in prefix or "(&" in prefix


def _is_constructor(match: re.Match[str], caller: dict[str, object]) -> bool:
    name = match.group("name").split("::")[-1]
    return name[:1].isupper() and str(caller.get("name", "")) != name


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo_path", type=Path)
    parser.add_argument("repo_id")
    parser.add_argument("--compile-commands", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--review-stubs", type=Path, required=True)
    parser.add_argument("--max-files", type=int, default=MAX_SOURCE_FILES)
    parser.add_argument("--higher-order-files", type=int, default=0)
    args = parser.parse_args()
    records = export_sites(
        args.repo_path,
        args.compile_commands,
        args.repo_id,
        max_files=args.max_files,
        higher_order_files=args.higher_order_files,
    )
    _write_jsonl(args.output, records)
    _write_jsonl(
        args.review_stubs,
        (
            review_stub(record)
            for record in records
            if record["ground_truth"] == "unknown"
        ),
    )
    print(f"exported {len(records)} sites; unresolved review stubs written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
