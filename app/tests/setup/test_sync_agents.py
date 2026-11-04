from types import SimpleNamespace

import pytest
from varde.setup.sync import agents
from varde.setup.sync.harness import Harness, HarnessId


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("OpenCode 2.0.18", 'permissions: [{"action": "read"'),
        ("opencode v2.0.32", 'permissions: [{"action": "read"'),
        ("opencode v2.0.17", 'permissions: [{"action": "read"'),
        ("2", 'permissions: [{"action": "read"'),
        ("2.4", 'permissions: [{"action": "read"'),
        ("v2", 'permissions: [{"action": "read"'),
        ("1.4.2", 'permission: {"read": "allow"'),
        # Hook install defaults to v2; agent sync retains its v1 fallback.
        ("unknown", 'permission: {"read": "allow"'),
    ],
)
def test_run_selects_opencode_variant_from_reported_version(
    tmp_path, monkeypatch, version, expected
):
    monkeypatch.setenv("VARDE_AGENTS_OPENCODE_VERSION", version)
    canonical = tmp_path / "canonical"

    agents.run(_context(tmp_path, canonical))

    assert expected in (canonical / "opencode" / "varde-builder.md").read_text()


def test_run_warns_for_opencode_below_floor(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VARDE_AGENTS_OPENCODE_VERSION", "2.0.17")

    agents.run(_context(tmp_path, tmp_path / "canonical"))

    assert "below the supported 2.x baseline 2.0.18" in capsys.readouterr().out


@pytest.mark.parametrize("version", ["2.0.18", "2.0.32"])
def test_run_does_not_warn_at_or_above_floor(tmp_path, monkeypatch, capsys, version):
    monkeypatch.setenv("VARDE_AGENTS_OPENCODE_VERSION", version)

    agents.run(_context(tmp_path, tmp_path / "canonical"))

    assert "below the supported 2.x baseline" not in capsys.readouterr().out


def test_opencode_version_probes_stdout_with_timeout(monkeypatch):
    monkeypatch.delenv("VARDE_AGENTS_OPENCODE_VERSION", raising=False)
    calls = []

    def run(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(stdout="OpenCode 2.4")

    monkeypatch.setattr(agents.subprocess, "run", run)

    assert agents._opencode_version() == (2, 4, 0)
    assert calls[0][1]["timeout"] == agents.OPENCODE_PROBE_TIMEOUT


def test_opencode_version_probe_timeout_is_unparseable(monkeypatch):
    monkeypatch.delenv("VARDE_AGENTS_OPENCODE_VERSION", raising=False)

    def run(*args, **kwargs):
        raise agents.subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(agents.subprocess, "run", run)

    assert agents._opencode_version() is None


def test_opencode_legacy_migration_uses_xdg_config_home(tmp_path, monkeypatch):
    from varde.setup.catalog import agents as catalog_agents

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    canonical = tmp_path / "canonical"
    harness = Harness(
        HarnessId.OPENCODE, tmp_path / "xdg/opencode/skills", tmp_path / "harness"
    )
    legacy = tmp_path / "xdg/opencode/agent"
    legacy.mkdir(parents=True)
    (legacy / "varde-builder.md").write_text(
        "legacy body\n<!-- varde-managed-agent -->\n"
    )
    context = _context(tmp_path, canonical)
    agent = next(item for item in catalog_agents() if item.name == "varde-builder")

    source = agents._migration_source(context, harness, agent, "opencode-v2.md")

    assert source is not None and "legacy body" in source


def test_opencode_legacy_cleanup_uses_xdg_config_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    canonical = tmp_path / "canonical/opencode"
    canonical.mkdir(parents=True)
    (canonical / "varde-builder.md").write_text(
        "canonical\n<!-- varde-managed-agent -->\n"
    )
    legacy = tmp_path / "xdg/opencode/agent"
    legacy.mkdir(parents=True)
    legacy_agent = legacy / "varde-builder.md"
    legacy_agent.write_text("legacy\n<!-- varde-managed-agent -->\n")
    harness = Harness(HarnessId.OPENCODE, None, tmp_path / "harness")
    harness.agents_dir.mkdir()

    agents._cleanup_harness(_context(tmp_path, tmp_path / "canonical"), harness, 2)

    assert not legacy_agent.exists()


def test_run_removes_managed_retired_aliases_and_keeps_unmarked_files(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("VARDE_AGENTS_OPENCODE_VERSION", "1")
    canonical = tmp_path / "canonical"
    markdown = Harness(HarnessId.CLAUDE, None, tmp_path / "claude")
    toml = Harness(HarnessId.CODEX, None, tmp_path / "codex")
    for harness in (markdown, toml):
        harness.agents_dir.mkdir(parents=True)
    for name in ("varde-executor", "build"):
        (markdown.agents_dir / f"{name}.md").write_text(
            "old body\n<!-- varde-managed-agent -->\n"
        )
    (markdown.agents_dir / "executor.md").write_text("user owned\n")
    (toml.agents_dir / "build.toml").write_text(
        'model = "custom"\n# varde-managed-agent\n'
    )

    agents.run(_context(tmp_path, canonical, [markdown, toml]))

    remaining = sorted(path.name for path in markdown.agents_dir.iterdir())
    assert "varde-executor.md" not in remaining
    assert "build.md" not in remaining
    assert (markdown.agents_dir / "executor.md").read_text() == "user owned\n"
    assert "build.toml" not in {path.name for path in toml.agents_dir.iterdir()}


def test_run_preserves_symlinked_harness_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_AGENTS_OPENCODE_VERSION", "1")
    canonical = tmp_path / "canonical"
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "harness"
    link.symlink_to(target)
    harness = Harness(HarnessId.CLAUDE, None, link)

    agents.run(_context(tmp_path, canonical, [harness]))

    assert link.is_symlink()
    assert list(target.iterdir()) == []


def _context(tmp_path, canonical, harnesses=()):
    return SimpleNamespace(
        home=tmp_path,
        agents_dir=canonical,
        harnesses=list(harnesses),
        link_mode="symlink",
        dry_run=False,
    )


def test_run_records_the_shipped_default_model(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_AGENTS_OPENCODE_VERSION", "1")
    canonical = tmp_path / "canonical"

    agents.run(_context(tmp_path, canonical))

    installed = (canonical / "claude" / "varde-builder.md").read_text()
    assert '<!-- varde-default: model: "sonnet" -->' in installed


def test_run_preserves_user_markdown_model(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_AGENTS_OPENCODE_VERSION", "1")
    canonical = tmp_path / "canonical"
    directory = canonical / "claude"
    directory.mkdir(parents=True)
    (directory / "varde-builder.md").write_text(
        "---\ndescription: agent\nmodel: custom\n---\nbody\n"
        "<!-- varde-managed-agent -->\n"
    )

    agents.run(_context(tmp_path, canonical))

    assert "model: custom" in (directory / "varde-builder.md").read_text()


def _install_explorer(canonical, model_lines):
    directory = canonical / "claude"
    directory.mkdir(parents=True)
    path = directory / "varde-explorer.md"
    path.write_text(
        f"---\ndescription: agent\n{model_lines}---\nbody\n"
        "<!-- varde-managed-agent -->\n"
    )
    return path


def test_run_moves_installed_explorer_from_sonnet_default_to_haiku(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("VARDE_AGENTS_OPENCODE_VERSION", "1")
    canonical = tmp_path / "canonical"
    path = _install_explorer(canonical, 'model: "sonnet"\n')

    agents.run(_context(tmp_path, canonical))

    assert 'model: "haiku"' in path.read_text()


def test_run_keeps_user_edited_explorer_model(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_AGENTS_OPENCODE_VERSION", "1")
    canonical = tmp_path / "canonical"
    path = _install_explorer(canonical, "model: custom\n")

    agents.run(_context(tmp_path, canonical))

    assert "model: custom" in path.read_text()


def test_run_preserves_user_codex_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_AGENTS_OPENCODE_VERSION", "1")
    canonical = tmp_path / "canonical"
    directory = canonical / "codex"
    directory.mkdir(parents=True)
    (directory / "varde-builder.toml").write_text(
        'model = "custom"\nmodel_reasoning_effort = "high"\n'
        'developer_instructions = "old"\n# varde-managed-agent\n'
    )

    agents.run(_context(tmp_path, canonical))

    installed = (directory / "varde-builder.toml").read_text()
    assert 'model = "custom"' in installed
    assert 'model_reasoning_effort = "high"' in installed


def test_run_installs_agents_and_links_selected_harness(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_AGENTS_OPENCODE_VERSION", "1")
    home = tmp_path / "home"
    home.mkdir()
    canonical = tmp_path / "canonical"
    harness = Harness(HarnessId.CLAUDE, None, home / ".claude/agents")

    agents.run(_context(tmp_path, canonical, [harness]))

    installed = canonical / "claude" / "varde-builder.md"
    linked = harness.agents_dir / "varde-builder.md"
    assert "<!-- varde-managed-agent -->" in installed.read_text()
    assert linked.is_symlink() and linked.resolve() == installed


def test_run_preserves_foreign_canonical_file(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_AGENTS_OPENCODE_VERSION", "1")
    canonical = tmp_path / "canonical"
    directory = canonical / "claude"
    directory.mkdir(parents=True)
    foreign = directory / "varde-builder.md"
    foreign.write_text("user owned")

    agents.run(_context(tmp_path, canonical))

    assert foreign.read_text() == "user owned"


def test_installed_agent_marker_matches_extension(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_AGENTS_OPENCODE_VERSION", "1")
    canonical = tmp_path / "canonical"

    agents.run(_context(tmp_path, canonical))

    markdown = (canonical / "claude" / "varde-builder.md").read_text()
    toml = (canonical / "codex" / "varde-builder.toml").read_text()
    assert markdown.rstrip().endswith("<!-- varde-managed-agent -->")
    assert toml.rstrip().endswith("# varde-managed-agent")


def _seed_retired(tmp_path, harness, extension):
    canonical_dir = tmp_path / "canonical" / harness.id.value
    canonical_dir.mkdir(parents=True)
    harness.agents_dir.mkdir(parents=True)
    marker = agents._marker(f"x.{extension}").decode().strip()
    canonical = canonical_dir / f"varde-mailman.{extension}"
    canonical.write_text(f"old\n{marker}\n")
    link = harness.agents_dir / f"varde-mailman.{extension}"
    link.symlink_to(canonical)
    return canonical, link


@pytest.mark.parametrize(
    ("harness_id", "extension"), [(HarnessId.CLAUDE, "md"), (HarnessId.CODEX, "toml")]
)
def test_run_removes_retired_mailman_symlinked_copies(
    tmp_path, monkeypatch, harness_id, extension
):
    monkeypatch.setenv("VARDE_AGENTS_OPENCODE_VERSION", "1")
    harness = Harness(harness_id, None, tmp_path / "harness")
    canonical, link = _seed_retired(tmp_path, harness, extension)

    agents.run(_context(tmp_path, tmp_path / "canonical", [harness]))

    assert not link.is_symlink() and not canonical.exists()


def test_run_keeps_foreign_retired_mailman(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_AGENTS_OPENCODE_VERSION", "1")
    harness = Harness(HarnessId.CLAUDE, None, tmp_path / "harness")
    harness.agents_dir.mkdir()
    foreign = harness.agents_dir / "varde-mailman.md"
    foreign.write_text("user owned\n")
    canonical_foreign = tmp_path / "canonical/claude/varde-mailman.md"
    canonical_foreign.parent.mkdir(parents=True)
    canonical_foreign.write_text("user owned canonical\n")

    agents.run(_context(tmp_path, tmp_path / "canonical", [harness]))

    assert foreign.read_text() == "user owned\n"
    assert canonical_foreign.read_text() == "user owned canonical\n"


def test_run_dry_run_reports_retired_mailman(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VARDE_AGENTS_OPENCODE_VERSION", "1")
    harness = Harness(HarnessId.CLAUDE, None, tmp_path / "harness")
    canonical, link = _seed_retired(tmp_path, harness, "md")
    context = _context(tmp_path, tmp_path / "canonical", [harness])
    context.dry_run = True

    agents.run(context)

    out = capsys.readouterr().out
    assert f"would remove {link}" in out and f"would remove {canonical}" in out
    assert link.is_symlink() and canonical.exists()


def test_run_removes_retired_mailman_from_opencode_legacy_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_AGENTS_OPENCODE_VERSION", "1")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    harness = Harness(HarnessId.OPENCODE, None, tmp_path / "harness")
    _seed_retired(tmp_path, harness, "md")
    legacy = tmp_path / "xdg/opencode/agent/varde-mailman.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("old\n<!-- varde-managed-agent -->\n")

    agents.run(_context(tmp_path, tmp_path / "canonical", [harness]))

    assert not legacy.exists()
