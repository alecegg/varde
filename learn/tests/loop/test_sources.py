import os
import stat
from pathlib import Path

import pytest
from varde_learn.loop.sources import (
    HARNESSES,
    _check_readable,
    is_ignored,
    load_locations,
    resolve_locations,
)


def test_defaults_and_env_overrides():
    env = {
        "HOME": "/home/test",
        "CODEX_HOME": "/custom/codex",
        "CLAUDE_CONFIG_DIR": "/custom/claude",
        "PI_CODING_AGENT_SESSION_DIR": "/custom/pi",
        "XDG_DATA_HOME": "/custom/data",
    }
    locations = resolve_locations({}, env, lambda path: True)
    assert [(row.harness, row.path) for row in locations] == [
        ("codex", Path("/custom/codex")),
        ("claude", Path("/custom/claude/projects")),
        ("opencode", Path("/custom/data/opencode")),
        ("pi", Path("/custom/pi")),
    ]
    assert all(row.origin == "default" and row.status == "ok" for row in locations)

    codex_tilde = resolve_locations(
        {},
        {**env, "CODEX_HOME": "~/custom-codex"},
        lambda path: True,
    )[0]
    assert codex_tilde.path == Path("/home/test/custom-codex")


def test_extra_roots_and_defaults_false():
    locations = resolve_locations(
        {
            "codex": {"roots": ["~/extra"]},
            "claude": {"defaults": False, "roots": ["/claude-alt"]},
            "ignore": {"paths": ["/repo", "~/private"]},
        },
        {"HOME": "/home/test"},
        lambda path: True,
    )
    assert [(row.harness, row.path, row.origin) for row in locations] == [
        ("codex", Path("/home/test/.codex"), "default"),
        ("codex", Path("/home/test/extra"), "config"),
        ("claude", Path("/claude-alt"), "config"),
        ("opencode", Path("/home/test/.local/share/opencode"), "default"),
        ("pi", Path("/home/test/.pi/agent/sessions"), "default"),
    ]
    assert locations[0].ignored_paths == (Path("/repo"), Path("/home/test/private"))


def test_defaults_false_disables_every_harness():
    config = {harness: {"defaults": False} for harness in HARNESSES}
    assert resolve_locations(config, {"HOME": "/home/test"}, lambda path: True) == []


def test_duplicate_root_remains_a_visible_location():
    locations = resolve_locations(
        {"codex": {"roots": ["/home/test/.codex", "/home/test/.codex"]}},
        {"HOME": "/home/test"},
        lambda path: True,
    )
    codex = [row for row in locations if row.harness == "codex"]
    assert [(row.path, row.origin, row.status) for row in codex] == [
        (Path("/home/test/.codex"), "default", "ok"),
        (Path("/home/test/.codex"), "config", "ok"),
        (Path("/home/test/.codex"), "config", "ok"),
    ]


def test_tilde_expansion_is_limited_to_tilde_and_tilde_slash():
    locations = resolve_locations(
        {"codex": {"defaults": False, "roots": ["~", "~/session", "~other/session"]}},
        {"HOME": "/home/test"},
        lambda path: True,
    )
    codex_paths = [row.path for row in locations if row.harness == "codex"]
    assert codex_paths == [
        Path("/home/test"),
        Path("/home/test/session"),
        Path("~other/session"),
    ]


def test_missing_and_injected_unreadable_locations_are_reported():
    def exists(path: Path) -> bool | tuple[str, str]:
        if path == Path("/denied"):
            return "unreadable", "permission denied"
        return False

    locations = resolve_locations(
        {"codex": {"defaults": False, "roots": ["/missing", "/denied"]}},
        {"HOME": "/home/test"},
        exists,
    )
    assert [
        (row.status, row.reason) for row in locations if row.harness == "codex"
    ] == [
        ("missing", "location does not exist"),
        ("unreadable", "permission denied"),
    ]


def test_real_unreadable_directory_is_reported(tmp_path):
    unreadable = tmp_path / "unreadable"
    unreadable.mkdir()
    unreadable.chmod(0)
    try:
        status, reason = _check_readable(unreadable)
        assert (status, reason) == ("unreadable", "permission denied")
    finally:
        unreadable.chmod(stat.S_IRWXU)


def test_ignore_paths_match_only_the_path_or_a_directory_prefix():
    ignored = [Path("/repo"), Path("/home/test/private")]
    assert is_ignored("/repo", ignored)
    assert is_ignored("/repo/project/session.jsonl", ignored)
    assert is_ignored("/home/test/private/session", ignored)
    assert not is_ignored("/repo-copy/session.jsonl", ignored)
    assert not is_ignored("/other/session.jsonl", ignored)


@pytest.mark.parametrize(
    "config",
    [
        {"bogus": {"roots": ["/x"]}},
        {"codex": {"unknown": True}},
        {"codex": {"roots": "/x"}},
        {"pi": {"defaults": "no"}},
        {"ignore": {"paths": "no"}},
    ],
)
def test_invalid_config_has_clear_error(config):
    with pytest.raises(ValueError, match="sources config"):
        resolve_locations(config, {"HOME": "/home/test"}, lambda path: True)


def test_loader_reads_toml(tmp_path):
    config = tmp_path / "sources.toml"
    config.write_text('[codex]\nroots = ["/extra"]\n', encoding="utf-8")
    locations = load_locations(
        config, env={"HOME": "/home/test"}, exists=lambda path: True
    )
    assert locations[1].path == Path("/extra")


def test_loader_reports_invalid_toml_and_config_path(tmp_path):
    config = tmp_path / "broken-sources.toml"
    config.write_text("[codex\nroots = [", encoding="utf-8")
    with pytest.raises(ValueError, match=f"sources config {config}"):
        load_locations(config, env={"HOME": "/home/test"}, exists=lambda path: True)


def test_opencode_default_matches_cli_diagnose(monkeypatch, tmp_path):
    from varde_learn.loop.cli_diagnose import _opencode_root as diagnose_opencode_root
    from varde_learn.loop.sources import _defaults

    db = tmp_path / "custom-opencode.db"
    monkeypatch.setenv("OPENCODE_DB", str(db))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert _defaults(dict(os.environ))["opencode"] == diagnose_opencode_root()

    monkeypatch.delenv("OPENCODE_DB")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert _defaults(dict(os.environ))["opencode"] == diagnose_opencode_root()
