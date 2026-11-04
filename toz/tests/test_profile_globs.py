from __future__ import annotations

import itertools
from pathlib import Path

import pytest
from varde_toz.capture import CaptureInput, capture
from varde_toz.profile import (
    Profile,
    Scope,
    find_match,
    glob_to_regex,
    load_file,
    load_profiles,
)
from varde_toz.strategies import chunk_with_profile


@pytest.mark.parametrize(
    ("glob", "yes", "no"),
    [
        ("cargo test*", "cargo test --workspace", "cargo build"),
        ("*.json", "config.json", "config.toml"),
        ("file?.txt", "file1.txt", "file12.txt"),
        ("[ab]ook", "book", "cook"),
        ("[!a]ook", "book", "aook"),
        (r"a+b", "a+b", "aaab"),
    ],
)
def test_glob_matches(glob: str, yes: str, no: str) -> None:
    matcher = glob_to_regex(glob)
    assert matcher.fullmatch(yes)
    assert not matcher.fullmatch(no)


def test_unterminated_class_fails() -> None:
    with pytest.raises(ValueError, match="unterminated"):
        glob_to_regex("bad[glob")


def test_malformed_glob_entry_is_diagnosed(tmp_path: Path) -> None:
    path = tmp_path / "profiles.toml"
    path.write_text('[[profile]]\nid="bad"\nmatch={command="cargo [test*"}\n')
    profiles, diagnostics = load_file(path)
    assert not any(profile.id == "bad" for profile in profiles)
    assert len(diagnostics) == 1
    assert diagnostics[0].profile_id == "bad"


def test_command_profiles_only_match_command_capture_kinds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "config"
    (config / "toz").mkdir(parents=True)
    (config / "toz" / "profiles.toml").write_text(
        "[[profile]]\nid='cmd'\nmatch={command='fixture'}\npreview={kind='toc'}\n"
    )
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))

    def profiled(kind: str) -> bool:
        result = capture(
            CaptureInput(
                b"body\n", label="fixture", source="fixture", kind=kind, force=True
            ),
            tmp_path,
            tmp_path / f"{kind.replace(':', '-')}.db",
        )
        status, output = result.status, result.output
        assert status == 1
        return "search: varde run query" in output

    assert profiled("run")
    assert profiled("exec")
    assert profiled("script")
    assert profiled("hook:Bash")
    assert not profiled("capture")


@pytest.mark.parametrize("merge_small", [True, False])
def test_profile_segmentation_covers_prefix_and_splits_large_sections(
    merge_small: bool,
) -> None:
    profile = Profile(
        "test",
        Scope.USER,
        Path("test.toml"),
        sections_kind="heading",
        sections_pattern=__import__("re").compile(r"^## (.+)$"),
        merge_small=merge_small,
    )
    text = "intro\n## tiny\nx\n## large\n" + "paragraph text\n\n" * 200
    chunks = chunk_with_profile(text, profile)
    assert chunks[0].line_start == 1
    assert chunks[-1].line_end == len(text.splitlines())
    assert all(
        current.line_start <= previous.line_end + 1
        for previous, current in itertools.pairwise(chunks)
    )
    assert len(chunks) >= 3


def test_source_profile_matches_non_command_and_scope_precedence() -> None:
    source = Profile(
        "source",
        Scope.USER,
        Path("user.toml"),
        match_kind="source",
        match_pattern=glob_to_regex("*.json"),
    )
    command = Profile(
        "command",
        Scope.PROJECT,
        Path("project.toml"),
        match_kind="command",
        match_pattern=glob_to_regex("cargo test*"),
    )
    assert find_match([source, command], "data.json", False) is source
    assert find_match([source, command], "cargo test", True) is command
    assert find_match([source, command], "cargo test", False) is None


def test_project_scope_overrides_user_and_drops_untrusted_script(
    tmp_path: Path, monkeypatch
) -> None:
    config = tmp_path / "config"
    user_dir = config / "toz"
    user_dir.mkdir(parents=True)
    project = tmp_path / "project"
    (project / ".varde").mkdir(parents=True)
    (user_dir / "profiles.toml").write_text(
        '[[profile]]\nid="shared"\nmerge_small=true\n'
    )
    project_profiles = project / ".varde" / "toz-profiles.toml"
    project_profile = (
        '[[profile]]\nid="shared"\nmerge_small=false\n'
        "script=\"toz.record('unsafe', {})\"\n"
    )
    project_profiles.write_text(project_profile)
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))
    profiles, diagnostics = load_profiles(project)
    profile = next(item for item in profiles if item.id == "shared")
    assert profile.scope is Scope.PROJECT
    assert not profile.merge_small
    assert profile.script is None
    assert any("trusted_projects" in item.reason for item in diagnostics)


def test_trusted_project_script_is_kept_and_bad_test_case_reported(
    tmp_path: Path, monkeypatch
) -> None:
    config = tmp_path / "config"
    user_dir = config / "toz"
    user_dir.mkdir(parents=True)
    project = tmp_path / "project"
    (project / ".varde").mkdir(parents=True)
    (user_dir / "profiles.toml").write_text(f"trusted_projects=[{str(project)!r}]\n")
    (project / ".varde" / "toz-profiles.toml").write_text(
        '[[profile]]\nid="trusted"\nscript="toz.record(\'ok\', {})"\n'
        '[[profile.test]]\ninput="no name"\n'
    )
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))
    profiles, diagnostics = load_profiles(project)
    profile = next(item for item in profiles if item.id == "trusted")
    assert profile.script == "toz.record('ok', {})"
    assert profile.tests == []
    assert any(
        item.profile_id == "trusted" and "name" in item.reason for item in diagnostics
    )
