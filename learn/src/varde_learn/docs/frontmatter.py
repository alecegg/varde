"""Validate skill frontmatter against the agentskills.io metadata rules.

YAML 1.2 scalar resolution is used here. PyYAML defaults
to YAML 1.1, so this safe loader uses YAML 1.2 boolean, integer, and float
resolvers. Without that adjustment yes/no/on/off and 1:30 would resolve as
booleans and integers in PyYAML, while YAML 1.2 treats them as strings. YAML
parse error wording may differ. This loader rejects every ``!!`` tag.
"""

from __future__ import annotations

import copy
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from varde_core.layout import skill_dirs
from varde_core.skill_relations import RelationError, closure, parse
from yaml.constructor import ConstructorError

KNOWN_FIELDS = {
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
    "requires",
    "recommends",
}
IMPLICIT_SKILL = "varde-manage"
BODY_LINE_BUDGET = 500


class _UniqueSafeLoader(yaml.SafeLoader):
    """SafeLoader that rejects repeated keys, including duplicate merge keys."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict:
        seen = set()
        saw_merge = False
        for key_node, _ in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                if saw_merge:
                    raise ConstructorError(
                        "while constructing a mapping",
                        node.start_mark,
                        "duplicate key",
                        key_node.start_mark,
                    )
                saw_merge = True
                continue
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in seen
                seen.add(key)
            except TypeError:
                continue
            if duplicate:
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "duplicate key",
                    key_node.start_mark,
                )
        return super().construct_mapping(node, deep=deep)


_UniqueSafeLoader.yaml_implicit_resolvers = copy.deepcopy(
    yaml.SafeLoader.yaml_implicit_resolvers
)
for _initial, _resolvers in list(_UniqueSafeLoader.yaml_implicit_resolvers.items()):
    _UniqueSafeLoader.yaml_implicit_resolvers[_initial] = [
        (_tag, _pattern)
        for _tag, _pattern in _resolvers
        if _tag
        not in {
            "tag:yaml.org,2002:bool",
            "tag:yaml.org,2002:int",
            "tag:yaml.org,2002:float",
            "tag:yaml.org,2002:timestamp",
        }
    ]
_UniqueSafeLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)
_UniqueSafeLoader.add_implicit_resolver(
    "tag:yaml.org,2002:int",
    re.compile(r"^(?:[-+]?(?:0|[1-9][0-9]*|0x[0-9a-fA-F]+|0o[0-7]+|0b[01]+))$"),
    list("-+0123456789"),
)
_UniqueSafeLoader.add_implicit_resolver(
    "tag:yaml.org,2002:float",
    re.compile(
        r"^(?:[-+]?(?:[0-9][0-9_]*\.[0-9_]*(?:[eE][-+]?[0-9]+)?|\.[0-9][0-9_]*(?:[eE][-+]?[0-9]+)?|[0-9][0-9_]*[eE][-+]?[0-9]+|\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN)))$"
    ),
    list("-+0123456789."),
)


@dataclass
class SkillResult:
    path: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_json(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "errors": self.errors,
            "warnings": self.warnings,
            "ok": self.ok,
        }


class InputError(ValueError):
    """A missing input path, absent SKILL.md, or unreadable file."""


def render_text(results: list[SkillResult]) -> str:
    out = []
    for result in results:
        out.append(f"{'OK  ' if result.ok else 'FAIL'}  {result.path}\n")
        out.extend(f"      error:   {message}\n" for message in result.errors)
        out.extend(f"      warning: {message}\n" for message in result.warnings)
    return "".join(out)


def check(paths: Sequence[str | os.PathLike[str]]) -> list[SkillResult]:
    files: list[tuple[Path, Path]] = []
    for raw in paths:
        path = _expand_tilde(Path(raw))
        shown = _normalize(path)
        if not path.exists():
            raise InputError(f"varde learn check: path not found: {shown}")
        found = _find_skill_files(path, shown)
        if not found:
            display = str(shown) or "."
            raise InputError(
                f"varde learn check: no SKILL.md found at or under {display}"
            )
        files.extend(found)

    known_by_root: dict[Path, dict[str, list[str]]] = {}
    results = []
    for real, shown in files:
        root = real.parent.parent
        if root == Path("."):
            known = None
        else:
            if root not in known_by_root:
                known_by_root[root] = _load_requirements(root)
            known = known_by_root[root]
        results.append(_validate_skill(real, shown, known))
    return results


def _expand_tilde(path: Path) -> Path:
    if path == Path("~") or str(path).startswith("~/"):
        return Path(os.environ.get("HOME", "")) / path.relative_to("~")
    return path


def _normalize(path: Path) -> Path:
    return Path(*[part for part in path.parts if part != "."])


def _find_skill_files(path: Path, shown: Path) -> list[tuple[Path, Path]]:
    if path.is_file() and path.name == "SKILL.md":
        return [(path, shown)]
    if not path.is_dir():
        return []
    direct = path / "SKILL.md"
    if direct.is_file():
        return [(direct, shown / "SKILL.md")]
    return [
        (child / "SKILL.md", shown / child.name / "SKILL.md")
        for child in sorted(path.iterdir())
        if (child / "SKILL.md").is_file()
    ]


def _split_frontmatter(text: str) -> tuple[str, int] | None:
    if not text.startswith("---\n"):
        return None
    rest = text[4:]
    close = rest.find("\n---")
    if close < 0:
        return None
    end = 4 + close + 4
    if text[end:].startswith("\n"):
        end += 1
    raw = rest[:close]
    return raw, end


def _parse_mapping(raw: str) -> tuple[dict, bool]:
    tag = _find_secondary_tag(raw)
    if tag:
        raise ValueError(f"frontmatter is not valid YAML: unsupported tag `{tag}`")
    try:
        node = yaml.compose(raw, Loader=_UniqueSafeLoader)
        explicit_description = isinstance(node, yaml.MappingNode) and any(
            isinstance(key, yaml.ScalarNode) and key.value == "description"
            for key, _ in node.value
        )
        value = yaml.load(raw, Loader=_UniqueSafeLoader)  # noqa: S506 - Loader subclasses SafeLoader and restricts construction.
    except yaml.YAMLError as exc:
        detail = (
            "duplicate key" if "duplicate key" in str(exc) else str(exc).splitlines()[0]
        )
        raise ValueError(f"frontmatter is not valid YAML: {detail}") from exc
    if not isinstance(value, dict):
        raise ValueError("frontmatter must be a YAML mapping (key: value pairs)")
    return value, explicit_description


def _find_secondary_tag(raw: str) -> str | None:
    """Find a tag token while skipping quoted text, comments and block bodies."""
    in_block = None
    flow_depth = 0
    for line in raw.splitlines():
        indent = len(line) - len(line.lstrip(" "))
        if in_block is not None:
            if not line.strip() or indent > in_block:
                continue
            in_block = None
        at = 0
        value_start = True
        quote = None
        while at < len(line):
            char = line[at]
            if quote:
                if char == "\\" and quote == '"':
                    at += 2
                    continue
                if char == quote:
                    if quote == "'" and line[at : at + 2] == "''":
                        at += 2
                        continue
                    quote = None
                at += 1
                continue
            if char.isspace():
                at += 1
                continue
            was_start = value_start
            value_start = False
            if char == "#" and (at == 0 or line[at - 1].isspace()):
                break
            if char in "-?:" and (at + 1 == len(line) or line[at + 1].isspace()):
                value_start = True
            elif char in "[{" and (was_start or flow_depth):
                flow_depth += 1
                value_start = True
            elif char in "]}" and flow_depth:
                flow_depth -= 1
            elif char == "," and flow_depth:
                value_start = True
            elif char == "&" and was_start:
                while at < len(line) and not line[at].isspace():
                    at += 1
                value_start = True
                continue
            elif (
                char in "|>"
                and was_start
                and re.match(r"^[0-9+-]*(?:\s*(?:#.*)?)$", line[at + 1 :])
            ):
                in_block = indent
                break
            elif char in "\"'" and was_start:
                quote = char
            elif char == "!" and was_start and line[at : at + 2] == "!!":
                return line[at:].split()[0].rstrip(",]}")
            at += 1
    return None


def _validate_skill(
    real: Path, shown: Path, known: dict[str, list[str]] | None
) -> SkillResult:
    try:
        text = (
            real.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
        )
    except OSError as exc:
        raise InputError(f"varde learn check: {shown}: {exc}") from exc
    result = SkillResult(str(shown))
    split = _split_frontmatter(text)
    if split is None:
        result.errors.append(
            "no `---`-delimited YAML frontmatter block found at the top of the file"
        )
        return result
    raw, body_start = split
    try:
        fields, explicit_description = _parse_mapping(raw)
    except ValueError as exc:
        result.errors.append(str(exc))
        return result
    _check_fields(fields, raw, shown.parent.name, explicit_description, result)
    _check_relations(raw, shown.parent.name, known, result.errors)
    body_lines = text[body_start:].count("\n") + 1
    if body_lines > BODY_LINE_BUDGET:
        result.warnings.append(
            (  # noqa: UP034 - Explicit grouping is required for split message text.
                f"SKILL.md body is ~{body_lines} lines, over the "
                f"{BODY_LINE_BUDGET}-line soft budget — consider moving detail "
                "into references/, assets/, or scripts/"
            )
        )
    return result


def _type_name(value: Any) -> str:
    if value is None:
        return "NoneType"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return "tagged"


def _check_fields(
    fields: dict,
    raw: str,
    directory: str,
    explicit_description: bool,
    result: SkillResult,
) -> None:
    name = fields.get("name")
    if not name:
        result.errors.append("missing required field `name`")
    elif not isinstance(name, str):
        result.errors.append(f"`name` must be a string, got {_type_name(name)}")
    else:
        length = len(name)
        if length > 64:
            result.errors.append(f"`name` is {length} chars, max is 64")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
            result.errors.append(
                (  # noqa: UP034 - Explicit grouping is required for split message text.
                    f"`name` {_py_repr(name)} must be lowercase alphanumeric + "
                    "hyphens only, no leading/trailing hyphen, no consecutive hyphens"
                )
            )
        if name != directory:
            result.errors.append(
                (  # noqa: UP034 - Explicit grouping is required for split message text.
                    f"`name` {_py_repr(name)} must match parent directory name "
                    f"{_py_repr(directory)}"
                )
            )

    description = fields.get("description")
    if not description:
        result.errors.append("missing required field `description`")
    elif not isinstance(description, str):
        result.errors.append(
            f"`description` must be a string, got {_type_name(description)}"
        )
    elif not description.strip():
        result.errors.append("missing required field `description`")
    elif len(description) > 1024:
        result.errors.append(f"`description` is {len(description)} chars, max is 1024")
    if explicit_description and not _description_is_one_quoted_line(raw):
        result.errors.append("`description` must be one double-quoted physical line")

    compatibility = fields.get("compatibility")
    if compatibility is not None and not isinstance(compatibility, str):
        result.errors.append(
            f"`compatibility` must be a string, got {_type_name(compatibility)}"
        )
    elif isinstance(compatibility, str) and len(compatibility) > 500:
        result.errors.append(
            f"`compatibility` is {len(compatibility)} chars, max is 500"
        )
    metadata = fields.get("metadata")
    if metadata is not None and (
        not isinstance(metadata, dict)
        or any(
            not isinstance(k, str) or not isinstance(v, str)
            for k, v in metadata.items()
        )
    ):
        result.errors.append("`metadata` must be a map of string keys to string values")
    tools = fields.get("allowed-tools")
    if tools is not None and not isinstance(tools, str):
        result.errors.append(
            f"`allowed-tools` must be a string, got {_type_name(tools)}"
        )

    unknown = sorted(
        {
            str(key)
            for key in fields
            if not isinstance(key, str) or key not in KNOWN_FIELDS
        }
    )
    result.warnings.extend(
        f"unrecognized frontmatter field `{key}` (client-specific fields are fine)"
        for key in unknown
    )


def _description_is_one_quoted_line(raw: str) -> bool:
    line = next(
        (line for line in raw.split("\n") if line.startswith("description:")), None
    )
    if line is None:
        return False
    value = line[len("description:") :].lstrip()
    if not value.startswith('"'):
        return False
    escaped = False
    for char in value[1:]:
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            return True
    return False


def _py_repr(value: str) -> str:
    quote = '"' if "'" in value and '"' not in value else "'"
    escaped = (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    escaped = escaped.replace(quote, "\\" + quote)
    escaped = "".join(
        f"\\x{ord(c):02x}" if ord(c) < 32 and c not in "\n\r\t" else c for c in escaped
    )
    return f"{quote}{escaped}{quote}"


def _check_relations(
    raw: str, directory: str, known: dict[str, list[str]] | None, errors: list[str]
) -> None:
    try:
        relations = parse(raw)
    except RelationError as exc:
        errors.append(str(exc))
        return
    errors.extend(
        f"must not list `{IMPLICIT_SKILL}`; it is installed implicitly"
        for name in (*relations.requires, *relations.recommends)
        if name == IMPLICIT_SKILL
    )
    if known is None:
        return
    for name in relations.recommends:
        if name == directory:
            errors.append("`recommends` must not name the skill itself")
        elif name not in known:
            errors.append(f"`recommends` names unknown skill `{name}`")
    if not relations.requires:
        return
    try:
        closure([directory], known.get)
    except RelationError as exc:
        if exc.kind == "unknown":
            errors.append(f"`requires` names unknown skill `{exc.detail}`")
        else:
            errors.append(str(exc))


def _load_requirements(root: Path) -> dict[str, list[str]]:
    # A moved module's ``skills`` directory is not the repository-wide skill
    # set. Use layout discovery when this path belongs to a checkout, while
    # retaining sibling-only validation for arbitrary user supplied trees.
    for candidate in (root, *root.parents):
        if (candidate / ".git").exists() or (candidate / "AGENTS.md").is_file():
            try:
                discovered = skill_dirs(candidate)
            except OSError, ValueError:
                discovered = {}
            skill_roots = {
                directory.parent.resolve() for directory in discovered.values()
            }
            if discovered and root.resolve() in skill_roots:
                return {
                    name: _load_skill_requires(directory / "SKILL.md")
                    for name, directory in discovered.items()
                }
    return _load_sibling_requirements(root)


def _load_sibling_requirements(root: Path) -> dict[str, list[str]]:
    requires = {}
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return requires
    for entry in entries:
        skill_file = entry / "SKILL.md"
        if not skill_file.is_file():
            continue
        requires[entry.name] = _load_skill_requires(skill_file)
    return requires


def _load_skill_requires(skill_file: Path) -> list[str]:
    try:
        text = (
            skill_file.read_text(encoding="utf-8")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
        )
        split = _split_frontmatter(text)
        return parse(split[0]).requires if split else []
    except OSError, ValueError:
        return []
