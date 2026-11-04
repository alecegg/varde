from varde_learn.knowledge.formats import edit_toml


def test_toml_edit_keeps_comments_and_seeded_hooks() -> None:
    existing = (
        "# user config\n[hooks.session_start]\n# retain seed\n\n[default]\n"
        '# keep this comment\nold = "old" # inline\nstale = true\n'
    )
    fresh = '[hooks.session_start]\n\n[default]\nold = "new"\nadded = 2\n'

    result = edit_toml(existing, fresh)

    assert result == (
        "# user config\n[hooks.session_start]\n# retain seed\n\n"
        '[default]\n# keep this comment\nold = "new" # inline\nadded = 2\n'
    )


def test_toml_edit_matches_project_and_default_table_decor() -> None:
    added_project = edit_toml(
        '[hooks.capture]\nmode = "fast"\n',
        '[project."/x/q"]\nworking = "work"\n\n[hooks.capture]\nmode = "fast"\n',
    )
    assert added_project == (
        '[project."/x/q"]\nworking = "work"\n[hooks.capture]\nmode = "fast"\n'
    )

    appended_project = edit_toml(
        '[hooks.capture]\nmode = "fast"\n',
        '[hooks.capture]\nmode = "fast"\n\n[project."/x/q"]\nworking = "work"\n',
    )
    assert appended_project == (
        '[hooks.capture]\nmode = "fast"\n[project."/x/q"]\nworking = "work"\n'
    )

    removed_default = edit_toml('[default]\n# seeded\nworking = "work"\n', "")
    assert removed_default == ""


def test_toml_edit_drops_removed_default_decor_and_keeps_hook_spacing() -> None:
    assert (
        edit_toml(
            '[default]\n# seeded\nworking = "work"\nknowledge = "docs"\n',
            '[default]\nknowledge = "docs"\n',
        )
        == '[default]\nknowledge = "docs"\n'
    )
    assert (
        edit_toml(
            '# top\n[default]\nworking = "work"\nknowledge = "docs"\n',
            "",
        )
        == ""
    )
    assert edit_toml(
        '[hooks.capture]\nmode = "fast"\n\n[default]\nworking = "work"\n',
        (
            '[hooks.capture]\nmode = "fast"\n\n[default]\n'
            'working = "work"\nknowledge = "docs"\n'
        ),
    ) == (
        '[hooks.capture]\nmode = "fast"\n\n[default]\n'
        'working = "work"\nknowledge = "docs"\n'
    )


def test_toml_edit_unsets_stale_values_and_falls_back_on_invalid_input() -> None:
    assert edit_toml("value = 1\nstale = 2\n", "value = 1\n") == "value = 1\n"
    assert edit_toml("not = [valid", "value = 2\n") == "value = 2\n"
