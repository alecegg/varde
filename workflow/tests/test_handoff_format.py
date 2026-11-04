from __future__ import annotations

import pytest
from varde_workflow.handoff_format import validate


def handoff() -> str:
    return """Summary: Continue the task
Goal:
Finish the requested work.
Context:
The branch contains the implementation.
State:
- Tests pass.
Next:
1. Review the diff.
Open:
- None.
Reading list:
- README.md
Pointers:
- mem-123
- [global] parser contract — source of truth
- project pattern — useful example
Do not redo:
- Existing implementation.
"""


def test_valid_handoff_parses_candidate_and_defaults_untagged_candidate() -> None:
    result = validate(handoff(), lambda path: path == "README.md")

    assert result.errors == []
    assert result.warnings == []
    assert result.summary == "Continue the task"
    assert result.candidates == [
        {"tag": "global", "text": "parser contract", "why": "source of truth"},
        {"tag": "project", "text": "project pattern", "why": "useful example"},
    ]


@pytest.mark.parametrize(
    ("old", "section"),
    [
        ("Summary: Continue the task\n", "Summary:"),
        ("Goal:\nFinish the requested work.\n", "Goal:"),
    ],
)
def test_missing_required_section_names_section(old: str, section: str) -> None:
    result = validate(handoff().replace(old, ""), lambda _: True)

    assert any(section in error for error in result.errors)


def test_section_order_error_names_section() -> None:
    text = handoff().replace(
        "Goal:\nFinish the requested work.\nContext:",
        "Context:\nThe branch contains the implementation.\nGoal:",
    )

    result = validate(text, lambda _: True)

    assert any("Goal:" in error and "order" in error for error in result.errors)


def test_limits_name_the_rejected_section() -> None:
    long_context = "word " * 251
    result = validate(
        handoff().replace("The branch contains the implementation.", long_context),
        lambda _: True,
    )

    assert any("Context:" in error and "250" in error for error in result.errors)


def test_nonexistent_reading_path_warns_and_malformed_tag_fails() -> None:
    text = (
        handoff()
        .replace("README.md", "missing.md")
        .replace(
            "[global] parser contract — source of truth",
            "[bad] parser contract — source of truth",
        )
    )

    result = validate(text, lambda _: False)

    assert any("Reading list:" in warning for warning in result.warnings)
    assert any("Pointers:" in error for error in result.errors)


@pytest.mark.parametrize(
    ("old", "replacement", "section"),
    [
        ("Continue the task", "x" * 121, "Summary:"),
        ("- Tests pass.\n", "- 1\n- 2\n- 3\n- 4\n- 5\n- 6\n", "State:"),
        ("1. Review the diff.\n", "1. a\n2. b\n3. c\n4. d\n", "Next:"),
        ("- None.\n", "- 1\n- 2\n- 3\n- 4\n", "Open:"),
        ("- README.md\n", "".join(f"- file{i}\n" for i in range(9)), "Reading list:"),
        (
            "- Existing implementation.\n",
            "".join(f"- item{i}\n" for i in range(6)),
            "Do not redo:",
        ),
        (
            "- mem-123\n",
            "".join(f"- item{i} — why\n" for i in range(6)),
            "Pointers:",
        ),
    ],
)
def test_section_limits_are_rejected(old: str, replacement: str, section: str) -> None:
    result = validate(handoff().replace(old, replacement), lambda _: True)

    assert any(section in error for error in result.errors)


def test_total_handoff_limits_name_a_section() -> None:
    words = "word " * 701
    result = validate(
        handoff().replace("Finish the requested work.", words), lambda _: True
    )
    characters = "x" * 5001
    char_result = validate(
        handoff().replace("The branch contains the implementation.", characters),
        lambda _: True,
    )

    assert any("Summary:" in error and "700 words" in error for error in result.errors)
    assert any(
        "Summary:" in error and "5000 characters" in error
        for error in char_result.errors
    )
