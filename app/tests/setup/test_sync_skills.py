import pytest
from varde.setup import dispatch
from varde.setup.catalog import skills
from varde.setup.sync.skills import (
    OWNERSHIP_MARKER,
    OWNERSHIP_VALUE,
    features_for,
    install_canonical,
    preset_names,
    preset_skills,
    remove_retired,
    resolve_names,
    resolve_selection,
    skill_relations,
    sync_entry,
)
from varde_core.skill_relations import Relations


def test_skill_relations_cover_available_skills():
    relations = skill_relations()
    assert set(relations) == {skill.name for skill in skills()}


def test_selection_adds_implicit_skill():
    resolved = resolve_selection(["varde-code"])
    assert {skill.name for skill in resolved.skills} == {"varde-code", "varde-manage"}


def test_empty_selection_means_all_skills():
    assert len(resolve_selection([]).skills) == len(skills())


def test_none_selection_means_all_skills():
    assert len(resolve_selection(None).skills) == len(skills())


def test_selection_features_are_derived_from_closure():
    relations = {
        "custom": Relations(requires=["varde-build"]),
        "varde-build": Relations(),
    }
    assert resolve_selection(["custom"], relations).features == {"change"}


def test_features_include_supported_skills():
    assert features_for(
        [
            "varde-plan",
            "varde-build",
            "varde-orchestrate",
            "varde-swarm",
            "varde-toz",
            "varde-learn",
            "varde-code",
            "varde-knowledge",
        ]
    ) == {"change", "toz", "learn", "code", "knowledge"}


def test_features_cover_split_learn_and_knowledge_skills():
    assert features_for(["varde-diagnose", "varde-improve", "varde-session-notes"]) == {
        "learn",
        "knowledge",
    }


def test_features_ignore_skills_without_runtime_features():
    assert features_for(["varde-docs", "varde-review"]) == set()


def test_closure_is_sorted_and_deduplicated():
    relations = {
        "a": Relations(requires=["c", "b", "b"]),
        "b": Relations(),
        "c": Relations(),
    }
    assert resolve_names(["a"], relations) == ["a", "b", "c"]


def test_closure_rejects_unknown_names():
    with pytest.raises(ValueError, match="unknown skill"):
        resolve_names(["absent"], {})


def test_presets_are_sorted():
    assert preset_names() == sorted(preset_names())


def test_unknown_preset_lists_names():
    with pytest.raises(ValueError, match="valid presets"):
        preset_skills("missing")


def test_preset_names_are_shipped_skills():
    shipped = {skill.name for skill in skills()}
    assert all(
        name in shipped for preset in preset_names() for name in preset_skills(preset)
    )


def test_skill_requirement_extends_module_preset_selection():
    selected = preset_skills("toz")
    relations = skill_relations()
    relations["varde-toz"] = Relations(requires=["varde-code"])
    assert resolve_names(selected, relations) == ["varde-code", "varde-toz"]


def test_selection_unions_preset_and_skill_dependency_closures():
    relations = skill_relations()
    relations["varde-toz"] = Relations(requires=["varde-code"])
    selection = resolve_selection(preset_skills("toz"), relations)
    assert {skill.name for skill in selection.skills} == {
        "varde-code",
        "varde-manage",
        "varde-toz",
    }


def test_sync_help_renders_preset_names(capsys):
    assert dispatch.run_setup_route(["setup", "sync", "--help"]) == 0
    output = capsys.readouterr().out
    assert "code, design, dev, full, learn" in output
    assert "{presets}" not in output


def test_install_canonical_writes_marker(tmp_path):
    chosen = next(skill for skill in skills() if skill.name == "varde-code")
    install_canonical(tmp_path, (chosen,))
    marker = tmp_path / chosen.name / ".varde-managed-skill"
    assert marker.read_text(encoding="utf-8").splitlines()[0] == "varde-managed-skill"


def test_install_canonical_dry_run_does_not_write(tmp_path):
    chosen = next(skill for skill in skills() if skill.name == "varde-code")
    assert install_canonical(tmp_path, (chosen,), dry_run=True)
    assert not (tmp_path / chosen.name).exists()


