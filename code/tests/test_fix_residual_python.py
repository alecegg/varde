from varde_code.extract.entity import extract_file
from varde_code.model import EntityKind, SymbolKind


def test_python_type_argument_is_not_a_reference():
    output = extract_file(
        "typed.py",
        "def use(values: list[str], error: tuple[str, str] | None):\n"
        "    return values\n",
        "python",
    )

    references = [
        symbol.name for symbol in output.symbols if symbol.kind == SymbolKind.REFERENCE
    ]

    assert "str" not in references
    assert "tuple" not in references
    assert "values" in references


def test_python_lambda_boundary_excludes_anonymous_lambda_token():
    source = "callback = lambda value: value\n"
    output = extract_file("lambda.py", source, "python")

    boundaries = [
        entity
        for entity in output.entities
        if entity.kind == EntityKind.CALLABLE_BOUNDARY
    ]

    assert len(boundaries) == 1
    boundary = boundaries[0].span
    assert source.encode()[boundary.start_byte : boundary.end_byte].decode() == (
        "lambda value: value"
    )


def test_python_negation_break_finds_nested_boolean_operator():
    output = extract_file(
        "negation.py",
        "def check(left, right):\n    if not (left and right):\n        return False\n",
        "python",
    )

    control_flow = [
        entity.name
        for entity in output.entities
        if entity.kind == EntityKind.CONTROL_FLOW
    ]

    assert "negation_break" in control_flow


def test_python_self_recursion_adds_control_flow_marker():
    output = extract_file(
        "recursive.py",
        "def recurse(value):\n    return recurse(value - 1)\n",
        "python",
    )

    recursive = [
        entity
        for entity in output.entities
        if entity.kind == EntityKind.CONTROL_FLOW and entity.name == "recursive_call"
    ]

    assert len(recursive) == 1


def test_python_compensating_usage_pattern_adds_control_flow_marker():
    output = extract_file(
        "compensating.py",
        "def handle(value):\n    def cleanup():\n        pass\n    return value\n",
        "python",
    )

    compensating = [
        entity
        for entity in output.entities
        if entity.kind == EntityKind.CONTROL_FLOW
        and entity.name == "compensating_usage"
    ]

    assert len(compensating) == 1
