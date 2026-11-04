import os

from varde_data.version import Cursor, Version, files_version


def test_files_version_detects_same_size_rewrite_with_pinned_mtime(tmp_path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("one")
    original = source.stat().st_mtime_ns
    before = files_version([source])

    source.write_text("two")
    os.utime(source, ns=(original, original))

    assert files_version([source]) != before


def test_files_version_detects_added_and_removed_set_members(tmp_path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("data")
    before = files_version([source], file_set_root=tmp_path)

    added = tmp_path / "new.txt"
    added.write_text("new")
    after_add = files_version([source], file_set_root=tmp_path)
    added.unlink()

    assert after_add != before
    assert files_version([source], file_set_root=tmp_path) == before


def test_missing_files_are_included_in_token() -> None:
    assert files_version(["missing-a"]) != files_version(["missing-b"])


def test_version_is_hashable_and_equality_only() -> None:
    assert Version("same") == Version("same")
    assert hash(Version("same")) == hash(Version("same"))
    assert Cursor("a") < Cursor("b")
