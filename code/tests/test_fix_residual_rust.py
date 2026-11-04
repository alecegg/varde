from varde_code.extract.entity import extract_file
from varde_code.model import EntityKind


def test_haskell_conditional_flow_matches_rust_branch_entities():
    source = (
        "choose x = if x > 2 then 2 else if x > 1 then 1 else 0\n"
        "plain x = if x > 0 then 1 else 0\n"
    )

    output = extract_file("fixture.hs", source, "haskell")
    flow = [
        (entity.name, entity.span.start_byte, entity.span.end_byte)
        for entity in output.entities
        if entity.kind == EntityKind.CONTROL_FLOW
    ]

    plain_start = source.index("plain")
    assert flow == [
        ("legacy_nesting", source.index("if x > 2"), source.index("\nplain")),
        ("conditional", source.index("if x > 2"), source.index("2 else if") + 1),
        ("legacy_nesting", source.index("if x > 1"), source.index("\nplain")),
        ("elseif_statement", source.index("if x > 1"), source.index("1 else 0") + 1),
        ("else_branch", source.index("0\n"), source.index("0\n") + 1),
        (
            "conditional",
            source.index("if x > 0"),
            source.index("1 else 0", plain_start) + 1,
        ),
        (
            "else_branch",
            source.index("0\n", plain_start),
            source.index("0\n", plain_start) + 1,
        ),
    ]


def test_bash_case_ternary_and_logical_negation_match_rust_flow_entities():
    source = (
        "run() {\n"
        '  case "$1" in x) echo x ;; esac\n'
        "  (( result = $1 ? $2 : $3 ))\n"
        "  [[ $1 && ! ( $2 && $3 ) ]]\n"
        "}\n"
    )

    output = extract_file("fixture.sh", source, "bash")
    flow_names = [
        entity.name
        for entity in output.entities
        if entity.kind == EntityKind.CONTROL_FLOW
    ]

    assert flow_names.count("case_statement") == 1
    assert flow_names.count("cognitive_decision") == 2
    assert flow_names.count("negation_break") == 1


def test_kotlin_labeled_jumps_match_rust_flow_entities():
    source = (
        "fun jump(items: List<Int>) {\n"
        "  OUT@ for (item in items) { continue@OUT }\n"
        "  outer@ while (true) { break@outer }\n"
        "}\n"
    )

    output = extract_file("fixture.kt", source, "kotlin")
    flow_names = [
        entity.name
        for entity in output.entities
        if entity.kind == EntityKind.CONTROL_FLOW
    ]

    assert flow_names.count("continue_statement") == 1
    assert flow_names.count("break_statement") == 1
    assert flow_names.count("labeled_jump") == 2


def test_swift_negated_logical_sequence_matches_rust_flow_entity():
    source = (
        "func check(_ a: Bool, _ b: Bool, _ c: Bool) {\n"
        '  if a && !(b && c) { print("x") }\n'
        "}\n"
    )

    output = extract_file("fixture.swift", source, "swift")
    flow_names = [
        entity.name
        for entity in output.entities
        if entity.kind == EntityKind.CONTROL_FLOW
    ]

    assert flow_names.count("negation_break") == 1


def test_swift_labeled_jumps_match_rust_flow_entities():
    source = (
        "func jump(_ flag: Bool) {\n"
        "  outer: while flag { if flag { break outer } }\n"
        "  loop: for value in [1] { continue loop }\n"
        "}\n"
    )

    output = extract_file("fixture.swift", source, "swift")
    flow_names = [
        entity.name
        for entity in output.entities
        if entity.kind == EntityKind.CONTROL_FLOW
    ]

    assert flow_names.count("labeled_jump") == 2
    assert flow_names.count("break_statement") == 0
    assert flow_names.count("continue_statement") == 0
