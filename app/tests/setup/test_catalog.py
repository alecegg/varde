from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from varde.manifest import Manifest
from varde.setup import catalog
from varde.setup.catalog import agents, collect_agents, collect_skills, skills


def _skill(root: Path, name: str, files: dict[str, str] | None = None) -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text("# skill\n")
    for relative, content in (files or {}).items():
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return directory


def test_provider_skills_merge_and_filter_hidden_content(tmp_path: Path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    _skill(
        first,
        "varde-one",
        {
            "visible.md": "one",
            ".hidden": "hidden",
            "evals/case.md": "eval",
            "__pycache__/x": "cache",
            "local-workspace/x": "workspace",
            "byte.pyc": "cache",
        },
    )
    _skill(second, "varde-two")
    values = collect_skills([first, second])
    assert [skill.name for skill in values] == ["varde-one", "varde-two"]
    assert [file.relative_path for file in values[0].files] == [
        "SKILL.md",
        "visible.md",
    ]


def test_duplicate_skill_names_name_both_roots(tmp_path: Path):
    first, second = tmp_path / "provider-a", tmp_path / "provider-b"
    first.mkdir()
    second.mkdir()
    _skill(first, "varde-duplicate")
    _skill(second, "varde-duplicate")
    with pytest.raises(ValueError, match="provider-a.*provider-b"):
        collect_skills([first, second])


def test_shared_file_from_one_provider_reaches_skill_in_another(tmp_path: Path):
    provider, consumer = tmp_path / "provider", tmp_path / "consumer"
    provider.mkdir()
    consumer.mkdir()
    (provider / "shared/references").mkdir(parents=True)
    (provider / "shared/MANIFEST").write_text("references/shared.md varde-consumer\n")
    (provider / "shared/references/shared.md").write_text("shared content")
    _skill(consumer, "varde-consumer")
    item = collect_skills([provider, consumer])[0]
    assert (
        next(
            file.bytes
            for file in item.files
            if file.relative_path == "references/shared.md"
        )
        == b"shared content"
    )


def test_shared_manifest_rejects_missing_file(tmp_path: Path):
    provider = tmp_path / "provider"
    (provider / "shared").mkdir(parents=True)
    (provider / "shared/MANIFEST").write_text("references/missing.md varde-skill\n")

    with pytest.raises(FileNotFoundError, match="references/missing.md"):
        collect_skills([provider])


@pytest.mark.parametrize("manifest", ["../outside.md varde-consumer\n", "malformed\n"])
def test_shared_manifest_rejects_unsafe_or_malformed_rows(
    tmp_path: Path, manifest: str
):
    root = tmp_path / "provider"
    root.mkdir()
    (root / "shared").mkdir()
    (root / "shared/MANIFEST").write_text(manifest)
    with pytest.raises(ValueError):
        collect_skills([root])


def test_shared_manifest_rejects_path_defined_by_multiple_roots(tmp_path: Path):
    first, second = tmp_path / "first", tmp_path / "second"
    for root in (first, second):
        (root / "shared/references").mkdir(parents=True)
        (root / "shared/MANIFEST").write_text("references/x.md varde-consumer\n")
        (root / "shared/references/x.md").write_text(root.name)
    with pytest.raises(ValueError, match="first.*second"):
        collect_skills([first, second])


def test_real_executable_mode_and_zip_shebang(tmp_path: Path):
    real = tmp_path / "real"
    real.mkdir()
    directory = _skill(real, "varde-real", {"run.sh": "echo hi"})
    (directory / "run.sh").chmod(0o755)
    real_file = next(
        file
        for file in collect_skills([real])[0].files
        if file.relative_path == "run.sh"
    )
    assert real_file.executable

    archive = tmp_path / "provider.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("skills/varde-zipped/SKILL.md", "# zipped\n")
        output.writestr("skills/varde-zipped/run", "#!/bin/sh\necho hi\n")
    with zipfile.ZipFile(archive) as source:
        zipped = zipfile.Path(source, at="skills/")
        item = collect_skills([zipped])[0]
    assert next(file for file in item.files if file.relative_path == "run").executable


def test_empty_skills_are_represented_as_empty_collection():
    assert collect_skills([]) == ()


def test_no_provider_reports_missing_skill_providers(monkeypatch):
    monkeypatch.setattr(catalog, "_provider_roots", lambda group, child: [])
    with pytest.raises(RuntimeError, match="no skill providers are installed"):
        skills()


def test_installed_provider_skills_are_available():
    values = skills()
    assert len(values) > 0
    assert [item.name for item in values] == sorted(item.name for item in values)
    assert all(
        any(file.relative_path == "SKILL.md" for file in item.files) for item in values
    )


def test_installed_agents_have_harness_variants():
    values = agents()
    assert {item.name for item in values} == {
        "accessibility",
        "readability",
        "spec-adherence",
        "ux-advocate",
        "varde-builder",
        "varde-explorer",
        "varde-planner",
        "varde-reviewer",
    }
    assert [item.name for item in values] == sorted(item.name for item in values)
    assert all(item.variants for item in values)
    assert {variant.file_name for agent in values for variant in agent.variants} >= {
        "claude.md",
        "codex.toml",
        "opencode.md",
        "pi.md",
    }


def test_agent_roots_ignore_metadata_directories(tmp_path: Path):
    root = tmp_path / "agents"
    (root / "varde-planner").mkdir(parents=True)
    (root / "varde-planner/codex.toml").write_text("agent")
    (root / "README.md").write_text("metadata")
    (root / "capabilities.json").write_text("{}")
    assert [item.name for item in collect_agents([root])] == ["varde-planner"]


def test_module_manifests_names_provider_missing_its_manifest(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="varde_example"):
        catalog._read_module_manifests([("varde_example", tmp_path)])


def test_module_manifests_invalid_manifest_names_provider(tmp_path: Path) -> None:
    (tmp_path / "module.toml").write_text("requires = []\n")
    with pytest.raises(
        ValueError, match="invalid manifest for provider varde_example.*name"
    ):
        catalog._read_module_manifests([("varde_example", tmp_path)])


def test_module_manifests_rejects_duplicate_names_and_names_both_providers(
    tmp_path: Path,
) -> None:
    providers = []
    for package in ("varde_first", "varde_second"):
        root = tmp_path / package
        root.mkdir()
        (root / "module.toml").write_text('name = "shared"\nrequires = []\n')
        providers.append((package, root))

    with pytest.raises(ValueError, match="module shared.*varde_first.*varde_second"):
        catalog._read_module_manifests(providers)


def test_module_preset_skips_unavailable_install_dependencies():
    manifests = {
        "workflow": Manifest("workflow", ("knowledge",)),
        "code": Manifest("code", ()),
    }
    names = {"workflow": ["varde-build"], "code": ["varde-code"]}
    assert catalog._module_preset_skills("workflow", manifests, names) is None
    assert catalog._module_preset_skills("code", manifests, names) == ["varde-code"]
