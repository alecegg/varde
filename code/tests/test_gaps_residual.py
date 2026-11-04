from pathlib import Path

from varde_code.extract.provider import CodeExtractionProvider


def test_kotlin_calls_fixture_parser_deviation_is_reported():
    source = """\
class Receiver { fun name(value: Int) {} }
fun alpha(vararg values: Int) {}
fun beta(value: Int) {}
fun run() {
    alpha(1)
    alpha(2, 3)
    val receiver = Receiver()
    receiver.name(4)
    beta(5)
}
"""

    output = CodeExtractionProvider().extract(Path("calls.kt"), source, "kotlin")

    assert [diagnostic.message for diagnostic in output.diagnostics] == [
        "syntax error — partial extract kept"
    ]
