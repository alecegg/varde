from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from varde_toz import cli
from varde_toz.chunk import chunk_default
from varde_toz.project import project_key
from varde_toz.store import NewCapture, Store


@pytest.fixture(autouse=True)
def _disable_json_from_prior_cli_invocations(monkeypatch):
    monkeypatch.setenv("TOZ_JSON", "0")


def _store(root: Path, config: Path) -> Store:
    return Store.open(config / project_key(root) / "toz.db")


def test_stats_json_events_and_session_filter(tmp_path, monkeypatch, capsys):
    root, config, home = (tmp_path / name for name in ("repo", "toz", "home"))
    root.mkdir()
    config.mkdir()
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(config))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "varde"))
    monkeypatch.setenv("VARDE_TOZ_SESSION", "session-a")
    store = _store(root, config)
    now = int(time.time())
    store.conn.executemany(
        "INSERT INTO stats_log(ts,kind,bytes_in,bytes_out,session) VALUES(?,?,?,?,?)",
        [(now, "run", 100, 20, "session-a"), (now, "capture", 50, 10, "session-b")],
    )
    store.conn.execute(
        (
            "INSERT INTO query_log(ts,kind,bytes_out,session,outcome,details_json) "
            "VALUES(?,?,?,?,?,?)"
        ),
        (now, "chunk", 5, "session-a", "ok", '{"handle":"abc"}'),
    )
    store.conn.commit()

    assert (
        cli.main(
            ["--project", str(root), "--json", "stats", "--session", "--events", "10"]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report[0]["captures"] == 1
    assert report[0]["bytes_in"] == 100
    assert report[0]["net_saved_bytes"] == 75
    assert report[0]["events"][0]["details"] == {"handle": "abc"}
    store.close()


def test_stats_events_rejects_out_of_range(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(tmp_path / "toz"))
    assert cli.main(["--project", str(tmp_path), "stats", "--events", "0"]) == 2
    assert "--events must be between 1 and 10000" in capsys.readouterr().err


def test_purge_older_than_prunes_and_preserves_recent(tmp_path, monkeypatch, capsys):
    root, config = tmp_path / "repo", tmp_path / "toz"
    root.mkdir()
    config.mkdir()
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(config))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "varde"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "varde"))
    store = _store(root, config)
    old = store.insert_capture(
        NewCapture("old", "run", "old", bytes=3), [("stdout", chunk_default("old")[0])]
    )
    recent = store.insert_capture(
        NewCapture("recent", "run", "recent", bytes=5),
        [("stdout", chunk_default("new")[0])],
    )
    store.conn.execute("UPDATE captures SET created_at=0 WHERE handle=?", (old,))
    store.conn.commit()

    assert (
        cli.main(["--project", str(root), "--json", "purge", "--older-than", "1d"]) == 0
    )
    assert json.loads(capsys.readouterr().out) == {"removed": 1}
    assert store.get_by_handle(old) is None
    assert store.get_by_handle(recent)["label"] == "recent"
    store.close()


def test_purge_global_yes_removes_all_stores_and_cache(tmp_path, monkeypatch, capsys):
    root, config = tmp_path / "repo", tmp_path / "toz"
    home = tmp_path / "home"
    root.mkdir()
    config.mkdir()
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(config))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "varde"))
    monkeypatch.delenv("VARDE_TOZ_FALLBACK_DIR", raising=False)
    monkeypatch.delenv("TOZ_FALLBACK_DIR", raising=False)
    _store(root, config).close()
    other = config / "other" / "toz.db"
    Store.open(other).close()
    cache = config / "cache"
    cache.mkdir()
    (cache / "page.meta").write_text("{}")
    (cache / "page.body").write_text("body")

    assert (
        cli.main(["--project", str(root), "--json", "purge", "--global", "--yes"]) == 0
    )
    assert json.loads(capsys.readouterr().out) == {"removed_stores": 2}
    assert not other.parent.exists()
    assert list(cache.iterdir()) == []


@pytest.mark.parametrize(
    ("duration", "expected_removed"),
    [("30m", 4), ("12h", 3), ("7d", 2), ("2w", 1), ("17", 5), ("4secs", 6)],
)
def test_purge_duration_units_select_captures_by_age(
    tmp_path, monkeypatch, capsys, duration, expected_removed
):
    root, config = tmp_path / "repo", tmp_path / "toz"
    root.mkdir()
    config.mkdir()
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(config))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "varde"))
    store = _store(root, config)
    now = int(time.time())
    for age in (10, 100, 2_000, 50_000, 700_000, 1_300_000):
        handle = store.insert_capture(
            NewCapture(f"age-{age}", "run", f"age-{age}", bytes=4),
            [("stdout", chunk_default("body")[0])],
        )
        store.conn.execute(
            "UPDATE captures SET created_at=? WHERE handle=?", (now - age, handle)
        )
    store.conn.commit()
    store.close()

    assert (
        cli.main(["--project", str(root), "--json", "purge", "--older-than", duration])
        == 0
    )
    assert json.loads(capsys.readouterr().out) == {"removed": expected_removed}


