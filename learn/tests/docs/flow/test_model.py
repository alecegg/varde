import json

from varde_learn.docs.flow import (
    EdgeKind,
    External,
    ExternalType,
    OrderedMap,
    Runs,
)


def test_flow_json_uses_serialized_kind_spellings(tmp_path, capsys) -> None:
    from varde_learn.docs.cli import run

    skill = tmp_path / "demo"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "| Request | Read |\n|---|---|\n| Build it | `references/x.md` |\n"
    )
    (skill / "references/x.md").write_text(
        "Read `references/a.md`.\n\nThen continue with `references/b.md`.\n\n"
        "The tool `references/c.md` exists.\n\nThe reviewer reads `references/a.md`.\n"
    )
    for name in ("a", "b", "c"):
        (skill / "references" / f"{name}.md").write_text("x\n")

    assert run(["flow", "--json", str(skill)]) == 0
    data = json.loads(capsys.readouterr().out)["data"][0]
    assert {edge["kind"] for edge in data["edges"]} == {
        "load",
        "handoff",
        "mention",
        "role",
    }


def test_flow_json_distinguishes_absent_route_from_present_null(
    tmp_path, capsys
) -> None:
    from varde_learn.docs.cli import run

    skill = tmp_path / "demo"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "| Request | Read |\n|---|---|\n| Build it | `references/build.md` |\n\n"
        "Before edits, read `references/gate.md`.\n"
    )
    (skill / "references/build.md").write_text("See `references/shared.md`.\n")
    (skill / "references/gate.md").write_text("gate\n")
    (skill / "references/shared.md").write_text("shared\n")

    assert run(["flow", "--json", str(skill)]) == 0
    edges = json.loads(capsys.readouterr().out)["data"][0]["edges"]
    by_target = {edge["to"]: edge for edge in edges}
    assert by_target["references/gate.md"]["route"] is None
    assert "route" not in by_target["references/shared.md"]


def test_external_handoff_and_route_membership() -> None:
    skill_call = External(
        "SKILL.md",
        ExternalType.SKILL,
        "varde-next mode",
        "varde-next",
        "mode",
        Runs(skill="varde-next", mode="mode"),
        "context",
        False,
        EdgeKind.HANDOFF,
        False,
        4,
    )
    assert skill_call.is_handoff()
    assert skill_call.serves_route("anything")


def test_ordered_map_preserves_insertion_order_and_lookups() -> None:
    values = OrderedMap([("second", 2), ("first", 1)])
    assert values.get("first") == 1
    assert values.get("missing") is None
    assert values.contains_key("second")
    assert list(values.iter()) == [("second", 2), ("first", 1)]
