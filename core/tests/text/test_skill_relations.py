from varde_core.skill_relations import (
    IMPLICIT_SKILL,
    RelationError,
    Relations,
    closure,
    parse,
)


def test_parse_flow_lists_and_defaults() -> None:
    assert parse(
        "name: varde-scan\nrequires: [varde-code]\nrecommends: [varde-toz]\n"
    ) == Relations(requires=["varde-code"], recommends=["varde-toz"])
    assert parse("name: varde-code\n") == Relations()
    assert parse("requires: []\nrecommends:\n") == Relations()
    assert parse("requires: varde-code\n").requires == ["varde-code"]


def test_parse_ignores_indented_and_unrelated_keys() -> None:
    assert (
        parse("metadata:\n  requires: [varde-code]\nother: requires\n") == Relations()
    )


def test_parse_rejects_malformed_value() -> None:
    try:
        parse("requires: [varde-code, \n")
    except RelationError as error:
        assert error.kind == "malformed"
        assert error.key == "requires"
    else:
        raise AssertionError("expected malformed relation error")


def test_closure_is_sorted_transitive_and_deduplicated() -> None:
    edges = {
        "varde-a": ["varde-c", "varde-b"],
        "varde-b": ["varde-d"],
        "varde-c": ["varde-d"],
        "varde-d": [],
    }
    assert closure(["varde-c", "varde-a"], edges.get) == [
        "varde-a",
        "varde-b",
        "varde-c",
        "varde-d",
    ]
    assert closure([], {}.get) == []


def test_closure_reports_unknown_names() -> None:
    for selected, expected in (
        (["varde-a"], "varde-missing"),
        (["varde-absent"], "varde-absent"),
    ):
        try:
            closure(selected, {"varde-a": ["varde-missing"]}.get)
        except RelationError as error:
            assert error.kind == "unknown"
            assert error.detail == expected
        else:
            raise AssertionError("expected unknown skill error")


def test_closure_reports_cycles_and_self_reference() -> None:
    try:
        closure(["varde-a"], {"varde-a": ["varde-b"], "varde-b": ["varde-a"]}.get)
    except RelationError as error:
        assert error.kind == "cycle"
        assert error.detail == ["varde-a", "varde-b", "varde-a"]
    else:
        raise AssertionError("expected cycle error")
    try:
        closure(["varde-a"], {"varde-a": ["varde-a"]}.get)
    except RelationError as error:
        assert error.kind == "cycle"
    else:
        raise AssertionError("expected self-cycle error")


def test_closure_does_not_add_implicit_skill() -> None:
    assert closure(["varde-a"], {"varde-a": []}.get) == ["varde-a"]
    assert IMPLICIT_SKILL == "varde-manage"
