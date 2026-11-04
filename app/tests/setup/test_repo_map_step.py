from varde.setup.repo_map_step import (
    block_text,
    default_modules,
    merge_block,
    plan_step,
)

START = "<!-- varde-map:start -->"
END = "<!-- varde-map:end -->"


def test_block_text_is_short_pointer() -> None:
    text = block_text()
    lines = text.splitlines()
    assert lines[0] == START and lines[-1] == END
    assert len(lines) <= 5
    assert "docs/repo-map/README.md" in text
    assert "varde map packs status --check" in text
    assert "build --stale" in text


def test_merge_creates_when_none() -> None:
    assert merge_block(None) == block_text() + "\n"


def test_merge_appends_after_blank_line() -> None:
    merged = merge_block("# Title\n\nbody\n")
    assert merged.startswith("# Title\n\nbody\n\n" + START)
    assert merged.endswith(END + "\n")


def test_merge_replaces_between_markers() -> None:
    existing = f"before\n{START}\nSTALE\n{END}\nafter\n"
    merged = merge_block(existing)
    assert "STALE" not in merged
    assert merged.startswith("before\n") and merged.endswith("\nafter\n")
    assert merged.count(START) == 1


def test_merge_is_idempotent() -> None:
    once = merge_block("# T\n")
    assert merge_block(once) == once
    assert merge_block(merge_block(None)) == merge_block(None)


def test_default_modules_filters_and_sorts() -> None:
    tracked = [
        "README.md",
        "app/src/a.py",
        "core/b.py",
        ".github/x.py",
        "vendor/v.py",
        "build/o.py",
        "docs/d.py",
        "tests/t.py",
        "node_modules/n.js",
        "core/c.py",
    ]
    assert default_modules(tracked) == ["app", "core"]


def test_default_modules_ignores_non_source_and_caps() -> None:
    assert default_modules(["notes/a.txt"]) == []
    many = [f"m{i:02d}/a.py" for i in range(30)]
    assert len(default_modules(many)) == 20


def test_plan_step() -> None:
    assert plan_step(True, False, False) == ["edit-agents-md", "build-packs"]
    assert plan_step(True, True, False) == ["edit-agents-md"]
    assert plan_step(True, True, True) == ["edit-agents-md"]
    assert plan_step(False, False, False) == []
