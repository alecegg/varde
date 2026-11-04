from varde_learn.knowledge import memory_config
from varde_learn.knowledge.memory_config import merge_toml_text


def test_merge_toml_text_preserves_user_content_and_applies_new_values() -> None:
    cases = [
        (
            '# user\n[default]\n# note\nworking = "old" # inline\nstale = 1\n',
            '[default]\nworking = "new"\nknowledge = "docs"\n',
            '# user\n[default]\n# note\nworking = "new" # inline\nknowledge = "docs"\n',
        ),
        (
            '[default]\nworking = "a"\nknowledge = "b"\n',
            '[default]\nworking = "a"\n',
            '[default]\nworking = "a"\n',
        ),
        (
            '[hooks.session_start]\n# seeded\n\n[default]\nworking = "x"\n',
            "[hooks.session_start]\n\n[default]\n",
            "[hooks.session_start]\n# seeded\n\n[default]\n",
        ),
        (
            '# keep comment\n[default]\nworking = "x"\n',
            "[default]\n",
            "# keep comment\n[default]\n",
        ),
    ]
    for existing, fresh, expected in cases:
        assert merge_toml_text(existing, fresh) == expected


def test_seeded_hooks_and_comments_are_retained_on_empty_save(
    monkeypatch, tmp_path
) -> None:
    from varde_learn.knowledge import memory_config

    path = tmp_path / "config.toml"
    path.write_text("# seeded\n[hooks.session_start]\n")
    monkeypatch.setattr(memory_config, "config_path", lambda: path)
    assert memory_config.save_config(memory_config.Config()) == path
    assert path.read_text() == "# seeded\n[hooks.session_start]\n"


def test_empty_config_without_seeded_content_is_removed(monkeypatch, tmp_path) -> None:
    from varde_learn.knowledge import memory_config

    path = tmp_path / "config.toml"
    path.write_text("[default]\n")
    monkeypatch.setattr(memory_config, "config_path", lambda: path)
    memory_config.save_config(memory_config.Config())
    assert not path.exists()


def test_inline_path_config_resolves_values_fallback_and_unknown_option(
    tmp_path, monkeypatch, capsys
) -> None:
    from varde_learn.knowledge.memory import MemoryPaths
    from varde_learn.module import register

    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.delenv("VARDE_WORKING_DIR", raising=False)
    monkeypatch.delenv("VARDE_KNOWLEDGE_DIR", raising=False)
    config = memory_config.Config.from_toml('[default]\nworking = "notes"\n')

    paths = MemoryPaths.resolve_with(project, config.document)

    assert paths.working.path == project / "notes"
    assert paths.knowledge.source.value == "builtin"
    assert not paths.knowledge.path.is_relative_to(project)
    assert (
        register().run(["paths", "set", "--project", str(project), "--bogus", "x"]) != 0
    )
    assert "bogus" in capsys.readouterr().err


