from pathlib import Path

import pytest
import varde_code.parse as parse_module
from varde_code.model import (
    Community,
    EdgeKind,
    EntityKind,
    RoleTag,
    Span,
    SymbolKind,
    span_of,
)
from varde_code.parse import (
    TreeSitterParser,
    language_for_extension,
    language_for_path,
    language_from_name,
    parse_source,
    parse_source_for_path,
)
from varde_code.toz_bridge import add_guide, capture_items, capture_text


def test_model_discriminants_and_names_match_rust_storage_contract():
    assert EntityKind.CALLABLE_BOUNDARY.as_i64() == 19
    assert EntityKind.from_i64(19) is EntityKind.CALLABLE_BOUNDARY
    assert EntityKind.from_i64(20) is None
    symbol = SymbolKind.from_i64(0)
    edge = EdgeKind.from_i64(3)
    assert symbol is not None and symbol.as_str() == "binding"
    assert edge is not None and edge.as_str() == "implements"
    assert RoleTag.PROCESS_MAIN.value == "process_main"
    assert Community(3, ["src/a.py"]).members == ["src/a.py"]
    assert Span(0, 1, 1, 0, 1, 1).end_byte == 1


def test_tree_sitter_parser_reports_errors_and_rust_compatible_spans():
    parsed = parse_source("python", "def hello():\n    return 1\n")
    assert not parsed.has_error()
    fn = parsed.root.named_children[0]
    span = span_of(fn)
    assert (span.start_byte, span.end_byte, span.start_line, span.end_line) == (
        0,
        25,
        1,
        2,
    )
    assert parse_source("python", "def broken(:\n").has_error()


def test_tree_sitter_parser_reports_unwritable_cache(monkeypatch, tmp_path):
    cache_file = tmp_path / "not-a-directory"
    cache_file.write_text("x", encoding="utf-8")
    monkeypatch.setenv("VARDE_TREE_SITTER_CACHE_DIR", str(cache_file))
    monkeypatch.setattr(parse_module, "configure", lambda config: None)
    with pytest.raises(RuntimeError, match="cache is not writable"):
        TreeSitterParser().parse("python", "x = 1")


def test_supported_extensions_aliases_and_header_retry():
    assert language_for_extension(".MTS") == "typescript"
    assert language_for_path(Path("src/a.h")) == "c"
    assert language_from_name("golang") == "go"
    parsed = parse_source_for_path(
        "c",
        "include/repository.h",
        "template <typename T> class Repository { public: void find() {} };",
    )
    assert parsed.lang == "cpp"
    assert not parsed.has_error()
    conditional = parse_source_for_path(
        "csharp",
        "conditional.cs",
        (
            "class C { private static bool Verify =>\n#if NET\n true;\n"
            "#else\n false;\n#endif\n}\n"
        ),
    )
    assert not conditional.has_error()
    assert conditional.masked_preprocessor
    assert TreeSitterParser().parse("python", "\0x").source == b" x"


class Capture:
    def __init__(self, response: str):
        self.response = response
        self.calls = []

    def capture(self, input, source, label):
        self.calls.append((input, source, label))
        return self.response


def test_toz_bridge_captures_and_adds_read_guide(monkeypatch):
    monkeypatch.delenv("VARDE_CODE_TOZ", raising=False)
    capture = Capture('{"handle":"abc","toc":[]}')
    result = capture_items(capture, "query", [{"x": 1}])
    assert result == {"handle": "abc", "items": 1, "format": "jsonl", "toc": ""}
    assert capture.calls[0][1:] == ("varde map results query", "query")
    assert capture_text(capture, "src", "label", "body") == capture.response
    guide = {}
    assert result is not None
    add_guide(guide, result, 2, 4)
    assert guide["toz_read"] == "varde run query --handle abc --lines 3:4"
    assert guide["toz_search"] == 'varde run query --handle abc "<term>"'