def test_purge_rejects_invalid_duration(tmp_path, monkeypatch, capsys):
    root, config = tmp_path / "repo", tmp_path / "toz"
    root.mkdir()
    config.mkdir()
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(config))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "varde"))
    _store(root, config).close()
    assert cli.main(["--project", str(root), "purge", "--older-than", "2months"]) == 2
    assert "invalid duration" in capsys.readouterr().err


def test_purge_rejects_duration_outside_sqlite_integer_range(
    tmp_path, monkeypatch, capsys
):
    root, config = tmp_path / "repo", tmp_path / "toz"
    root.mkdir()
    config.mkdir()
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(config))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "varde"))
    _store(root, config).close()

    assert (
        cli.main(
            [
                "--project",
                str(root),
                "purge",
                "--older-than",
                "999999999999999999999999s",
            ]
        )
        == 2
    )
    assert capsys.readouterr().err == (
        'varde-toz: invalid duration "999999999999999999999999s": '
        "number too large to fit in target type\n"
    )


def test_purge_confirmation_names_scope_and_target_count(tmp_path, monkeypatch, capsys):
    root, config = tmp_path / "repo", tmp_path / "toz"
    root.mkdir()
    config.mkdir()
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(config))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "varde"))
    _store(root, config).close()
    Store.open(config / "other" / "toz.db").close()
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: "n")

    assert cli.main(["--project", str(root), "purge", "--global"]) == 1
    assert (
        capsys.readouterr().err
        == "varde-toz: delete ALL 2 Toz store(s) and cached pages? [y/N] "
    )


def test_profile_test_file_runs_cases_from_given_file(tmp_path, monkeypatch, capsys):
    profile_file = tmp_path / "profiles.toml"
    profile_file.write_text(
        '[[profile]]\nid = "plain"\nmatch = { source = "fixture" }\n\n'
        '[[profile.test]]\nname = "contains"\ninput = "alpha\\nbeta\\n"\n'
        'expect_preview_contains = ["alpha"]\n'
    )
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(tmp_path / "fixture-config"))
    assert cli.main(["profile", "test", "--file", str(profile_file)]) == 0
    assert capsys.readouterr().out == "pass: plain / contains\n"


def test_profile_test_reports_failed_expectation(tmp_path, monkeypatch, capsys):
    profile_file = tmp_path / "profiles.toml"
    profile_file.write_text(
        '[[profile]]\nid = "plain"\nmatch = { source = "fixture" }\n\n'
        '[[profile.test]]\nname = "missing"\ninput = "alpha\\n"\n'
        'expect_preview_contains = ["absent"]\n'
    )
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(tmp_path / "fixture-config"))
    assert cli.main(["profile", "test", "--file", str(profile_file)]) == 1
    assert (
        capsys.readouterr().out == 'FAIL: plain / missing: preview missing "absent"\n'
    )


