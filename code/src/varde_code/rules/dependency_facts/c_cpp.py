"""C and C++ include dependency facts."""

from __future__ import annotations

from pathlib import Path

from ...parse import language_for_path
from .types import (
    Fact,
    FactInput,
    FileRow,
    ImportRow,
    certified_fact,
    indexed_paths,
    missing_fact,
    physical_targets,
    resolve_relative_path,
)


def facts(input: FactInput) -> list[Fact]:
    by_id = {file.id: file for file in input.files}
    indexed = indexed_paths(input.files)
    imports_by_file: dict[int, list[ImportRow]] = {}
    for imp in input.imports:
        imports_by_file.setdefault(imp.file_id, []).append(imp)
    tree_names: set[str] | None = None
    output: list[Fact] = []
    for source in input.files:
        if source.is_test or source.is_tooling or not is_c_cpp(source):
            continue
        imports = imports_by_file.get(source.id)
        if not imports:
            continue
        try:
            text = source.physical.read_text(encoding="utf-8")
        except OSError, UnicodeError:
            continue
        root = repository_root(source)
        for imp, include in pair_includes(imports, scan_includes(text)):
            if not include.quoted or include.conditional or imp.type_only:
                continue
            fact, tree_names = include_fact(
                root, by_id, indexed, input.files, tree_names, source, imp
            )
            if fact is not None:
                output.append(fact)
    return output


def is_c_cpp(file: FileRow) -> bool:
    return language_for_path(file.path) in {"c", "cpp"}


def repository_root(source: FileRow) -> Path:
    root = source.physical
    for _ in Path(source.relative).parts:
        root = root.parent
    return root


def include_fact(
    root: Path,
    by_id: dict[int, FileRow],
    indexed: dict[str, list[int]],
    files: list[FileRow] | tuple[FileRow, ...],
    names: set[str] | None,
    source: FileRow,
    imp: ImportRow,
) -> tuple[Fact | None, set[str] | None]:
    spec = imp.specifier
    if not is_plain_header_path(spec):
        return None, names
    base = resolve_relative_path(source.relative, spec)
    if base is None:
        return None, names
    targets = physical_targets(root, [base])
    if len(targets.paths) == 1:
        ids = indexed.get(base, [])
        return (
            certified_fact(by_id, source, imp, ids[0]) if len(ids) == 1 else None
        ), names
    if targets.existing_path or targets.paths:
        return None, names
    if not names_repository_path(spec) or include_root_candidate(files, spec):
        return None, names
    if names is None:
        names = collect_names(root)
    basename = spec.rsplit("/", 1)[-1]
    if any(name == basename or name.startswith(f"{basename}.") for name in names):
        return None, names
    return missing_fact(source, imp), names


def is_plain_header_path(spec: str) -> bool:
    return (
        bool(spec)
        and not spec.startswith("/")
        and all(char.isascii() and (char.isalnum() or char in "_./+-") for char in spec)
    )


def names_repository_path(spec: str) -> bool:
    return spec.startswith(("./", "../"))


def include_root_candidate(
    files: list[FileRow] | tuple[FileRow, ...], spec: str
) -> bool:
    spec = spec.removeprefix("./")
    suffix = f"/{spec}"
    return any(
        file.relative == spec or file.relative.endswith(suffix) for file in files
    )


def collect_names(root: Path) -> set[str]:
    names: set[str] = set()
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir():
                    if entry.name != ".git":
                        pending.append(entry)
                else:
                    names.add(entry.name)
            except OSError:
                continue
    return names


class Include:
    def __init__(self, spec: str, quoted: bool, conditional: bool):
        self.spec = spec
        self.quoted = quoted
        self.conditional = conditional


def pair_includes(imports: list[ImportRow], includes: list[Include]):
    pairs = []
    next_index = 0
    for include in includes:
        offset = next(
            (
                i
                for i, imp in enumerate(imports[next_index:])
                if imp.specifier == include.spec
            ),
            None,
        )
        if offset is not None:
            next_index += offset
            pairs.append((imports[next_index], include))
            next_index += 1
    return pairs


class Guard:
    def __init__(self):
        self.name: str | None = None
        self.defined = False
        self.closed = False
        self.trailing = False
        self.branched = False

    def whole_file(self) -> bool:
        return self.defined and self.closed and not self.trailing and not self.branched


def scan_includes(text: str) -> list[Include]:
    depth = 0
    guard = Guard()
    found: list[tuple[Include, int]] = []
    for seen, line in enumerate(directive_lines(text), start=1):
        keyword, args = split_directive(line)
        if guard.closed:
            guard.trailing = True
        if keyword in {"if", "ifdef", "ifndef"}:
            if seen == 1:
                guard.name = guard_name(keyword, args)
            depth += 1
        elif keyword in {"else", "elif", "elifdef", "elifndef"}:
            if depth == 1:
                guard.branched = True
        elif keyword == "endif":
            depth = max(0, depth - 1)
            if depth == 0 and guard.name is not None:
                guard.closed = True
        elif keyword == "define" and seen == 2:
            guard.defined = guard.name is not None and args.split()[:1] == [guard.name]
        elif keyword == "include":
            target = include_target(args)
            if target is not None:
                spec, quoted = target
                found.append((Include(spec, quoted, False), depth))
    guard_depth = int(guard.whole_file())
    return [
        Include(item.spec, item.quoted, depth > guard_depth) for item, depth in found
    ]


def guard_name(keyword: str, args: str) -> str | None:
    compact = "".join(args.split())
    if keyword == "ifndef":
        name = args.split()[0] if args.split() else ""
    elif keyword == "if":
        if compact.startswith("!defined(") and compact.endswith(")"):
            name = compact[len("!defined(") : -1]
        elif compact.startswith("!defined"):
            name = compact[len("!defined") :]
        else:
            return None
    else:
        return None
    return name or None


def include_target(args: str) -> tuple[str, bool] | None:
    args = args.strip()
    if not args:
        return None
    opening = args[0]
    if opening == '"':
        close, quoted = '"', True
    elif opening == "<":
        close, quoted = ">", False
    else:
        return None
    end = args.find(close, 1)
    return (args[1:end], quoted) if end >= 0 else None


def split_directive(line: str) -> tuple[str, str]:
    body = line.lstrip().lstrip("#").lstrip()
    end = next(
        (
            i
            for i, char in enumerate(body)
            if not (char.isascii() and (char.isalnum() or char == "_"))
        ),
        len(body),
    )
    return body[:end], body[end:]


def directive_lines(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\\\n", "")
    return [
        line
        for line in strip_comments(text).splitlines()
        if line.lstrip().startswith("#")
    ]


def strip_comments(text: str) -> str:
    output: list[str] = []
    i = 0
    block = line_comment = False
    quote: str | None = None
    while i < len(text):
        char = text[i]
        following = text[i + 1] if i + 1 < len(text) else ""
        if char == "\n":
            line_comment = False
            quote = None
            output.append(char)
        elif block:
            if char == "*" and following == "/":
                i += 1
                block = False
                output.append(" ")
        elif line_comment:
            pass
        elif quote is not None:
            output.append(char)
            if char == "\\" and following:
                i += 1
                output.append(text[i])
            elif char == quote:
                quote = None
        elif char == "/" and following == "*":
            i += 1
            block = True
        elif char == "/" and following == "/":
            i += 1
            line_comment = True
        else:
            if char in {'"', "'"}:
                quote = char
            output.append(char)
        i += 1
    return "".join(output)
