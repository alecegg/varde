from types import ModuleType

from varde_code.extract import adapter, entity
from varde_code.extract.langs import python as python_lang
from varde_code.parse import ParsedFile, TreeSitterParser


class StubBackend:
    def parse(self, language, source):
        tree = TreeSitterParser().parse(language, source).tree
        return ParsedFile(language, tree, source.upper().encode())


def test_uses_language_backend(monkeypatch):
    backend = StubBackend()
    module = ModuleType("varde_code.extract.langs.python")
    module.__dict__["BACKEND"] = "ast-grep"
    monkeypatch.setattr(adapter, "import_module", lambda _: module)

    parsed = adapter.ParserAdapter({"ast-grep": backend}).parse("py", "print('ok')")

    assert parsed.lang == "python"
    assert parsed.source == b"PRINT('OK')"


def test_uses_tree_sitter_default_when_language_module_is_not_yet_available(
    monkeypatch,
):

    def missing_module(_):
        error = ModuleNotFoundError("missing")
        error.name = "varde_code.extract.langs.python"
        raise error

    monkeypatch.setattr(adapter, "import_module", missing_module)
    parser = adapter.ParserAdapter()

    parsed = parser.parse("py", "print('ok')")

    assert parsed.lang == "python"
    assert parsed.source == b"print('ok')"


def test_extract_file_selects_language_backend(monkeypatch):
    class RecordingBackend:
        def __init__(self):
            from varde_code.parse import TreeSitterParser

            self.parser = TreeSitterParser()

        def parse(self, language, source):
            return self.parser.parse(language, "def selected():\n    return 1\n")

    backend = RecordingBackend()
    monkeypatch.setattr(python_lang, "BACKEND", backend)

    output = entity.extract_file("sample.py", "x = 1\n", "py")

    assert "selected" in {symbol.name for symbol in output.symbols}
