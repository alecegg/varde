import tomllib

from varde_core import skill_props as sp


def test_round_trip_keeps_unknown_keys():
    props = sp.Props(
        packaged_version="1.0",
        packaged_hash="abc",
        loop_hash="def",
        pending_version="1.1",
        pending_hash="ghi",
        extra=(("future", "x=y"),),
    )
    assert sp.parse(sp.render(props)) == props


def test_marker_only_sidecar_parses_as_no_properties():
    assert sp.parse("varde-managed-skill\n") == sp.Props()
    assert sp.render(sp.Props()) == "varde-managed-skill\n"


def test_render_starts_with_marker_line():
    assert (
        sp.render(sp.Props(packaged_hash="a")).splitlines()[0] == "varde-managed-skill"
    )


def test_hash_ignores_sidecar_and_changes_with_bytes_or_paths():
    base = {"SKILL.md": b"a", "references/x.md": b"b"}
    assert sp.tree_hash({**base, sp.SIDECAR: b"junk"}) == sp.tree_hash(base)
    assert sp.tree_hash({**base, "SKILL.md": b"A"}) != sp.tree_hash(base)
    assert sp.tree_hash({"SKILL.md": b"a", "references/y.md": b"b"}) != sp.tree_hash(
        base
    )
    assert sp.tree_hash({"ab": b"c"}) != sp.tree_hash({"a": b"bc"})


def test_modified_detection():
    props = sp.Props(packaged_hash="h1")
    assert not sp.is_modified(props, "h1")
    assert sp.is_modified(props, "h2")
    assert sp.is_modified(sp.Props(), "h2")


def test_hashed_paths_skip_sidecar_dotfiles_and_bytecode():
    assert sp.is_hashed_path("SKILL.md")
    assert sp.is_hashed_path("step_tools/x/y.py")
    assert not sp.is_hashed_path(sp.SIDECAR)
    assert not sp.is_hashed_path("step_tools/__pycache__/y.pyc")
    assert not sp.is_hashed_path("references/.hidden")


def test_hashed_path_skips_evals_and_workspaces():
    assert not sp.is_hashed_path("evals/a.json")
    assert not sp.is_hashed_path("x-workspace/a.md")
    assert sp.is_hashed_path("references/a.md")


def test_registry_renderer_escapes_and_joins():
    text = sp.render_registry([("a", "b", 'c"d'), ("e", "f", "g")])
    assert 'entry = "c\\"d"' in text
    assert text.count("[[tool]]") == 2
    assert tomllib.loads(text)["tool"][0]["entry"] == 'c"d'
