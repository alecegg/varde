"""Page quality warnings: each rule on its fixture, silence on a clean page."""

from pathlib import Path

from varde_learn.docs.pages import cli as pages_cli
from varde_learn.docs.pages.blocks.quality import MAX_BARE_RUN, quality_warnings

FIXTURES = Path(__file__).parent / "fixtures" / "quality"


def rules(name: str, task_ids: tuple[str, ...] = ()) -> list[str]:
    text = (FIXTURES / name).read_text(encoding="utf-8")
    return [w.rule for w in quality_warnings(text, task_ids)]


def test_clean_page_is_silent() -> None:
    assert rules("clean.md") == []


def test_first_block_not_prose() -> None:
    warnings = quality_warnings((FIXTURES / "first-block.md").read_text())
    assert [(w.rule, w.line) for w in warnings] == [("quality-first-block", 4)]


def test_empty_and_prose_first_pages_are_silent() -> None:
    assert quality_warnings("") == []
    assert quality_warnings("# T\n\n## S\n\nText.\n") == []


def test_stale_reference_ignores_code() -> None:
    warnings = quality_warnings((FIXTURES / "stale.md").read_text())
    assert [(w.rule, w.line) for w in warnings] == [("quality-stale-reference", 3)]


def test_stale_phrases_all_fire() -> None:
    for phrase in ("see above", "As Mentioned Earlier", "as noted earlier"):
        assert rules_of(f"# T\n\nFine. {phrase}.\n") == ["quality-stale-reference"]


def rules_of(text: str) -> list[str]:
    return [w.rule for w in quality_warnings(text)]


def test_open_choice_before_last_heading() -> None:
    warnings = quality_warnings((FIXTURES / "open-choice.md").read_text())
    assert [(w.rule, w.line) for w in warnings] == [("quality-open-choice", 6)]


def test_open_choice_in_last_section_is_silent() -> None:
    assert rules("clean.md") == []
    assert rules_of("Text.\n\n```ui\nf = form(fields: [])\n```\n") == []


def test_covers_resolution() -> None:
    warnings = quality_warnings((FIXTURES / "covers.md").read_text(), ("task-a",))
    assert [w.rule for w in warnings] == ["quality-covers"]
    assert "'missing'" in warnings[0].message


def test_covers_task_id_unknown_without_tasks() -> None:
    messages = [
        w.message for w in quality_warnings((FIXTURES / "covers.md").read_text())
    ]
    assert any("'task-a'" in m for m in messages)


def test_bare_run_boundary() -> None:
    assert MAX_BARE_RUN == 3
    text = (FIXTURES / "bare-run.md").read_text()
    assert rules("bare-run.md") == ["quality-bare-run"]
    three = "\n".join(
        line for line in text.splitlines() if not line.startswith(("t4", "t5"))
    )
    assert rules_of(three) == []


def test_bare_run_only_on_recap() -> None:
    text = (FIXTURES / "bare-run.md").read_text().replace("type: recap", "type: plan")
    assert rules_of(text) == []


def test_warning_only_page_exits_zero(tmp_path: Path, capsys) -> None:
    doc = tmp_path / "page.md"
    doc.write_text((FIXTURES / "first-block.md").read_text())
    assert pages_cli.check_blocks(doc) == 0
    assert f"{doc}:4: warning: quality-first-block:" in capsys.readouterr().out


def test_error_plus_warning_exits_one_with_error_first(tmp_path: Path, capsys) -> None:
    doc = tmp_path / "page.md"
    doc.write_text("# T\n\n```ui\nbad = nope(x: 1)\n```\n")
    assert pages_cli.check_blocks(doc) == 1
    lines = capsys.readouterr().out.splitlines()
    assert ": warning: " not in lines[0]
    assert "warning: quality-first-block" in lines[-1]


def test_task_ids_come_from_the_tasks_folder(tmp_path: Path, capsys) -> None:
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "task-a.md").write_text("x")
    doc = tmp_path / "plan.md"
    doc.write_text((FIXTURES / "covers.md").read_text())
    pages_cli.check_blocks(doc)
    out = capsys.readouterr().out
    assert "'missing'" in out
    assert "'task-a'" not in out


def test_normal_widget_fixture_has_no_caption_repeating_the_included_heading() -> None:
    from pathlib import Path as _P

    text = (_P(__file__).parent / "fixtures" / "widgets" / "normal.md").read_text()
    assert 'title: "Criteria"' not in text
