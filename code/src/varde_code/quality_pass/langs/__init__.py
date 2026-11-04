"""Language-specific quality fact extensions discovered by package directory.

Optional module hooks:

* ``exported_names(root, source_bytes)`` returns exported names or ``(owner, name)``
  identities.
* ``file_private(record, root, source_bytes, references)`` returns a visibility result.
* ``parameter_count(function_node)`` overrides grammar-specific counting.
* ``verified_role(record, function_node, body, source_bytes)`` returns only roles
  established from syntax and resolved imports or base methods.
* ``call_site(call_node, source_bytes)`` supplies resolved name, receiver and arity.
* ``convention_issues(record)`` returns language-specific naming issues.
* ``filter_name_issues(record, issues)`` drops conventional language-specific issues.
* ``unmeasured_regions(root, source_bytes)`` lists ``{kind, start_line, end_line}``
  spans whose code the parser cannot measure (macros, templates).
* ``overload_pairs(records, root, source_bytes)`` pairs const/non-const overload ids.

Hooks return ``None`` to use the neutral fallback. In particular, overrides and
framework roles require a verified same-name base method or resolved imported
decorator. Languages without a directory use the neutral implementation.
"""

from __future__ import annotations

from importlib import import_module
from importlib.resources import files
from types import ModuleType

from varde_code.parse import language_from_name

# JavaScript and TSX share the TypeScript grammar family and its hooks.
_LANGUAGE_ALIASES = {"javascript": "typescript", "tsx": "typescript"}


def language_module(language: str) -> ModuleType | None:
    """Load the plugin for ``language``, following shared-grammar aliases."""
    canonical = language_from_name(language)
    if canonical is None:
        return None
    canonical = _LANGUAGE_ALIASES.get(canonical, canonical)
    if not canonical.isidentifier() or canonical.startswith("_"):
        return None
    try:
        entries = files(__package__).iterdir()
    except FileNotFoundError:
        return None
    if not any(item.is_dir() and item.name == canonical for item in entries):
        return None
    module_name = f"{__package__}.{canonical}"
    try:
        return import_module(module_name)
    except ModuleNotFoundError as error:
        if error.name != module_name:
            raise
        return None
