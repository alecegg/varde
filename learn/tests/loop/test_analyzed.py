from varde_learn.loop.analyzed import mark, seen
from varde_learn.loop.analyzed import read_all as list_analyzed


def test_mark_and_seen_are_separated_by_harness(tmp_path):
    mark(tmp_path, "codex", "same", "2026-10-18T12:00:00Z", "first")
    mark(tmp_path, "claude", "same", "2026-10-18T12:01:00Z", "second")

    assert seen(tmp_path, "codex") == {"same"}
    assert seen(tmp_path, "claude") == {"same"}
    assert list_analyzed(tmp_path)[0]["metrics"] == {}
    assert list_analyzed(tmp_path)[0]["friction_added"] == []


def test_repeated_mark_uses_latest_row(tmp_path):
    mark(tmp_path, "codex", "s1", "earlier", "old")
    mark(tmp_path, "codex", "s1", "later", "new")

    rows = list_analyzed(tmp_path)
    assert len(rows) == 1
    assert rows[0]["analyzed_at"] == "later"
    assert rows[0]["summary"] == "new"


def test_truncated_last_line_is_ignored(tmp_path):
    mark(tmp_path, "codex", "complete", "now", "ok")
    with (tmp_path / "analyzed.jsonl").open("a") as ledger:
        ledger.write('{"session":"partial"')

    assert seen(tmp_path, "codex") == {"complete"}


def test_list_returns_ledger_fields(tmp_path):
    mark(tmp_path, "codex", "s1", "now", "summary")

    row = list_analyzed(tmp_path)[0]
    assert row["session"] == "s1"
    assert row["harness"] == "codex"
    assert row["analyzed_at"] == "now"
    assert row["metrics"] == {}
    assert row["friction_added"] == []


def test_mark_after_truncated_line_starts_a_new_parseable_row(tmp_path):
    (tmp_path / "analyzed.jsonl").write_text('{"session":"broken"', encoding="utf-8")
    mark(
        tmp_path,
        "codex",
        "s2",
        "now",
        "summary",
        {"input_tokens": 9},
        friction_added=["retry_loop"],
    )
    row = list_analyzed(tmp_path)[0]
    assert row["session"] == "s2"
    assert row["metrics"] == {"input_tokens": 9}
    assert row["friction_added"] == ["retry_loop"]