def test_paths_reports_legacy_memory_bank(tmp_path, monkeypatch, capsys) -> None:
    import json

    from varde_learn.module import register

    project = tmp_path / "project"
    (project / "memory-bank" / "working").mkdir(parents=True)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("VARDE_WORKING_DIR", raising=False)
    monkeypatch.delenv("VARDE_KNOWLEDGE_DIR", raising=False)

    assert register().run(["paths", "--project", str(project)]) == 0
    text = capsys.readouterr().out
    assert "legacy memory-bank found" in text
    assert "--working memory-bank/working" in text
    assert register().run(["paths", "--project", str(project), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["legacy_memory_bank"] == [str(project / "memory-bank" / "working")]

    register().run(
        ["paths", "set", "--project", str(project), "--working", "memory-bank/working"]
    )
    capsys.readouterr()
    assert register().run(["paths", "--project", str(project), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["legacy_memory_bank"] == []


def test_paths_lists_memory_kind(tmp_path, monkeypatch, capsys) -> None:
    import json

    from varde_learn.module import register

    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("VARDE_MEMORY_DIR", raising=False)

    assert register().run(["paths", "--project", str(project), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["memory_source"] == "builtin"
    assert data["memory"].endswith("varde/memory")
    assert register().run(["paths", "--project", str(project)]) == 0
    assert "memory: " in capsys.readouterr().out

    monkeypatch.setenv("VARDE_MEMORY_DIR", str(tmp_path / "env-mem"))
    assert register().run(["paths", "--project", str(project), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["memory_source"] == "env"
    assert data["memory"] == str(tmp_path / "env-mem")


def test_memory_budget_default_and_override() -> None:
    assert memory_config.Config.from_toml("").memory.budget_chars() == (1200, None)
    config = memory_config.Config.from_toml("[memory]\nbudget = 300\n")
    assert config.memory.budget_chars() == (300, None)


def test_memory_budget_falls_back_with_message() -> None:
    for text in ("[memory]\nbudget = 0\n", '[memory]\nbudget = "x"\n'):
        value, error = memory_config.Config.from_toml(text).memory.budget_chars()
        assert value == 1200
        assert error is not None
        assert "positive integer" in error
    value, error = memory_config.Config.from_toml("memory = 3\n").memory.budget_chars()
    assert (value, error) == (1200, "`memory` is not a table")


def test_orchestration_settings_unchanged_beside_memory() -> None:
    config = memory_config.Config.from_toml(
        "[orchestration]\nwake_timeout_seconds = 5\n[memory]\nbudget = 9\n"
    )
    assert config.orchestration.wake_timeout_seconds() == (5, None)
    assert config.orchestration.wake_max_failures() == (3, None)
    bad = memory_config.Config.from_toml("orchestration = 1\n")
    assert bad.orchestration.wake_timeout_seconds() == (
        10,
        "`orchestration` is not a table",
    )


def test_memory_shared_reads_a_non_empty_string() -> None:
    config = memory_config.Config.from_toml(
        '[memory]\nshared = "git@h:team/mem.git"\nbudget = 9\n'
    )
    assert config.memory.shared() == ("git@h:team/mem.git", None)
    assert config.memory.budget_chars() == (9, None)


def test_memory_shared_reports_absent_empty_and_non_string() -> None:
    for text in (
        "",
        "[memory]\nbudget = 3\n",
        '[memory]\nshared = ""\n',
        "[memory]\nshared = 3\n",
    ):
        value, error = memory_config.Config.from_toml(text).memory.shared()
        assert value == ""
        assert error is not None
    value, error = memory_config.Config.from_toml("memory = 3\n").memory.shared()
    assert (value, error) == ("", "`memory` is not a table")


def test_set_default_memory_edits_text_only(tmp_path) -> None:
    from varde_learn.knowledge.paths_memory import set_default_memory

    assert set_default_memory("", "/m") == '[default]\nmemory = "/m"\n'
    existing = '# user\n[default]\nworking = "w" # keep\n[hooks.x]\n'
    result = set_default_memory(existing, "/m")
    assert (
        result == '# user\n[default]\nworking = "w" # keep\nmemory = "/m"\n[hooks.x]\n'
    )
    assert set_default_memory(result, "/n").count("memory") == 1
    assert set_default_memory(result, "/m") == result
    assert list(tmp_path.iterdir()) == []


def test_unset_default_memory_keeps_other_content() -> None:
    from varde_learn.knowledge.paths_memory import (
        set_default_memory,
        unset_default_memory,
    )

    text = '# user\n[default]\nworking = "w"\nmemory = "/m"\n'
    assert unset_default_memory(text) == '# user\n[default]\nworking = "w"\n'
    assert unset_default_memory('[default]\nmemory = "/m"\n') == ""
    assert unset_default_memory("[x]\na = 1\n") == "[x]\na = 1\n"
    assert unset_default_memory(set_default_memory("", "/m")) == ""


def test_memory_default_rejects_bad_input() -> None:
    import pytest
    from varde_learn.knowledge.memory_config import MemoryConfigError
    from varde_learn.knowledge.paths_memory import set_default_memory

    for text, directory in (("[default", "/m"), ("default = 1\n", "/m"), ("", " ")):
        with pytest.raises(MemoryConfigError):
            set_default_memory(text, directory)
