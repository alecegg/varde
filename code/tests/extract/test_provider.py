from pathlib import Path

from varde_code.complexity import FunctionComplexity
from varde_code.extract import provider
from varde_code.extract.entity import EntityExtractOutput
from varde_code.extract.provider import (
    CodeExtractionProvider,
    ExtractionOutput,
    extract_file,
)
from varde_code.model import Entity, EntityKind, ExtractOutput, Span


def test_provider_returns_entities_and_function_complexity(monkeypatch):
    entity = Entity(EntityKind.FUNCTION, "choose", 0, Span(0, 65, 1, 0, 4, 0))
    flow = Entity(
        EntityKind.CONTROL_FLOW,
        "if",
        0,
        Span(20, 22, 2, 4, 2, 6),
        enclosing_function="choose",
    )
    monkeypatch.setattr(
        provider,
        "extract_entities",
        lambda *_: EntityExtractOutput(entities=[entity, flow]),
    )
    output = CodeExtractionProvider().extract(
        Path("sample.py"),
        "def choose(value):\n    if value:\n        return 1\n    return 0\n",
        "python",
    )

    assert isinstance(output, ExtractOutput)
    assert isinstance(output, ExtractionOutput)
    assert any(
        entity.kind == EntityKind.FUNCTION and entity.name == "choose"
        for entity in output.entities
    )
    assert len(output.complexities) == 1
    assert isinstance(output.complexities[0], FunctionComplexity)
    assert output.complexities[0].name == "choose"
    assert output.complexities[0].cyclomatic == 2


def test_extract_file_is_provider_convenience(monkeypatch):
    entity = Entity(EntityKind.FUNCTION, "plain", 0, Span(0, 10, 1, 0, 2, 0))
    monkeypatch.setattr(
        provider, "extract_entities", lambda *_: EntityExtractOutput(entities=[entity])
    )
    output = extract_file(Path("sample.py"), "def plain():\n    return 1\n", "py")

    assert [metric.name for metric in output.complexities] == ["plain"]


def test_complexities_are_computed_only_when_read(monkeypatch):
    entity = Entity(EntityKind.FUNCTION, "plain", 0, Span(0, 10, 1, 0, 2, 0))
    monkeypatch.setattr(
        provider, "extract_entities", lambda *_: EntityExtractOutput(entities=[entity])
    )
    calls = []

    def complexities(entities):
        calls.append(entities)
        return []

    monkeypatch.setattr(provider, "function_complexities", complexities)
    output = CodeExtractionProvider().extract(
        Path("sample.py"), "def plain(): pass", "python"
    )

    assert calls == []
    assert output.complexities == []
    assert output.complexities == []
    assert calls == [output.entities]


def test_extract_does_not_compute_complexities(monkeypatch):
    monkeypatch.setattr(provider, "extract_entities", lambda *_: EntityExtractOutput())

    def fail_if_called(_):
        raise AssertionError("complexities should be lazy")

    monkeypatch.setattr(provider, "function_complexities", fail_if_called)
    output = CodeExtractionProvider().extract(Path("sample.py"), "", "python")

    assert output.entities == []


def test_complexity_cache_does_not_affect_output_equality() -> None:
    from dataclasses import fields

    first = ExtractionOutput()
    second = ExtractionOutput()
    _ = first.complexities
    assert first == second
    cache_field = next(
        item for item in fields(ExtractionOutput) if item.name == "_complexities"
    )
    assert not cache_field.init and not cache_field.repr and not cache_field.compare
