from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from varde_learn.knowledge import memory
from varde_workflow import cli
from varde_workflow.commands.plan_answer import answer_question, replace_body_bytes
from varde_workflow.commands.status import count_open_questions


def _plan(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "plans" / "sample" / "plan.md"
    path.parent.mkdir(parents=True)
    path.write_text(f"---\ntype: plan\nid: sample\n---\n{body}", encoding="utf-8")
    return path


def test_answer_question_removes_nested_bullet_and_records_answer(
    tmp_path: Path,
) -> None:
    path = _plan(
        tmp_path,
        "## Decisions so far\n\n## Open Questions\n- Which route?\n"
        "  - Keep both options\n  - Another note\n- Next question?\n",
    )

    assert (
        cli.run(
            [
                "plan",
                "answer",
                str(path),
                "--question",
                "1",
                "--answer",
                "Use A\n## Heading",
                "--json",
            ]
        )
        == 0
    )
    result = path.read_text(encoding="utf-8")
    assert "- Which route?\n" not in result
    assert "Keep both options" not in result
    assert "- Next question?" in result
    assert "Which route? → Use A ## Heading (" in result
    assert count_open_questions(result) == 1


def test_answer_question_creates_decisions_and_restores_empty_marker(
    tmp_path: Path,
) -> None:
    path = _plan(tmp_path, "## Open Questions\n- Is this okay?\n")
    assert (
        cli.run(
            [
                "plan",
                "answer",
                str(path),
                "--question",
                "Is this okay?",
                "--answer",
                "Yes",
            ]
        )
        == 0
    )
    result = path.read_text(encoding="utf-8")
    assert "## Decisions so far\n\n- Is this okay? → Yes (" in result
    assert "## Open Questions\n\nn/a — no open questions\n\n" in result


def test_answer_question_ignores_fenced_heading_and_is_repeatable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _plan(
        tmp_path, "```md\n## Open Questions\n- fake\n```\n## Open Questions\n- real\n"
    )
    assert (
        cli.run(["plan", "answer", str(path), "--question", "real", "--answer", "Done"])
        == 0
    )
    answered = path.read_text(encoding="utf-8")
    capsys.readouterr()
    assert (
        cli.run(["plan", "answer", str(path), "--question", "real", "--answer", "Done"])
        == 0
    )
    assert path.read_text(encoding="utf-8") == answered
    assert "Question already answered in" in capsys.readouterr().out


def test_answer_question_json_reports_noop(tmp_path: Path, capsys):
    path = _plan(
        tmp_path,
        "## Decisions so far\n\n- Already answered? → Yes (2026-10-23)\n\n"
        "## Open Questions\n- Another question?\n",
    )
    assert (
        cli.run(
            [
                "plan",
                "answer",
                str(path),
                "--question",
                "Already answered?",
                "--answer",
                "Yes",
                "--json",
            ]
        )
        == 0
    )
    assert '"updated":false' in capsys.readouterr().out


def test_answer_question_digit_exact_match_is_already_recorded():
    text = "## Decisions so far\n\n- 1 → Yes (2026-10-23)\n\n## Open Questions\n- 1\n"

    assert answer_question(text, "1", "Again", "2026-10-24") == text


def test_answer_question_resolves_bare_plan_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _plan(tmp_path, "## Open Questions\n- real\n")
    monkeypatch.setattr(
        memory.MemoryPaths,
        "resolve",
        lambda _path: SimpleNamespace(working=SimpleNamespace(path=tmp_path)),
    )
    assert (
        cli.run(["plan", "answer", "sample", "--question", "real", "--answer", "Done"])
        == 0
    )
    assert "real → Done" in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("question", ["missing", "Repeated"])
def test_answer_question_rejects_missing_or_ambiguous(
    tmp_path: Path, question: str, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _plan(tmp_path, "## Open Questions\n- Repeated\n- Repeated\n")
    assert (
        cli.run(["plan", "answer", str(path), "--question", question, "--answer", "x"])
        == 1
    )
    error = capsys.readouterr().err
    assert "no open question" in error or "matches several" in error


def test_pure_transform_collapses_answer_and_counts_questions() -> None:
    result = answer_question(
        "## Open Questions\n- First?\n- Second?\n", "First?", "A\n## B", "2026-10-23"
    )
    assert "First? → A ## B (2026-10-23)" in result
    assert count_open_questions(result) == 1


def test_index_argument_always_answers_the_current_indexed_question(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _plan(tmp_path, "## Decisions so far\n\n## Open Questions\n- Q1\n- Q2\n")
    args = ["plan", "answer", str(path), "--question", "1", "--answer", "x"]

    assert cli.run(args) == 0
    first_result = path.read_text(encoding="utf-8")
    capsys.readouterr()
    assert cli.run(args) == 0
    second_result = path.read_text(encoding="utf-8")
    capsys.readouterr()

    assert "- Q1 → x" in first_result
    assert "- Q2 → x" in second_result
    assert count_open_questions(second_result) == 0
    assert cli.run(args) == 1
    assert "Answered question" not in capsys.readouterr().out


def test_index_answer_with_previous_same_answer_still_writes_question(
    tmp_path: Path,
) -> None:
    path = _plan(
        tmp_path,
        "## Decisions so far\n\n- Earlier → yes (2026-10-22)\n\n"
        "## Open Questions\n- Q1\n",
    )

    assert (
        cli.run(["plan", "answer", str(path), "--question", "1", "--answer", "yes"])
        == 0
    )

    result = path.read_text(encoding="utf-8")
    assert "- Q1 → yes (" in result
    assert count_open_questions(result) == 0


def test_empty_decisions_section_keeps_blank_line_after_heading() -> None:
    result = answer_question(
        "## Decisions so far\n\n## Open Questions\n- Q1\n",
        "Q1",
        "x",
        "2026-10-23",
    )

    assert "## Decisions so far\n\n- Q1 → x (2026-10-23)" in result


def test_fenced_bullets_in_open_questions_are_ignored() -> None:
    body = "## Open Questions\n- Q1\n```md\n- fake\n```\n"

    assert count_open_questions(body) == 1
    with pytest.raises(ValueError, match="no open question"):
        answer_question(body, "fake", "x", "2026-10-23")


def test_answering_last_question_preserves_other_section_content() -> None:
    body = (
        "## Open Questions\n\nIntro prose.\n\n- Q1\n\n"
        "### Notes\nkeep me\n\n## Assumptions\n"
    )

    result = answer_question(body, "Q1", "x", "2026-10-23")

    assert "n/a — no open questions" in result
    assert "Intro prose." in result
    assert "### Notes\nkeep me" in result
    assert "## Assumptions" in result


def test_decisions_stay_together_and_keep_template_spacing() -> None:
    result = answer_question(
        "## Decisions so far\n\n- Earlier → yes (2026-10-22)\n\n"
        "## Open Questions\n- Q1\n",
        "Q1",
        "x",
        "2026-10-23",
    )

    assert (
        "- Earlier → yes (2026-10-22)\n- Q1 → x (2026-10-23)\n\n## Open Questions\n\n"
    ) in result
    assert "## Open Questions\n\nn/a — no open questions\n\n" in result


def test_numeric_bullet_text_matches_as_text() -> None:
    result = answer_question(
        "## Decisions so far\n\n- Earlier → x (2026-10-22)\n\n"
        "## Open Questions\n- Q1\n- 1\n",
        "1",
        "x",
        "2026-10-23",
    )

    assert "- Q1\n" in result
    assert "- 1 → x" in result


def test_replace_body_uses_suffix_length_when_body_occurs_earlier() -> None:
    body = b"same body"
    raw = b"frontmatter same body\n---\nsame body"

    assert (
        replace_body_bytes(raw, body, b"changed")
        == b"frontmatter same body\n---\nchanged"
    )


def test_nested_plan_id_falls_back_to_directory_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = tmp_path / "plans" / "parent" / "children" / "nested" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        "---\ntype: plan\nid: null\n---\n## Open Questions\n- nested question\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        memory.MemoryPaths,
        "resolve",
        lambda _path: SimpleNamespace(working=SimpleNamespace(path=tmp_path)),
    )

    assert (
        cli.run(
            [
                "plan",
                "answer",
                "nested",
                "--question",
                "nested question",
                "--answer",
                "Done",
            ]
        )
        == 0
    )
    assert "nested question → Done" in plan.read_text(encoding="utf-8")
