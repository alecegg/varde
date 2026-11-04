"""YAML formatting helpers shared across Varde packages."""

from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from typing import Any


def _construct_float(loader: Any, node: Any) -> float | str:
    scalar = loader.construct_scalar(node)
    value = loader.construct_yaml_float(node)
    overflowed = not math.isfinite(value) and not scalar.lstrip("+-").startswith(".")
    return scalar if overflowed else value


class YamlSyntaxError(ValueError):
    """A YAML parser error rendered without source excerpts or line breaks."""


@lru_cache(maxsize=2)
def _core_loader(use_c_loader: bool) -> type:
    import yaml

    base: Any = (
        yaml.CSafeLoader if use_c_loader and yaml.__with_libyaml__ else yaml.SafeLoader
    )

    class CoreLoader(base):
        pass

    CoreLoader.yaml_implicit_resolvers = {
        key: [
            (tag, pattern)
            for tag, pattern in resolvers
            if tag
            not in {
                "tag:yaml.org,2002:bool",
                "tag:yaml.org,2002:timestamp",
                "tag:yaml.org,2002:value",
            }
        ]
        for key, resolvers in base.yaml_implicit_resolvers.items()
    }
    CoreLoader.add_implicit_resolver(
        "tag:yaml.org,2002:bool",
        re.compile(r"^(?:true|false)$", re.IGNORECASE),
        list("tTfF"),
    )
    CoreLoader.add_implicit_resolver(
        "tag:yaml.org,2002:float",
        re.compile(
            r"^[-+]?(?:(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?|[0-9]+\.[0-9]*)$"
        ),
        list("-+0123456789."),
    )
    CoreLoader.add_constructor("tag:yaml.org,2002:float", _construct_float)
    return CoreLoader


def load_yaml(text: str) -> Any:
    """Load YAML using the YAML 1.2 core scalar rules used by serde_yaml."""
    import yaml

    use_c_loader = yaml.__with_libyaml__
    CoreLoader = _core_loader(use_c_loader)
    try:
        return yaml.load(text, Loader=CoreLoader)  # noqa: S506 - CoreLoader subclasses SafeLoader and only changes scalar resolvers.
    except yaml.YAMLError as exc:
        error = exc
        if use_c_loader:
            try:
                yaml.load(text, Loader=_core_loader(False))  # noqa: S506 - SafeLoader-based fallback only formats parser errors.
            except yaml.YAMLError as pure_exc:
                error = pure_exc
        problem = getattr(error, "problem", None)
        mark = getattr(error, "problem_mark", None)
        context = getattr(error, "context", None)
        context_mark = getattr(error, "context_mark", None)
        if problem is not None and mark is not None:
            if ", but got '<stream end>'" in problem:
                problem = "did not find " + problem.partition(", but got")[0]
            line, column = mark.line + 1, mark.column + 1
            if mark.index == len(text):
                line, column = line + 1, 1
            message = f"{problem} at line {line} column {column}"
            if context is not None and context_mark is not None:
                message += (
                    f", {context} at line {context_mark.line + 1} "
                    f"column {context_mark.column + 1}"
                )
        else:
            message = str(error).splitlines()[0]
        raise YamlSyntaxError(message) from error


def dump_yaml(value: Any) -> str:
    """Serialize common YAML values with serde_yaml-compatible scalar layout."""
    if value == {}:
        return "---\n{}\n"
    lines = ["---"]
    _emit(value, lines, 0)
    return "\n".join(lines) + "\n"


def _emit(value: Any, lines: list[str], indent: int) -> None:
    prefix = " " * indent
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = _scalar(str(key))
            if _is_multiline(item):
                lines.extend(_block(key_text + ": ", item, indent))
            elif isinstance(item, (dict, list)):
                if not item:
                    lines.append(
                        f"{prefix}{key_text}: "
                        + ("{}" if isinstance(item, dict) else "[]")
                    )
                else:
                    lines.append(f"{prefix}{key_text}:")
                    _emit(item, lines, indent + 2)
            else:
                lines.append(f"{prefix}{key_text}: {_value(item)}")
    elif isinstance(value, list):
        for item in value:
            if _is_multiline(item):
                lines.extend(_block("- ", item, indent))
            elif isinstance(item, (dict, list)):
                if not item:
                    lines.append(
                        prefix + ("- {}" if isinstance(item, dict) else "- []")
                    )
                else:
                    lines.append(prefix + "-")
                    _emit(item, lines, indent + 2)
            else:
                lines.append(prefix + "- " + _value(item))
    else:
        lines.append(prefix + _value(value))


def _is_multiline(value: Any) -> bool:
    return isinstance(value, str) and "\n" in value


def _block(prefix: str, value: str, indent: int) -> list[str]:
    ending = len(value) - len(value.rstrip("\n"))
    indicator = "|" if ending == 1 else "|-" if ending == 0 else "|+"
    content = value[:-ending] if ending else value
    rendered = [" " * indent + prefix + indicator]
    rendered.extend(" " * (indent + 2) + line for line in content.split("\n"))
    if ending > 1:
        rendered.extend(" " * (indent + 2) for _ in range(ending - 1))
    return rendered


def _value(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return _scalar(value)
    if isinstance(value, (int, float)):
        return str(value)
    return _scalar(str(value))


_AMBIGUOUS = re.compile(
    r"^(?:~|null|true|false|0x[0-9a-f_]+|0o[0-7_]+|[-+]?(?:[0-9]+(?:_[0-9]+)*(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?|"
    r"[-+]?\.(?:inf|nan))$",
    re.IGNORECASE,
)


def _scalar(value: str) -> str:
    if not value:
        return "''"
    if "\t" in value:
        return json.dumps(value, ensure_ascii=False)
    if value != value.strip() or _AMBIGUOUS.fullmatch(value):
        return _quoted(value)
    if value[0] in ",[]{}#&*!|>'\"%@`" or (
        value[0] in "-?:" and (len(value) == 1 or value[1].isspace())
    ):
        if value == "=":
            return value
        return _quoted(value)
    if any(token in value for token in (": ", " #", "\t", "\r")):
        return _quoted(value)
    return value


def _quoted(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
