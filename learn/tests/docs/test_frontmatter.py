from pathlib import Path

import pytest
from varde_learn.docs.frontmatter import InputError, SkillResult, check, render_text

DESCRIPTION = 'description: "Example skill"\n'


def write_skill(root: Path, name: str, content: str) -> Path:
    path = root / name
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(content, encoding="utf-8")
    return path


def validate(
    tmp_path: Path, extra: str = "", description: str = DESCRIPTION
) -> SkillResult:
    skill = write_skill(
        tmp_path, "sample", f"---\nname: sample\n{description}{extra}---\n# Sample\n"
    )
    return check([skill])[0]


def check_text(tmp_path: Path, content: str) -> SkillResult:
    return check([write_skill(tmp_path, "s", content)])[0]


def test_duplicate_and_unhashable_keys(tmp_path: Path) -> None:
    for extra in [
        "name: sample\n",
        "description: Different description\n",
        "metadata:\n  owner: one\n  owner: two\n",
        "defaults: &defaults\n  owner: one\n  owner: two\nmetadata:\n  <<: *defaults\n",
        "metadata:\n  <<: {owner: one}\n  <<: {owner: two}\n",
        "extra:\n  a: 1\n  a: 2\n",
        "base: &b {a: 1, a: 2}\nmetadata:\n  <<: *b\n",
    ]:
        result = validate(tmp_path, extra)
        assert not result.ok and "duplicate key" in result.errors[0]
    assert not validate(tmp_path, "? [one, two]\n: value\n").ok


def test_unknown_keys_and_python_key_display(tmp_path: Path) -> None:
    result = validate(tmp_path, "1: foo\nextra: bar\n")
    assert result.warnings == [
        "unrecognized frontmatter field `1` (client-specific fields are fine)",
        "unrecognized frontmatter field `extra` (client-specific fields are fine)",
    ]
    result = validate(tmp_path, "zeta: 1\ntrue: 2\n~: 3\nalpha: 4\n")
    assert [warning.split("`")[1] for warning in result.warnings] == [
        "None",
        "True",
        "alpha",
        "zeta",
    ]


def test_description_line_rules(tmp_path: Path) -> None:
    assert validate(tmp_path, description='description: "A single line"\n').ok
    for description in [
        "description: Plain text\n",
        "description: 'Single quoted'\n",
        "description: >\n  Folded text\n",
        "description: |\n  Literal text\n",
        'description: "First line\n  second line"\n',
        'description: &value "Anchored"\n',
    ]:
        assert (
            "`description` must be one double-quoted physical line"
            in validate(tmp_path, description=description).errors
        )
    assert validate(tmp_path, description='description: "say \\"hi\\""\n').ok


def test_merge_precedence_aliases_and_tags(tmp_path: Path) -> None:
    for extra in [
        "metadata:\n  <<: {owner: inherited}\n  owner: explicit\n",
        "metadata:\n  <<: [{owner: first}, {owner: second}]\n",
        (
            "defaults: &defaults\n  <<: {owner: inherited}\n  owner: explicit\n"
            "metadata:\n  <<: *defaults\n"
        ),
        (
            "defaults: &defaults\n  <<: {owner: inherited}\n  owner: explicit\n"
            "metadata: *defaults\n"
        ),
        "metadata:\n  <<: {owner: 5}\n  owner: explicit\n",
    ]:
        assert validate(tmp_path, extra).ok
    inherited = write_skill(
        tmp_path,
        "inherited",
        "---\nname: inherited\n<<: {description: inherited}\n---\n",
    )
    assert check([inherited])[0].ok
    assert not validate(tmp_path, "metadata:\n  <<: {owner: 5}\n").ok
    for value in ["!!python/object:builtins.object {}", "!!str one"]:
        assert (
            "unsupported tag"
            in validate(tmp_path, f"metadata:\n  owner: {value}\n").errors[0]
        )
    assert not validate(tmp_path, "extra: [a,\n  b, !!python/object:x c]\n").ok
    assert validate(
        tmp_path, "note: \"wow !!x\" # !!y\nother: 'it''s !!z'\nplain: hi!!\n"
    ).ok


