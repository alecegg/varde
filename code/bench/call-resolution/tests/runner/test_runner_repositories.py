"""Tests for repository manifest normalization and dry-run validation."""

from __future__ import annotations

from pathlib import Path

from run import runner


def _write_manifest(root, group, text):
    repos = root / "repos"
    repos.mkdir(exist_ok=True)
    path = repos / f"{group}.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_normalizes_python_manifest_row_shape(tmp_path, monkeypatch):
    _write_manifest(
        tmp_path,
        "python-ts",
        'format_version = 1\n[[repo]]\nrepo = "django/django"\n'
        'url = "https://example.test/django.git"\npin_sha = "abc123"\n'
        'language = "python"\nrole = "dev"\n',
    )
    monkeypatch.setattr(runner, "ROOT", tmp_path)

    assert runner._load_repositories("python-ts") == {
        "django/django": {
            "name": "django/django",
            "url": "https://example.test/django.git",
            "sha": "abc123",
            "languages": ["python"],
            "role": "dev",
        }
    }


def test_normalizes_name_sha_manifest_row_shape(tmp_path, monkeypatch):
    _write_manifest(
        tmp_path,
        "go-rust",
        '[[repo]]\nname = "go-gitea/gitea"\n'
        'url = "https://example.test/gitea.git"\nsha = "def456"\n'
        'language = "go"\nrole = "test-only"\n',
    )
    monkeypatch.setattr(runner, "ROOT", tmp_path)

    assert runner._load_repositories("go-rust")["go-gitea/gitea"] == {
        "name": "go-gitea/gitea",
        "url": "https://example.test/gitea.git",
        "sha": "def456",
        "languages": ["go"],
        "role": "test-only",
    }


def test_normalizes_repos_array_and_group_language(tmp_path, monkeypatch):
    _write_manifest(
        tmp_path,
        "cpp",
        '[[repos]]\nrepo = "fmtlib/fmt"\n'
        'url = "https://example.test/fmt.git"\npin_sha = "ghi789"\n'
        'role = "dev"\n',
    )
    monkeypatch.setattr(runner, "ROOT", tmp_path)

    assert runner._load_repositories("cpp")["fmtlib/fmt"] == {
        "name": "fmtlib/fmt",
        "url": "https://example.test/fmt.git",
        "sha": "ghi789",
        "languages": ["cpp"],
        "role": "dev",
    }


def test_normalizes_manifest_metadata_and_multiple_languages(tmp_path, monkeypatch):
    _write_manifest(
        tmp_path,
        "multi",
        'version = 1\nselection = "fixture"\n[[repo]]\n'
        'name = "example/shared"\nurl = "https://example.test/shared.git"\n'
        'sha = "jkl012"\nlanguages = ["java", "csharp"]\nrole = "dev"\n',
    )
    monkeypatch.setattr(runner, "ROOT", tmp_path)

    assert runner._load_repositories("multi")["example/shared"]["languages"] == [
        "csharp",
        "java",
    ]


def test_unknown_repository_manifest_shape_has_clear_error(tmp_path, monkeypatch):
    _write_manifest(tmp_path, "bad", 'repos = "not-an-array-of-tables"\n')
    monkeypatch.setattr(runner, "ROOT", tmp_path)

    try:
        runner._load_repositories("bad")
    except (TypeError, ValueError) as error:
        assert "unknown repository manifest shape" in str(error)
    else:
        raise AssertionError("unsupported manifest shape was accepted")


def test_all_real_dev_and_test_records_resolve_to_manifest_repositories():
    call_root = Path(runner.__file__).resolve().parents[1]
    manifest_groups = sorted(path.stem for path in (call_root / "repos").glob("*.toml"))
    assert manifest_groups == ["cpp", "go-rust", "java-csharp", "python-ts"]

    repos_by_group = {
        group: runner._load_repositories(group) for group in manifest_groups
    }
    for repos in repos_by_group.values():
        assert repos
        for repo in repos.values():
            assert repo["name"]
            assert len(repo["sha"]) == 40
            assert repo["languages"]

    for split in ("dev", "test"):
        split_root = runner._split_dir(split, runner.DEFAULT_RESTRICTED_DIR)
        groups = sorted(path for path in split_root.iterdir() if path.is_dir())
        assert [group.name for group in groups] == manifest_groups
        for group_dir in groups:
            repos = repos_by_group[group_dir.name]
            records, skipped = runner._load_records(group_dir)
            assert skipped >= 0
            expected_role = "dev" if split == "dev" else "test-only"
            for record in records:
                repo = repos.get(str(record["repo"]))
                assert repo is not None, (
                    f"{split}/{group_dir.name}: unknown repo {record['repo']}"
                )
                assert repo["role"] == expected_role, (
                    f"{record['repo']} is not a {expected_role} repo"
                )
                assert record["language"] in repo["languages"], (
                    f"{record['repo']} does not list language {record['language']}"
                )


def test_real_data_dry_run_prints_pins_without_creating_repo_cache(tmp_path, capsys):
    cache = tmp_path / "repo-cache"

    assert (
        runner.main(
            [
                "--adapter",
                "existing",
                "--split",
                "dev",
                "--repo-cache",
                str(cache),
                "--dry-run",
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert (
        "would clone python-ts:django/django @ d430084791a61b31cecec132bce3dca19194f7f2"
        in output
    )
    assert (
        "would clone cpp:fmtlib/fmt @ fdf31252e61ca7efe99af41bb4780353cc2253dd"
        in output
    )
    assert not cache.exists()
