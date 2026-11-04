from __future__ import annotations

from pathlib import Path

from varde_runner.evidence import resolve_evidence_path


def test_evidence_path_allowlist_checks_file_and_root(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    note = root / "decision.md"
    note.write_text("# Decision\n", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    hidden = root / ".secret"
    hidden.mkdir()
    hidden_file = hidden / "decision.txt"
    hidden_file.write_text("hidden", encoding="utf-8")
    bad_extension = root / "decision.json"
    bad_extension.write_text("{}", encoding="utf-8")
    oversized = root / "large.txt"
    oversized.touch()
    oversized.write_bytes(b"x" * (5 * 1024 * 1024 + 1))
    link = root / "link.txt"
    link.symlink_to(outside)

    roots = (root,)
    assert resolve_evidence_path(str(note), roots) == note
    assert resolve_evidence_path(str(root / ".." / "outside.txt"), roots) is None
    assert resolve_evidence_path(str(link), roots) is None
    assert resolve_evidence_path(str(hidden_file), roots) is None
    assert resolve_evidence_path(str(oversized), roots) is None
    assert resolve_evidence_path(str(bad_extension), roots) is None


def test_evidence_path_allows_symlinked_ancestors_but_rejects_links_inside_root(
    tmp_path: Path,
) -> None:
    actual_root = tmp_path / "actual" / "plans"
    actual_root.mkdir(parents=True)
    note = actual_root / "decision.md"
    note.write_text("# Decision", encoding="utf-8")
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path / "actual", target_is_directory=True)
    aliased_root = alias / "plans"
    assert (
        resolve_evidence_path(str(alias / "plans" / "decision.md"), (aliased_root,))
        == note
    )

    link = aliased_root / "linked.md"
    link.symlink_to(note)
    assert resolve_evidence_path(str(link), (aliased_root,)) is None