def test_install_preserves_unowned_directory(tmp_path):
    chosen = next(skill for skill in skills() if skill.name == "varde-code")
    destination = tmp_path / chosen.name
    destination.mkdir(parents=True)
    (destination / "mine").write_text("keep")
    install_canonical(tmp_path, (chosen,))
    assert (destination / "mine").read_text() == "keep"


def test_sync_entry_creates_symlink(tmp_path):
    chosen = next(skill for skill in skills() if skill.name == "varde-code")
    canonical = tmp_path / "canonical"
    install_canonical(canonical, (chosen,))
    message = sync_entry(tmp_path / "harness", canonical, chosen)
    assert "Linked harness skill" in message
    assert (tmp_path / "harness" / chosen.name).is_symlink()


def test_sync_entry_preserves_foreign_destination(tmp_path):
    chosen = next(skill for skill in skills() if skill.name == "varde-code")
    canonical = tmp_path / "canonical"
    install_canonical(canonical, (chosen,))
    foreign = tmp_path / "harness" / chosen.name
    foreign.mkdir(parents=True)
    (foreign / "mine").touch()
    assert "Preserved unowned" in sync_entry(tmp_path / "harness", canonical, chosen)


def test_sync_entry_copy_mode(tmp_path):
    chosen = next(skill for skill in skills() if skill.name == "varde-code")
    canonical = tmp_path / "canonical"
    install_canonical(canonical, (chosen,))
    sync_entry(tmp_path / "harness", canonical, chosen, link_mode="copy")
    assert (tmp_path / "harness" / chosen.name / ".varde-managed-skill").exists()


def _seed_retired_skill(tmp_path):
    canonical = tmp_path / "skills" / "varde-mailman"
    canonical.mkdir(parents=True)
    (canonical / OWNERSHIP_MARKER).write_bytes(OWNERSHIP_VALUE)
    harness = tmp_path / "harness"
    harness.mkdir()
    link = harness / "varde-mailman"
    link.symlink_to(canonical)
    return canonical, harness, link


def test_saved_retired_skill_is_dropped_with_one_warning(capsys):
    from varde.setup.sync import config

    saved = config.read({"sync": {"skills": ["varde-plan", "varde-mailman"]}})

    assert saved.skills == ["varde-plan"]
    assert capsys.readouterr().err.count("varde-mailman") == 1
    with pytest.raises(ValueError, match="unknown skill varde-mailman"):
        config.validate_skills(["varde-mailman"])


def test_saved_retired_only_skills_is_no_selection(capsys):
    from varde.setup.sync import config

    saved = config.read({"sync": {"skills": ["varde-mailman"]}})

    assert saved.skills is None
    assert "varde-mailman" in capsys.readouterr().err


def test_remove_retired_removes_owned_canonical_and_symlink(tmp_path):
    canonical, harness, link = _seed_retired_skill(tmp_path)

    remove_retired(tmp_path / "skills", [harness, None])

    assert not canonical.exists() and not link.is_symlink()


def test_remove_retired_removes_old_agent_doc_authoring_install(tmp_path):
    canonical = tmp_path / "skills" / "varde-agent-doc-authoring"
    canonical.mkdir(parents=True)
    (canonical / OWNERSHIP_MARKER).write_bytes(OWNERSHIP_VALUE)
    harness = tmp_path / "harness"
    harness.mkdir()
    link = harness / "varde-agent-doc-authoring"
    link.symlink_to(canonical)

    remove_retired(tmp_path / "skills", [harness])

    assert not canonical.exists() and not link.is_symlink()


def test_remove_retired_keeps_foreign_dir_and_symlink(tmp_path):
    canonical = tmp_path / "skills" / "varde-mailman"
    canonical.mkdir(parents=True)
    (canonical / "SKILL.md").write_text("user\n")
    harness = tmp_path / "harness"
    harness.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    link = harness / "varde-mailman"
    link.symlink_to(elsewhere)

    messages = remove_retired(tmp_path / "skills", [harness])

    assert canonical.is_dir() and link.is_symlink()
    assert all(m.startswith("Preserved unowned") for m in messages)


def test_remove_retired_dry_run_changes_nothing(tmp_path):
    canonical, harness, link = _seed_retired_skill(tmp_path)

    messages = remove_retired(tmp_path / "skills", [harness], dry_run=True)

    assert messages == [f"would remove {link}", f"would remove {canonical}"]
    assert canonical.is_dir() and link.is_symlink()
