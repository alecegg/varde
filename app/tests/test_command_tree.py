"""The single `varde learn <concern> <verb>` command tree stays short and complete.

Each task that registers a new `varde learn ...` path adds it to EXPECTED_PATHS in
the same change.
"""

from __future__ import annotations

import re

import pytest
from varde.routes import ROUTES
from varde_learn.module import register

MAX_PATH_WORDS = 3  # words after `varde`
MAX_GROUP_HELP_LINES = 40

EXPECTED_PATHS = {
    ("learn", "check"),
    ("learn", "how"),
    ("learn", "measure"),
    ("learn", "tools"),
    ("learn", "sessions", "show"),
    ("learn", "sessions", "summary"),
    ("learn", "sessions", "capture"),
    ("learn", "sessions", "sweep"),
    ("learn", "sessions", "run"),
    ("learn", "sessions", "calls"),
    ("learn", "sessions", "fire"),
    ("learn", "friction", "list"),
    ("learn", "friction", "add"),
    ("learn", "friction", "show"),
    ("learn", "friction", "set-status"),
    ("learn", "friction", "export"),
    ("learn", "friction", "import"),
    ("learn", "friction", "adopt"),
    ("learn", "friction", "recurrence"),
    ("learn", "knowledge", "create"),
    ("learn", "knowledge", "show"),
    ("learn", "knowledge", "update"),
    ("learn", "knowledge", "delete"),
    ("learn", "knowledge", "set-field"),
    ("learn", "knowledge", "map"),
    ("learn", "knowledge", "search"),
    ("learn", "knowledge", "lint"),
    ("learn", "docs", "serve"),
    ("learn", "docs", "watch"),
    ("learn", "docs", "comments"),
    ("learn", "docs", "reply"),
    ("learn", "docs", "blocks"),
    ("learn", "docs", "recap"),
    ("learn", "docs", "build"),
    ("learn", "docs", "spec"),
    ("learn", "skills", "demand"),
    *(
        ("learn", "skills", verb)
        for verb in (
            "candidates",
            "extract",
            "reset",
            "accept",
            "reject",
            "report",
            "fill",
            "updates",
        )
    ),
    *(
        ("learn", "memory", verb)
        for verb in (
            "add",
            "list",
            "show",
            "retire",
            "reset",
            "surface",
            "promote",
            "pull",
            "migrate",
            "search",
            "update",
            "set-field",
            "delete",
            "map",
            "lint",
        )
    ),
}

_COMMAND_LINE = re.compile(r"^  ([a-z][a-z-]*)(?:\s|$)")


def _help(path: tuple[str, ...], capsys: pytest.CaptureFixture[str]) -> str:
    capsys.readouterr()
    code = register().run([*path[1:], "--help"])
    assert code == 0, f"varde {' '.join(path)} --help exited {code}"
    return capsys.readouterr().out


def _children(text: str) -> list[str]:
    if "\nCommands:\n" not in text:
        return []
    block = text.split("\nCommands:\n", 1)[1].split("\n\n", 1)[0]
    matches = (_COMMAND_LINE.match(line) for line in block.splitlines())
    names = [m.group(1) for m in matches if m]
    return [name for name in names if name != "help"]


def _walk(capsys: pytest.CaptureFixture[str]) -> tuple[set[tuple[str, ...]], dict]:
    paths: set[tuple[str, ...]] = set()
    group_help: dict[tuple[str, ...], str] = {}
    pending: list[tuple[str, ...]] = [("learn",)]
    while pending:
        group = pending.pop()
        text = _help(group, capsys)
        group_help[group] = text
        for name in _children(text):
            path = (*group, name)
            if _children(_help(path, capsys)):
                pending.append(path)
            else:
                paths.add(path)
    return paths, group_help


def test_walked_paths_equal_expected(capsys) -> None:
    paths, _ = _walk(capsys)
    assert paths == EXPECTED_PATHS
    assert ("learn", "skills", "demand") in paths


def test_no_removed_paths_or_long_paths(capsys) -> None:
    paths, _ = _walk(capsys)
    assert all(len(path) <= MAX_PATH_WORDS for path in paths)
    assert not any(path[-1] == "how-report" for path in paths)
    assert not any(path[:2] == ("learn", "measure") and len(path) > 2 for path in paths)


def test_no_route_names_doc_or_knowledge_group() -> None:
    assert not [r.path for r in ROUTES if r.path[0] in {"doc", "knowledge"}]


def test_group_help_fits_one_screen(capsys) -> None:
    _, group_help = _walk(capsys)
    lines = {group: text.count("\n") for group, text in group_help.items()}
    long = {g: n for g, n in lines.items() if n > MAX_GROUP_HELP_LINES}
    assert not long


def test_every_group_names_its_verbs(capsys) -> None:
    _, group_help = _walk(capsys)
    assert {g[1] for g in group_help if len(g) == 2} >= {
        "sessions",
        "friction",
        "knowledge",
        "docs",
        "skills",
    }