def test_profile_list_json_contains_builtin_and_diagnostics(
    tmp_path, monkeypatch, capsys
):
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(tmp_path / "toz"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    assert cli.main(["--project", str(root), "--json", "profile", "list"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert len(report["profiles"]) == 4
    assert report["diagnostics"] == []


def test_profile_test_runs_builtin_fixture_cases(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(tmp_path / "toz"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    assert cli.main(["profile", "test"]) == 0
    output = capsys.readouterr().out
    assert output.count("pass:") == 4
    assert "FAIL:" not in output


def test_migrate_metadata_scrubs_legacy_source_fields(tmp_path, monkeypatch, capsys):
    root, config = tmp_path / "repo", tmp_path / "toz"
    root.mkdir()
    config.mkdir()
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(config))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    store = _store(root, config)
    handle = store.insert_capture(
        NewCapture(
            "token=secret-value",
            "run",
            "token=secret-value",
            source_key="token=secret-value",
        ),
        [("stdout", chunk_default("safe output")[0])],
    )
    store.close()

    assert cli.main(["--project", str(root), "--json", "migrate-metadata"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "stores": 1,
        "captures": 1,
        "cached_pages": 0,
    }
    migrated = Store.open(_store(root, config).path)
    row = migrated.get_by_handle(handle)
    assert "secret-value" not in row["label"]
    assert "secret-value" not in row["source"]
    assert migrated.full_text(row["id"]) == "safe output"
    migrated.close()


def test_migrate_metadata_rekeys_legacy_fetch_cache(tmp_path, monkeypatch, capsys):
    import blake3

    root = tmp_path / "repo"
    root.mkdir()
    config = tmp_path / "toz"
    cache = config / "cache"
    cache.mkdir(parents=True)
    (config / "config.toml").write_text('[redact]\npatterns = ["private-value"]\n')
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(config))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "varde"))
    url = "https://example.test/page?token=private-value"
    legacy = blake3.blake3(url.encode()).hexdigest()
    meta = {
        "url": url,
        "final_url": url,
        "content_type": "text/html",
        "fetched_at": 1,
        "title": "private-value title",
        "etag": None,
        "handle": "abc",
        "project_key": "project-key",
    }
    (cache / f"{legacy}.meta").write_text(json.dumps(meta))
    (cache / f"{legacy}.body").write_text("cached response")

    assert cli.main(["--project", str(root), "--json", "migrate-metadata"]) == 0
    assert json.loads(capsys.readouterr().out)["cached_pages"] == 1
    migrated = list(cache.glob("*.meta"))
    assert len(migrated) == 1 and migrated[0].stem != legacy
    document = json.loads(migrated[0].read_text())
    assert "private-value" not in document["url"]
    assert "private-value" not in document["title"]
    assert migrated[0].with_suffix(".body").read_text() == "cached response"

    assert cli.main(["--project", str(root), "--json", "migrate-metadata"]) == 0
    assert json.loads(capsys.readouterr().out)["cached_pages"] == 0


def test_doctor_json_reports_store_fts_cache_and_plugin_checks(
    tmp_path, monkeypatch, capsys
):
    root, config, home = tmp_path / "repo", tmp_path / "toz", tmp_path / "home"
    root.mkdir()
    config.mkdir()
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(config))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    Store.open(_store(root, config).path).close()

    assert cli.main(["--project", str(root), "--json", "doctor"]) == 0
    report = json.loads(capsys.readouterr().out)
    messages = [check["message"] for check in report["checks"]]
    assert any("store opens:" in message for message in messages)
    assert any(
        "FTS5 with trigram tokenizer available" in message for message in messages
    )
    assert report["warnings"] == 0
    assert "hooks" in report


def test_doctor_reports_context_mode_conflict(tmp_path, monkeypatch, capsys):
    root, config, home = tmp_path / "repo", tmp_path / "toz", tmp_path / "home"
    root.mkdir()
    config.mkdir()
    settings = home / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text('{"enabledPlugins":{"context-mode@context-mode":true}}')
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(config))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    Store.open(_store(root, config).path).close()

    assert cli.main(["--project", str(root), "--json", "doctor"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert any(
        not row["ok"] and "context-mode plugin is enabled" in row["message"]
        for row in report["checks"]
    )


def test_profile_test_reports_missing_match_and_empty_records(
    tmp_path, monkeypatch, capsys
):
    profile_file = tmp_path / "profiles.toml"
    profile_file.write_text(
        '[[profile]]\nid="without-match"\n\n[[profile.test]]\n'
        'name="missing match"\ninput="text"\n\n[[profile]]\n'
        'id="records"\nmatch={source="fixture"}\n\n[[profile.test]]\n'
        'name="empty records"\ninput="text"\nexpect_records={}\n'
    )
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(tmp_path / "fixture-config"))
    assert cli.main(["profile", "test", "--file", str(profile_file)]) == 1
    output = capsys.readouterr().out
    assert (
        "FAIL: without-match / missing match: profile has no `match`; "
        "cannot select it for a test case"
    ) in output
    assert "pass: records / empty records" in output


def test_maintenance_help_matches_rust_command_text(capsys):
    assert cli.main(["stats", "--help"]) == 0
    stats_help = capsys.readouterr().out
    assert stats_help.startswith("Bytes kept out of context, per kind")
    assert "--session" in stats_help and "--events <N>" in stats_help
    assert cli.main(["purge", "--help"]) == 0
    purge_help = capsys.readouterr().out
    assert "-y, --yes" in purge_help and "--older-than <OLDER_THAN>" in purge_help


def test_untrusted_project_profile_script_is_removed_with_diagnostic(
    tmp_path, monkeypatch
):
    from varde_toz.profile import load_profiles

    config = tmp_path / "config"
    config.mkdir()
    project = tmp_path / "project"
    (project / ".varde").mkdir(parents=True)
    (project / ".varde" / "toz-profiles.toml").write_text(
        '[[profile]]\nid="p"\nscript="x"\n'
    )
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))
    profiles, diagnostics = load_profiles(project)
    profile = next(item for item in profiles if item.id == "p")
    assert profile.script is None
    assert (
        diagnostics[0].reason
        == "script dropped: project is not listed in trusted_projects"
    )
