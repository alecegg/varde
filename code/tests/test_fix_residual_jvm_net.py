from varde_code.extract.entity import extract_file
from varde_code.model import SymbolKind


def test_java_symbols_match_jsts_fallback_classification():
    source = (
        "class Example {\n"
        "  Widget field;\n"
        "  Widget run(Widget argument) {\n"
        "    return Use(argument);\n"
        "  }\n"
        "}\n"
    )

    output = extract_file("fixture.java", source, "java")
    references = [
        symbol.name for symbol in output.symbols if symbol.kind == SymbolKind.REFERENCE
    ]

    assert references == ["run", "argument", "Use", "argument"]


def test_csharp_symbols_match_jsts_fallback_classification():
    source = (
        "class Example {\n"
        "  Widget field;\n"
        "  Widget Run(Widget argument) {\n"
        "    return Use(argument);\n"
        "  }\n"
        "}\n"
    )

    output = extract_file("fixture.cs", source, "csharp")
    references = [
        symbol.name for symbol in output.symbols if symbol.kind == SymbolKind.REFERENCE
    ]

    assert references == [
        "Widget",
        "Widget",
        "Run",
        "Widget",
        "argument",
        "Use",
        "argument",
    ]
