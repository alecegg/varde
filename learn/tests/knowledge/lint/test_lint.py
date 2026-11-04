from pathlib import Path

import pytest
from varde_learn.knowledge.lint import (
    CheckKind,
    LintError,
    LintOptions,
    Severity,
    lint,
    lint_with_options,
)


def _concept(body: str) -> str:
    return f"---\ntype: decision\n---\n{body}"


def _write(root: Path, name: str, body: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_lint_checks_links_orphans_and_malformed_files(tmp_path: Path) -> None:
    _write(tmp_path, "a.md", _concept("[b](b.md) [missing](/missing.md)"))
    _write(tmp_path, "b.md", _concept("No incoming link."))
    _write(tmp_path, "bad.md", "---\n: invalid yaml\n---\n")
    report = lint(tmp_path)
    assert [(issue.check_kind, issue.severity) for issue in report.issues] == [
        (CheckKind.MALFORMED_CONCEPT, Severity.ERROR),
        (CheckKind.BROKEN_LINK, Severity.ERROR),
        (CheckKind.ORPHANED_CONCEPT, Severity.WARNING),
    ]


def test_index_links_count_and_missing_index_is_optional(tmp_path: Path) -> None:
    _write(tmp_path, "index.md", "[a](nested/a.md)")
    _write(tmp_path, "nested/a.md", _concept("No links."))
    assert lint(tmp_path).issues == []
    report = lint_with_options(tmp_path, LintOptions(require_index=True))
    assert [(issue.check_kind, issue.path.name) for issue in report.issues] == [
        (CheckKind.MISSING_INDEX, "nested")
    ]


def test_walk_skips_hidden_artifact_and_reserved_files(tmp_path: Path) -> None:
    _write(tmp_path, "a.md", _concept("[b](b.md)"))
    _write(tmp_path, "b.md", _concept("[a](a.md)"))
    _write(tmp_path, "README.md", "---\n: invalid yaml\n---\n")
    _write(tmp_path, ".hidden/bad.md", "---\n: invalid yaml\n---\n")
    _write(tmp_path, "target/bad.md", "---\n: invalid yaml\n---\n")
    assert lint(tmp_path).issues == []


def test_missing_root_raises_typed_error(tmp_path: Path) -> None:
    with pytest.raises(LintError):
        lint(tmp_path / "missing")
