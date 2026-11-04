"""Import the post-freeze core and learn APIs needed by downstream plans."""

from importlib import import_module
from inspect import signature


def test_post_freeze_names_are_importable() -> None:
    names = {
        "varde_core.redact": (
            "Kind",
            "Notice",
            "RedactConfig",
            "Redacted",
            "Redactor",
            "SecretValue",
            "Span",
            "values",
        ),
        "varde_core.text_audit": (
            "Finding",
            "Rule",
            "Severity",
            "audit",
            "expand_skill_dir",
        ),
        "varde_core.skill_relations": (
            "IMPLICIT_SKILL",
            "RelationError",
            "Relations",
            "closure",
            "parse",
        ),
        "varde_learn.loop.errors": (
            "LearnError",
            "NotImplemented",
            "Usage",
            "StoreConfig",
            "StoreInvalid",
            "StoreItemNotFound",
            "StoreInsideGit",
            "StoreSchemaTooNew",
            "StoreSchemaVersion",
            "StoreGitCheck",
            "StoreIo",
            "StoreDatabase",
            "Diagnose",
        ),
        "varde_learn.loop.redact": ("Redacted", "apply"),
        "varde_learn.loop.store_dir": ("resolve_store_dir",),
    }
    for module_name, attributes in names.items():
        module = import_module(module_name)
        for attribute in attributes:
            assert hasattr(module, attribute), f"{module_name}.{attribute} is absent"


def test_post_freeze_documented_parameter_names() -> None:
    redact_values = import_module("varde_core.redact.values")
    assert tuple(signature(redact_values.collect).parameters) == ("root",)
    assert tuple(signature(redact_values.from_dotenv).parameters) == ("path",)
    assert tuple(signature(redact_values.from_environment).parameters) == ()

    relations = import_module("varde_core.skill_relations")
    assert tuple(signature(relations.parse).parameters) == ("frontmatter",)


def test_enum_conversion_helpers_return_documented_values() -> None:
    model = import_module("varde_code.model")
    examples = (
        (model.EntityKind.CALL, 6, "call"),
        (model.SymbolKind.REFERENCE, 1, "reference"),
        (model.EdgeKind.IMPORT, 1, "import"),
    )
    for member, integer, name in examples:
        assert member.as_i64() == integer
        assert member.as_str() == name
