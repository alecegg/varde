"""Java, Kotlin and Scala import dependency facts.

The parser is intentionally conservative: it certifies only imports whose
source declaration and package directory can be identified unambiguously.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .types import IMPORT_KIND, Fact, FactInput, FileRow, ImportRow


@dataclass
class ParsedSource:
    package: str | None = None
    declared: list[str] = field(default_factory=list)
    imports: list[tuple[str, bool]] = field(default_factory=list)
    partial: list[str] = field(default_factory=list)


def facts(input: FactInput) -> list[Fact]:
    imports_by_file: dict[int, list[ImportRow]] = {}
    for imp in input.imports:
        if not imp.type_only:
            imports_by_file.setdefault(imp.file_id, []).append(imp)
    declarations: dict[tuple[str, str], dict[str, FileRow]] = {}
    packages: set[str] = set()
    partial: set[str] = set()
    roots: dict[str, set[str]] = {}
    sources: list[tuple[FileRow, list[tuple[str, bool]]]] = []
    for file in input.files:
        language = language_for(file.relative)
        if language is None or not is_candidate(file):
            continue
        try:
            text = file.physical.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            continue
        parsed = parse_file(text, language)
        partial.update(parsed.partial)
        if parsed.package is None:
            continue
        package = parsed.package
        packages.add(package)
        roots.setdefault(package, set()).add(source_root(file.relative))
        for name in parsed.declared:
            declarations.setdefault((package, name), {}).setdefault(unit(file), file)
        if not file.is_test and not file.is_tooling:
            sources.append((file, parsed.imports))

    output: list[Fact] = []
    for source, directives in sources:
        indexed = imports_by_file.get(source.id, [])
        for _specifier, plain, imp in pair_imports(indexed, directives):
            if plain:
                result = import_fact(
                    source, imp, packages, partial, roots, declarations
                )
                if result is not None:
                    output.append(result)
    return output


def language_for(path: str) -> str | None:
    ext = Path(path).suffix
    return {".java": "java", ".kt": "kotlin", ".kts": "kotlin", ".scala": "scala"}.get(
        ext
    )


def is_candidate(file: FileRow) -> bool:
    parts = Path(file.relative).parts
    suffixes = (
        ".min.js",
        ".min.mjs",
        ".min.cjs",
        ".min.css",
        ".bundle.js",
        ".bundle.mjs",
        ".pb.go",
        ".gen.go",
        ".gen.ts",
        ".gen.tsx",
        ".gen.js",
        ".gen.mjs",
        ".gen.cjs",
    )
    excluded = {
        "target",
        "node_modules",
        "dist",
        "build",
        "vendor",
        "third_party",
        "third-party",
        "bower_components",
        ".next",
        ".nuxt",
        "grammars",
    }
    return (
        language_for(file.relative) is not None
        and not any(
            part in excluded or part.endswith(("_fixture", "_fixtures"))
            for part in parts
        )
        and not any(
            parts[i : i + 2]
            in (("priv", "static"), ("alembic", "versions"), ("migrations", "versions"))
            for i in range(len(parts) - 1)
        )
        and not Path(file.relative).name.lower().endswith(suffixes)
        and not any(
            part in {"build-logic", "buildSrc", "build-settings-logic"}
            for part in Path(file.relative).parts
        )
        and not is_build_script(file.relative)
    )


def is_build_script(path: str) -> bool:
    name = Path(path).name
    return name.endswith(".gradle.kts") or name in {"build.gradle", "settings.gradle"}


def unit(file: FileRow) -> str:
    parent = Path(file.relative).parent.as_posix()
    return parent if parent != "." else "."


def source_root(path: str) -> str:
    parts = path.split("/")
    for i in range(max(0, len(parts) - 2)):
        if parts[i] == "src":
            return "/".join(parts[: i + 3])
    return Path(path).parent.as_posix()


def import_fact(
    source: FileRow,
    imp: ImportRow,
    packages: set[str],
    partial: set[str],
    roots: dict[str, set[str]],
    declarations: dict[tuple[str, str], dict[str, FileRow]],
) -> Fact | None:
    split = split_specifier(imp.specifier)
    if split is None:
        return None
    package, name = split
    if f"{package}.{name}" in packages:
        return None
    from_unit = unit(source)
    module_class = name.endswith("$") and len(name) > 1
    lookup = name[:-1] if module_class else name
    targets = declarations.get((package, lookup), {})
    if targets:
        if len(targets) != 1:
            return None
        to_unit, target = next(iter(targets.items()))
        if (
            target.is_test
            or target.is_tooling
            or (module_class and language_for(target.relative) != "scala")
            or to_unit == from_unit
            or target.id == source.id
        ):
            return None
        return Fact(
            source.id,
            from_unit,
            target.id,
            to_unit,
            IMPORT_KIND,
            "certified",
            imp.id,
            imp.specifier,
        )
    if module_class:
        return None
    constant = "_" in name and not any(char.islower() for char in name)
    looks_like_type = bool(name) and name[0].isupper() and not constant
    if not (
        package in packages
        and package not in partial
        and looks_like_type
        and source_root(source.relative) in roots.get(package, set())
    ):
        return None
    return Fact(
        source.id, from_unit, None, None, IMPORT_KIND, "missing", imp.id, imp.specifier
    )


def split_specifier(spec: str) -> tuple[str, str] | None:
    if "/" not in spec:
        return None
    package, name = spec.rsplit("/", 1)
    if (
        not package
        or not name
        or not all(is_identifier(part) for part in package.split("/"))
        or not is_identifier(name)
    ):
        return None
    return package.replace("/", "."), name


def is_identifier(part: str) -> bool:
    return (
        bool(part)
        and (part[0].isalpha() or part[0] in "_$")
        and all(c.isalnum() or c in "_$" for c in part[1:])
    )


def pair_imports(imports: list[ImportRow], directives: list[tuple[str, bool]]):
    pairs = []
    next_index = 0
    for spec, plain in directives:
        found = next(
            (
                i
                for i in range(next_index, len(imports))
                if imports[i].specifier == spec
            ),
            None,
        )
        if found is not None:
            pairs.append((spec, plain, imports[found]))
            next_index = found + 1
    return pairs


def parse_file(text: str, language: str) -> ParsedSource:
    package_parts: list[str] = []
    parsed = ParsedSource()
    block = False
    body_seen = False
    for line in code_lines(text):
        trimmed = line.strip()
        if not trimmed:
            continue
        if trimmed.startswith("package "):
            kind, name = package_clause(trimmed[8:])
            if kind == "plain" and not body_seen:
                package_parts.extend(name.split("."))
            elif kind == "block":
                block = True
                parsed.partial.append(".".join([*package_parts, name]).strip("."))
            elif kind == "unknown":
                block = True
            continue
        imported = import_clause(trimmed, language)
        if imported is not None:
            body_seen = True
            parsed.imports.append(imported)
        elif not line[:1].isspace():
            name = declaration_name(trimmed, language)
            if name:
                body_seen = True
                parsed.declared.append(name)
    if block:
        parsed.declared.clear()
        parsed.imports.clear()
    if package_parts and not block:
        parsed.package = ".".join(package_parts)
    return parsed


def package_clause(rest: str) -> tuple[str, str]:
    rest = rest.strip()
    if rest.startswith("object "):
        name = rest[7:].split()[0].rstrip("{")
        return (
            ("block", name)
            if name and all(is_identifier(p) for p in name.split("."))
            else ("unknown", "")
        )
    if "{" in rest or rest.endswith(":"):
        name = rest.rstrip("{").rstrip(":").strip()
        return (
            ("block", name)
            if name and all(is_identifier(p) for p in name.split("."))
            else ("unknown", "")
        )
    name = rest.removesuffix(";").strip()
    return (
        ("plain", name)
        if name and all(is_identifier(p) for p in name.split("."))
        else ("unknown", "")
    )


def import_clause(line: str, language: str) -> tuple[str, bool] | None:
    if not line.startswith("import") or len(line) == 6 or not line[6].isspace():
        return None
    rest = line[6:].strip()
    if language == "java":
        static = rest == "static" or rest.startswith("static ")
        path = rest.removeprefix("static").strip().removesuffix(";").strip()
        wildcard = path.endswith(".*")
        if wildcard:
            path = path[:-2]
        plain = not static and not wildcard
    elif language == "kotlin":
        path = rest.split(" as ", 1)[0].strip()
        wildcard = path.endswith(".*")
        if wildcard:
            path = path[:-2]
        plain = not wildcard
    else:
        selector = "{" in rest
        path = rest.split("{", 1)[0].rstrip(".").strip()
        wildcard = path.endswith(("._", ".*"))
        path = path.removesuffix("._").removesuffix(".*").strip()
        plain = not selector and not wildcard
    if not path or "*" in path:
        return None
    return path.replace(".", "/"), plain


def declaration_name(line: str, language: str) -> str | None:
    text = strip_annotations(line)
    words = text.split(None, 1)
    if not words:
        return None
    word, rest = words[0], words[1] if len(words) > 1 else ""
    modifiers = (
        JAVA_MODIFIERS
        if language == "java"
        else KOTLIN_MODIFIERS
        if language == "kotlin"
        else SCALA_MODIFIERS
    )
    keywords = (
        JAVA_DECLS
        if language == "java"
        else KOTLIN_DECLS
        if language == "kotlin"
        else SCALA_DECLS
    )
    for _ in range(12):
        if word == "@interface":
            return identifier(rest)
        base = word.split("[", 1)[0]
        if base not in modifiers:
            break
        if word in {"enum", "fun"}:
            next_word = rest.split(None, 1)[0] if rest.split() else ""
            if next_word.split("[", 1)[0] not in keywords:
                break
        parts = rest.split(None, 1)
        if not parts:
            return None
        word, rest = parts[0], parts[1] if len(parts) > 1 else ""
    if word == "@interface":
        return identifier(rest)
    if word.split("[", 1)[0] not in keywords:
        return None
    if word in {"fun", "def", "val", "var", "type"}:
        rest = rest.lstrip()
        if rest.startswith("<"):
            rest = (after_angle(rest) or "").lstrip()
        end = delimiter_index(rest)
        return identifier(rest[:end].rsplit(".", 1)[-1])
    return identifier(rest)


JAVA_DECLS = {"class", "interface", "enum", "record"}
KOTLIN_DECLS = {"class", "interface", "object", "typealias", "fun", "val", "var"}
SCALA_DECLS = {"class", "trait", "object", "type", "given", "def", "val", "var", "enum"}
JAVA_MODIFIERS = {
    "public",
    "protected",
    "private",
    "abstract",
    "final",
    "static",
    "sealed",
    "non-sealed",
    "strictfp",
    "default",
    "synchronized",
    "native",
    "transient",
    "volatile",
}
KOTLIN_MODIFIERS = {
    "public",
    "private",
    "protected",
    "internal",
    "open",
    "abstract",
    "sealed",
    "data",
    "value",
    "inline",
    "fun",
    "annotation",
    "enum",
    "companion",
    "expect",
    "actual",
    "external",
    "lateinit",
    "operator",
    "infix",
    "suspend",
    "tailrec",
    "const",
    "crossinline",
    "noinline",
    "vararg",
    "override",
}
SCALA_MODIFIERS = {
    "case",
    "abstract",
    "final",
    "sealed",
    "implicit",
    "lazy",
    "override",
    "private",
    "protected",
    "erased",
    "inline",
    "opaque",
    "open",
    "transparent",
    "infix",
    "extension",
}


def identifier(text: str) -> str | None:
    text = text.lstrip()
    end = next(
        (i for i, c in enumerate(text) if not (c.isalnum() or c in "_$")), len(text)
    )
    value = text[:end]
    return value if is_identifier(value) else None


def strip_annotations(text: str) -> str:
    while True:
        text = text.lstrip()
        if not text.startswith("@") or text.startswith("@interface"):
            return text
        end = (
            next(
                (i for i, c in enumerate(text[1:]) if not (c.isalnum() or c in "_$.")),
                len(text) - 1,
            )
            + 1
        )
        text = text[end:].lstrip()
        if text.startswith("("):
            depth = 0
            for i, char in enumerate(text):
                depth += (char == "(") - (char == ")")
                if depth == 0:
                    text = text[i + 1 :]
                    break
            else:
                return ""


def after_angle(text: str) -> str | None:
    depth = 0
    for i, char in enumerate(text):
        if char == "<":
            depth += 1
        elif char == ">":
            depth -= 1
            if depth == 0:
                return text[i + 1 :]
    return None


def delimiter_index(text: str) -> int:
    depth = 0
    for i, char in enumerate(text):
        if char == "<":
            depth += 1
        elif char == ">":
            depth = max(0, depth - 1)
        elif depth == 0 and (char in "(=[{:" or char.isspace()):
            return i
    return len(text)


def code_lines(text: str) -> list[str]:
    lines = []
    in_block = False
    quote: str | None = None
    triple = False
    raw_lines = text.split("\n")
    if raw_lines and raw_lines[-1] == "":
        raw_lines.pop()
    for index, raw in enumerate(raw_lines):
        if index < len(raw_lines) - 1:
            raw = raw.removesuffix("\r")  # noqa: PLW2901 - CR stripped except on last line
        code = []
        i = 0
        escaped = False
        while i < len(raw):
            char = raw[i]
            if in_block:
                if raw.startswith("*/", i):
                    in_block = False
                    i += 2
                else:
                    i += 1
                continue
            if quote:
                if raw.startswith('"""', i) and triple and not escaped:
                    code.append('"""')
                    quote = None
                    triple = False
                    i += 3
                    continue
                code.append(char)
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote and not triple:
                    quote = None
                i += 1
                continue
            if raw.startswith("/*", i):
                in_block = True
                i += 2
                continue
            if raw.startswith("//", i):
                break
            if raw.startswith('"""', i):
                quote = '"'
                triple = True
                code.append('"""')
                i += 3
                continue
            if char in {'"', "`"}:
                quote = char
                code.append(char)
                i += 1
                continue
            code.append(char)
            i += 1
        lines.append("".join(code))
    return lines
