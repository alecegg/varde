import json
from pathlib import Path

from varde_toz.commands.doctor import render_doctor_section
from varde_toz.doctor import DoctorEntry, DoctorSection
from varde_toz.install import retire_owned_files


def _hash(text: str) -> str:
    from blake3 import blake3

    return blake3(text.encode()).hexdigest()[:32]


def _manifest(
    root: Path, files: dict[str, str], name: str = ".varde-toz-install.json"
) -> None:
    (root / name).write_text(
        json.dumps(
            {"version": 1, "files": {key: _hash(value) for key, value in files.items()}}
        )
    )


def test_owned_files_are_removed_and_empty_directories_pruned(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a/one.ts").write_text("shim")
    (tmp_path / "b/two.ts").write_text("shim")
    (tmp_path / "a/foreign.ts").write_text("foreign")
    _manifest(tmp_path, {"a/one.ts": "shim", "b/two.ts": "shim"})

    assert retire_owned_files(tmp_path, ["a/one.ts", "b/two.ts", "c/absent.ts"]) == []
    assert not (tmp_path / "a/one.ts").exists()
    assert not (tmp_path / "b").exists()
    assert not (tmp_path / ".varde-toz-install.json").exists()
    assert (tmp_path / "a/foreign.ts").exists()


def test_edited_file_keeps_all_files_and_manifest(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a/one.ts").write_text("shim")
    (tmp_path / "a/two.ts").write_text("edited")
    _manifest(tmp_path, {"a/one.ts": "shim", "a/two.ts": "shim"})

    assert retire_owned_files(tmp_path, ["a/one.ts", "a/two.ts"]) == [
        tmp_path / "a/two.ts"
    ]
    assert (tmp_path / "a/one.ts").exists()
    assert (tmp_path / ".varde-toz-install.json").exists()


def test_file_without_manifest_entry_is_kept(tmp_path):
    (tmp_path / "one.ts").write_text("shim")
    assert retire_owned_files(tmp_path, ["one.ts"]) == [tmp_path / "one.ts"]


def test_legacy_manifest_name_is_supported(tmp_path):
    (tmp_path / "one.ts").write_text("shim")
    _manifest(tmp_path, {"one.ts": "shim"}, ".toz-install.json")
    assert retire_owned_files(tmp_path, ["one.ts"]) == []
    assert not (tmp_path / "one.ts").exists()


def test_missing_files_leave_manifest_alone(tmp_path):
    _manifest(tmp_path, {"missing.ts": "shim"})
    assert retire_owned_files(tmp_path, ["missing.ts"]) == []
    assert not (tmp_path / ".varde-toz-install.json").exists()


def test_malformed_manifest_does_not_claim_files(tmp_path):
    (tmp_path / "one.ts").write_text("shim")
    (tmp_path / ".varde-toz-install.json").write_text("not json")
    assert retire_owned_files(tmp_path, ["one.ts"]) == [tmp_path / "one.ts"]


def test_doctor_section_text_and_json_are_host_supplied():
    section = DoctorSection(
        "hooks",
        [DoctorEntry("hook claude SessionStart: current", {"state": "current"})],
    )
    assert render_doctor_section(section) == (
        "hooks",
        ["hook claude SessionStart: current"],
        [{"state": "current"}],
    )