def test_yaml_11_vs_12_scalar_values(tmp_path: Path) -> None:
    # YAML 1.2 core schema: `true`, `false`, and `null` are non-string scalars,
    # while `yes`, `no`, `on`, `off`, and `y` are plain strings. YAML 1.1 would
    # resolve several of these to booleans or numbers.
    for value in ["yes", "no", "on", "off", "y", "Yes", "1_000", "1:30"]:
        assert validate(tmp_path, f"metadata:\n  owner: {value}\n").ok
    for value in ["true", "false", "null", "5", "0o17", "1.5", "[a]", "{a: b}"]:
        assert not validate(tmp_path, f"metadata:\n  owner: {value}\n").ok


def test_required_fields_types_and_limits(tmp_path: Path) -> None:
    assert check_text(tmp_path, "# Title\n").errors == [
        "no `---`-delimited YAML frontmatter block found at the top of the file"
    ]
    assert check_text(tmp_path, "---\n---\n").errors == [
        "no `---`-delimited YAML frontmatter block found at the top of the file"
    ]
    assert check_text(tmp_path, "---\n- a\n- b\n---\n").errors == [
        "frontmatter must be a YAML mapping (key: value pairs)"
    ]
    assert check_text(tmp_path, "---\n\n---\n").errors == [
        "frontmatter must be a YAML mapping (key: value pairs)"
    ]
    assert (
        check_text(tmp_path, "---\nname: a: b\n---\n")
        .errors[0]
        .startswith("frontmatter is not valid YAML: ")
    )
    assert check_text(tmp_path, '---\ndescription: "d"\n---\n').errors == [
        "missing required field `name`"
    ]
    assert check_text(tmp_path, '---\nname: s\ndescription: "  "\n---\n').errors == [
        "missing required field `description`"
    ]
    assert check_text(tmp_path, '---\nname: 0\ndescription: "d"\n---\n').errors == [
        "missing required field `name`"
    ]
    assert (
        check_text(tmp_path, '---\nname: 1.5\ndescription: "d"\n---\n').errors[0]
        == "`name` must be a string, got float"
    )
    assert check_text(tmp_path, "---\nname: s\ndescription: 5\n---\n").errors == [
        "`description` must be a string, got int",
        "`description` must be one double-quoted physical line",
    ]
    assert (
        check_text(
            tmp_path, '---\nname: s\ndescription: "' + "x" * 1025 + '"\n---\n'
        ).errors[0]
        == "`description` is 1025 chars, max is 1024"
    )
    assert check_text(
        tmp_path, '---\nname: s\ndescription: "d"\ncompatibility: 5\n---\n'
    ).errors == ["`compatibility` must be a string, got int"]
    assert check_text(
        tmp_path, '---\nname: s\ndescription: "d"\nmetadata: [a]\n---\n'
    ).errors == ["`metadata` must be a map of string keys to string values"]
    assert check_text(
        tmp_path, '---\nname: s\ndescription: "d"\nallowed-tools: [a]\n---\n'
    ).errors == ["`allowed-tools` must be a string, got list"]


def test_name_path_newlines_and_body_budget(tmp_path: Path) -> None:
    name = "a" * 65
    assert check(
        [write_skill(tmp_path, name, f'---\nname: {name}\ndescription: "d"\n---\n')]
    )[0].errors == ["`name` is 65 chars, max is 64"]
    assert (
        check_text(tmp_path, '---\nname: Bad--Name\ndescription: "d"\n---\n')
        .errors[0]
        .startswith("`name` 'Bad--Name' must be lowercase")
    )
    assert check_text(
        tmp_path, '---\r\nname: s\r\ndescription: "d"\r\n---\r\n# Body\r\n'
    ).ok
    assert check_text(tmp_path, '---\nname: s\ndescription: "d"\n---trailing\n').ok
    head = '---\nname: s\ndescription: "d"\n---\n'
    assert not check_text(tmp_path, head + "x\n" * 499).warnings
    assert (
        check_text(tmp_path, head + "x\n" * 500)
        .warnings[0]
        .startswith("SKILL.md body is ~501 lines")
    )


