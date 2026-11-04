from varde_code.extract import extract_file


def test_tsx_keeps_intrinsic_jsx_tag_names_as_references():
    output = extract_file(
        "view.tsx", "function View() { return <span>ok</span>; }", "tsx"
    )
    assert any(symbol.name == "span" for symbol in output.symbols)


def test_dart_excludes_call_names_from_references():
    output = extract_file(
        "sample.dart", "void run() { queue.add(1); windowMock.expect(1); }", "dart"
    )
    names = {symbol.name for symbol in output.symbols}
    assert "queue" in names
    assert "add" not in names
