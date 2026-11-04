from varde_code.extract import extract_file
from varde_code.extract.entity import node_is_test
from varde_code.extract.langs import tables_for
from varde_code.extract.langs.base import (
    LanguageTables,
    VisitRule,
    strip_generic_args,
    unquote,
)
from varde_code.extract.minhash import body_minhash
from varde_code.extract.preproc import scan
from varde_code.extract.recursion import Callable, CalleeReference, resolve
from varde_code.model import EntityKind, Span
from varde_code.parse import TreeSitterParser


def test_language_table_default_and_lookup():
    tables = tables_for("python")
    assert isinstance(tables, LanguageTables)
    assert VisitRule(EntityKind.FUNCTION).kind is EntityKind.FUNCTION


def test_minhash_is_stable_and_skips_short_bodies():
    assert body_minhash("a b c d") is None
    signature = body_minhash("alpha beta gamma delta epsilon zeta")
    assert signature is not None
    assert len(signature) == 4
    assert signature == body_minhash("ALPHA BETA GAMMA DELTA EPSILON ZETA")
    assert signature != body_minhash("one two three four five six")


def test_preprocessor_regions():
    source = "#if FOO\nint a;\n#else\nint b;\n#endif\n"
    entities = scan(source)
    assert [entity.name for entity in entities] == ["preproc_if", "preproc_branch"]
    assert entities[0].span.start_line == 1


def test_recursive_cycle_resolution():
    span = Span(0, 1, 1, 0, 1, 1)
    callables = [
        Callable(None, "a", 0, 0, 1, span, span, unqualified_callable=True),
        Callable(None, "b", 0, 0, 1, span, span, unqualified_callable=True),
    ]
    markers = resolve(
        callables, [CalleeReference(0, "b", 0), CalleeReference(1, "a", 0)]
    )
    assert [marker.name for marker in markers] == ["recursive_call", "recursive_call"]


def test_node_is_test_uses_language_hook():
    tables = LanguageTables(test_node=lambda _node: True)
    node = TreeSitterParser().parse("python", "def test_example(): pass").root
    assert node_is_test(node, tables)


def test_shared_name_helpers():
    assert strip_generic_args("Comparable[Thing]") == "Comparable[Thing]"
    assert strip_generic_args("Comparable<Thing>") == "Comparable"
    assert unquote('  "value"  ') == "value"
    assert unquote("`value`", allow_backtick=True) == "value"
    assert unquote("`value`") == "`value`"


def test_symbol_walk_uses_parent_child_positions_without_child_index():
    output = extract_file("sample.py", "def run(value):\n    return value\n", "python")
    assert {symbol.name for symbol in output.symbols} >= {"value"}


def test_extract_output_reports_parse_errors():
    output = extract_file("broken.py", "def broken(:\n", "python")
    assert output.has_parse_error is True
