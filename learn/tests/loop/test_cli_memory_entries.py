from __future__ import annotations

import json

import pytest
from test_cli_memory import add_json, call
from varde_learn.memory import store


@pytest.fixture(autouse=True)
def memory_env(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_MEMORY_DIR", str(tmp_path / "mem"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.chdir(tmp_path)
    return tmp_path / "mem"


def show_version(entry_id: str) -> str:
    code, out, err = call("show", entry_id, "--json")
    assert code == 0, err
    return json.loads(out)["data"]["version"]


def test_search_finds_added_entry_and_filters_scope() -> None:
    first = add_json("--scope", "global", "--text", "postgres tuning notes")["id"]
    add_json("--scope", "skill", "--key", "alpha", "--text", "postgres in a skill")
    code, out, _ = call("search", "--text", "postgres", "--json")
    hits = json.loads(out)["data"]["hits"]
    assert code == 0 and len(hits) == 2
    code, out, _ = call("search", "--text", "postgres", "--scope", "global", "--json")
    assert [h["id"] for h in json.loads(out)["data"]["hits"]] == [first]


def test_search_field_filter_and_bad_field() -> None:
    add_json("--scope", "global", "--text", "postgres notes")
    code, out, _ = call("search", "--text", "postgres", "--field", "type=decision")
    assert code == 0 and out == ""
    code, _, err = call("search", "--text", "postgres", "--field", "novalue")
    assert code == 2 and "key=value" in err


def test_set_field_updates_and_conflict_exits_1() -> None:
    entry_id = add_json("--scope", "global", "--text", "note")["id"]
    version = show_version(entry_id)
    code, _, err = call(
        "set-field", entry_id, "type", "decision", "--expected-version", version
    )
    assert code == 0, err
    code, _, err = call(
        "set-field", entry_id, "type", "pattern", "--expected-version", version
    )
    assert code == 1 and "conflict" in err
    code, out, _ = call("search", "--text", "note", "--field", "type=decision")
    assert entry_id in out


def test_update_text_from_file_and_inline(tmp_path) -> None:
    entry_id = add_json("--scope", "global", "--text", "old words")["id"]
    path = tmp_path / "new.md"
    path.write_text("fresh words\n", encoding="utf-8")
    code, _, err = call(
        "update",
        entry_id,
        "--expected-version",
        show_version(entry_id),
        "--file",
        str(path),
    )
    assert code == 0, err
    code, out, _ = call("show", entry_id)
    assert "fresh words" in out
    code, _, err = call(
        "update",
        entry_id,
        "--expected-version",
        show_version(entry_id),
        "--text",
        "api_key = abcdefgh12345",
    )
    assert code == 2 and "secret" in err


def test_update_missing_entry_exits_1() -> None:
    code, _, err = call("update", "nope", "--expected-version", "x", "--text", "t")
    assert code == 1 and "not_found" in err


def test_delete_reports_inbound_links(memory_env) -> None:
    target = add_json("--scope", "global", "--text", "target")["id"]
    add_json("--scope", "global", "--text", f"see [it]({target}.md)")
    code, out, err = call("delete", target)
    assert code == 0, err
    assert "linked from" in out
    assert not (memory_env / "global" / f"{target}.md").exists()


def test_map_prints_and_writes_only_on_request(memory_env, tmp_path) -> None:
    entry_id = add_json("--scope", "global", "--text", "mapped note")["id"]
    code, out, _ = call("map")
    assert code == 0 and entry_id in out
    destination = tmp_path / "out" / "MAP.md"
    assert not destination.exists()
    code, _, _ = call("map", "--write", str(destination))
    assert code == 0 and entry_id in destination.read_text()


def test_lint_reports_unreadable_and_orphan(memory_env) -> None:
    add_json("--scope", "global", "--text", "alone")
    (memory_env / "global" / "bad.md").write_text("no front matter", encoding="utf-8")
    code, out, _ = call("lint", "--json")
    envelope = json.loads(out)
    data = envelope["data"]["error"]["details"]
    codes = {i["code"] for i in data["issues"]}
    assert code == 2 and envelope["ok"] is False
    assert {"unreadable", "orphan"} <= codes
    assert data["errors"] >= 1
    assert store.load_report(memory_env)[0]


def test_lint_exits_2_on_errors_and_0_when_clean(memory_env) -> None:
    add_json("--scope", "global", "--text", "alone")
    code, out, _ = call("lint")
    assert code == 0 and "error" not in out
    (memory_env / "global" / "bad.md").write_text("no front matter", encoding="utf-8")
    code, out, _ = call("lint")
    assert code == 2 and "unreadable" in out


def test_search_survives_a_short_knowledge_source() -> None:
    add_json("--scope", "global", "--text", "zebra facts", "--source", "knowledge:foo")
    code, out, err = call("search", "--text", "zebra", "--json")
    assert code == 0, err
    assert len(json.loads(out)["data"]["hits"]) == 1


def test_add_rejects_a_long_surfaced_summary_unless_not_surfaced() -> None:
    long_text = "x" * 95 + "\n\nbody"
    code, _, err = call("add", "--scope", "global", "--text", long_text)
    assert code == 2 and "80" in err
    code, out, err = call(
        "add", "--scope", "global", "--no-surface", "--text", long_text, "--json"
    )
    assert code == 0, err
    data = json.loads(out)["data"]
    assert data["version"] == show_version(data["id"])


def test_list_expired_reports_without_deleting(memory_env) -> None:
    keep = add_json("--scope", "global", "--text", "kept")["id"]
    old = add_json("--scope", "global", "--text", "stale")["id"]
    code, _, err = call(
        "set-field",
        old,
        "valid_until",
        "2020-01-01",
        "--expected-version",
        show_version(old),
    )
    assert code == 0, err
    code, out, _ = call("list", "--expired")
    assert old in out and keep not in out
    assert (memory_env / "global" / f"{old}.md").exists()


def test_list_scope_counts_go_to_stderr(capsys) -> None:
    add_json("--scope", "global", "--text", "one")
    capsys.readouterr()
    code, out, _ = call("list")
    assert code == 0 and "global: 1" not in out
    assert "global: 1" in capsys.readouterr().err