def test_relations_and_input_errors(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    write_skill(
        root,
        "s",
        '---\nname: s\ndescription: "d"\nrequires: [dep]\nrecommends: [extra]\n---\n',
    )
    write_skill(root, "dep", '---\nname: dep\ndescription: "d"\n---\n')
    write_skill(root, "extra", '---\nname: extra\ndescription: "d"\n---\n')
    assert all(result.ok for result in check([root]))
    assert check([root / "s"])[0].ok and check([root / "s" / "SKILL.md"])[0].ok
    with pytest.raises(InputError, match="path not found"):
        check([root / "missing"])
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(InputError, match="no SKILL.md found"):
        check([empty])
    for relation, expected in [
        ("requires: [missing]\n", "`requires` names unknown skill `missing`"),
        ("recommends: [missing]\n", "`recommends` names unknown skill `missing`"),
        ("requires: [varde-manage]\n", "must not list `varde-manage`"),
        ("recommends: [s]\n", "`recommends` must not name the skill itself"),
        ("requires: {a: b}\n", "is not a flow list of skill names"),
    ]:
        skill = write_skill(
            tmp_path / "relations",
            "s",
            f'---\nname: s\ndescription: "d"\n{relation}---\n',
        )
        assert any(expected in error for error in check([skill])[0].errors)
    assert SkillResult("x").to_json() == {
        "path": "x",
        "errors": [],
        "warnings": [],
        "ok": True,
    }
    assert render_text([SkillResult("x")]) == "OK    x\n"


def relation_results(tmp_path: Path, skills: dict[str, str]) -> list[SkillResult]:
    root = tmp_path / "relation-root"
    for name, relations in skills.items():
        write_skill(
            root, name, f'---\nname: {name}\ndescription: "d"\n{relations}---\n'
        )
    return check([root])


def errors_for(results: list[SkillResult], name: str) -> list[str]:
    return next(result.errors for result in results if f"/{name}/" in result.path)


def test_relation_keys_are_known_fields(tmp_path: Path) -> None:
    result = relation_results(tmp_path, {"s": "requires: []\nrecommends: []\n"})[0]
    assert result.errors == []
    assert result.warnings == []


def test_known_require_and_recommend_pass(tmp_path: Path) -> None:
    results = relation_results(
        tmp_path,
        {"s": "requires: [dep]\nrecommends: [extra]\n", "dep": "", "extra": ""},
    )
    assert all(result.ok for result in results)


def test_self_reference_and_cycles_are_rejected(tmp_path: Path) -> None:
    results = relation_results(tmp_path, {"s": "requires: [s]\n"})
    assert any("cycle" in error and "s" in error for error in errors_for(results, "s"))
    results = relation_results(
        tmp_path, {"s": "requires: [a]\n", "a": "requires: [s]\n"}
    )
    assert any("cycle" in error and "a" in error for error in errors_for(results, "s"))


def test_recommends_does_not_resolve_required_dependencies(tmp_path: Path) -> None:
    results = relation_results(
        tmp_path, {"s": "recommends: [dep]\n", "dep": "requires: [missing]\n"}
    )
    assert errors_for(results, "s") == []
    assert errors_for(results, "dep")


def test_relative_skill_directory_has_no_relation_root(
    tmp_path: Path, monkeypatch
) -> None:
    skill = write_skill(
        tmp_path, "s", '---\nname: s\ndescription: "d"\nrequires: [missing]\n---\n'
    )
    monkeypatch.chdir(skill.parent)
    result = check([Path("s")])[0]
    assert not any("unknown skill" in error for error in result.errors)


def test_directory_search_is_one_level_and_accepts_skill_file(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    first = write_skill(root, "a", '---\nname: a\ndescription: "d"\n---\n')
    write_skill(root, "b", '---\nname: b\ndescription: "d"\n---\n')
    write_skill(root / "b" / "nested", "c", '---\nname: c\ndescription: "d"\n---\n')
    assert [Path(result.path).parent.name for result in check([root])] == ["a", "b"]
    assert Path(check([first / "SKILL.md"])[0].path) == first / "SKILL.md"
    assert Path(check([Path(f"{first}/")])[0].path) == first / "SKILL.md"


def test_missing_and_empty_inputs_raise_input_error(tmp_path: Path) -> None:
    with pytest.raises(InputError) as missing:
        check([tmp_path / "nope"])
    assert (
        str(missing.value) == f"varde learn check: path not found: {tmp_path / 'nope'}"
    )
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(InputError, match="no SKILL.md found"):
        check([empty])
    readme = tmp_path / "README.md"
    readme.write_text("x")
    with pytest.raises(InputError):
        check([readme])


def test_rendered_output_has_stable_rows_and_diagnostics(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    write_skill(root, "good", '---\nname: good\ndescription: "d"\nextra: 1\n---\n')
    write_skill(root, "bad", "---\nname: wrong\ndescription: d\n---\n")
    results = check([root])
    text = render_text(results).replace(f"{root}/", "")
    assert text == (
        "FAIL  bad/SKILL.md\n"
        "      error:   `name` 'wrong' must match parent directory name 'bad'\n"
        "      error:   `description` must be one double-quoted physical line\n"
        "OK    good/SKILL.md\n"
        "      warning: unrecognized frontmatter field `extra` "
        "(client-specific fields are fine)\n"
    )


def test_tag_scanner_respects_yaml_quoting_and_block_scalars(tmp_path: Path) -> None:
    assert not validate(
        tmp_path,
        "compatibility: rock 'n roll\nextra: !!python/object:builtins.object {}\n",
    ).ok
    assert not validate(tmp_path, 'notes: |\n  say "foo\n  bar\nextra: !!str x\n').ok
    assert validate(tmp_path, "notes: |\n  keep !!str as is\n").ok
    assert validate(tmp_path, "compatibility: wow !! great\n").ok


def test_quoted_merge_key_is_an_ordinary_unknown_field(tmp_path: Path) -> None:
    result = validate(tmp_path, '"<<": {owner: x}\n')
    assert result.ok
    assert any("<<" in warning for warning in result.warnings)
    assert validate(tmp_path, "'<<': 5\n").ok


def test_duplicate_key_errors_use_normalized_wording(tmp_path: Path) -> None:
    assert "duplicate key" in validate(tmp_path, "a: {x: 1, x: 2}\n").errors[0]
    message = validate(tmp_path, "~: 1\n~: 2\n").errors[0]
    assert "duplicate key" in message
    assert "duplicate entry" not in message


def test_no_skill_found_error_names_the_given_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(InputError) as error:
        check([Path(".")])
    assert str(error.value) == ("varde learn check: no SKILL.md found at or under .")


def test_real_skill_authoring_skill_validates() -> None:
    fixture = (
        Path(__file__).parents[2]
        / "src"
        / "varde_learn"
        / "skills"
        / "varde-skill-authoring"
    )
    result = check([fixture])
    assert len(result) == 1
    assert result[0].ok, result[0]


def test_merged_description_does_not_trigger_physical_line_check(
    tmp_path: Path,
) -> None:
    skill = write_skill(
        tmp_path, "sample", "---\nname: sample\n<<: {description: inherited}\n---\n"
    )
    assert check([skill])[0].ok


def test_merged_unknown_fields_still_warn(tmp_path: Path) -> None:
    skill = write_skill(
        tmp_path,
        "sample",
        (
            '---\nname: sample\ndescription: "d"\nbase: &b\n  owner: one\n'
            "metadata:\n  <<: *b\n---\n"
        ),
    )
    result = check([skill])[0]
    assert result.ok
    assert any("`base`" in warning for warning in result.warnings)
