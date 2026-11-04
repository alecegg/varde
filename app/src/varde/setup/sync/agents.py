"""Install and synchronize provider agent definitions."""

from __future__ import annotations

import os
import subprocess
import tempfile
from enum import Enum
from pathlib import Path

from varde.setup.catalog import Agent, AgentVariant
from varde.setup.catalog import agents as catalog_agents
from varde.setup.hooks_install import config_home
from varde.setup.opencode_version import is_below_floor, parse_version
from varde.setup.sync import fsops
from varde.setup.sync.harness import Harness, HarnessId
from varde.setup.sync.preserve import preserve_models as _preserve_models

MARKDOWN_MARKER = b"\n<!-- varde-managed-agent -->\n"
TOML_MARKER = b"\n# varde-managed-agent\n"
OPENCODE_PROBE_TIMEOUT = 2
RETIRED_AGENTS = ("varde-mailman",)
HARNESS_EXTENSIONS = {
    HarnessId.CLAUDE: "md",
    HarnessId.CODEX: "toml",
    HarnessId.OPENCODE: "md",
    HarnessId.PI: "md",
}


class DirectoryState(Enum):
    MISSING = 1
    REAL = 2
    FOREIGN = 3


class CanonicalFile(Enum):
    MISSING = 1
    MANAGED = 2
    FOREIGN = 3


class HarnessEntry(Enum):
    MISSING = 1
    MANAGED = 2
    CANONICAL_LINK = 3
    FOREIGN = 4


def _directory_state(path: Path) -> DirectoryState:
    try:
        path.lstat()
    except FileNotFoundError:
        return DirectoryState.MISSING
    return (
        DirectoryState.REAL
        if path.is_dir() and not path.is_symlink()
        else DirectoryState.FOREIGN
    )


def _has_marker(contents: bytes) -> bool:
    return any(
        line in (b"<!-- varde-managed-agent -->", b"# varde-managed-agent")
        for line in contents.split(b"\n")
    )


def _managed_file(path: Path) -> str | None:
    try:
        if not path.is_file() or path.is_symlink():
            return None
        contents = path.read_bytes()
    except FileNotFoundError:
        return None
    return contents.decode() if _has_marker(contents) else None


def _canonical_file(path: Path) -> tuple[CanonicalFile, str | None]:
    try:
        if not path.is_file() or path.is_symlink():
            return (
                (CanonicalFile.FOREIGN, None)
                if os.path.lexists(path)
                else (CanonicalFile.MISSING, None)
            )
        contents = path.read_bytes()
    except FileNotFoundError:
        return CanonicalFile.MISSING, None
    if not _has_marker(contents):
        return CanonicalFile.FOREIGN, None
    return CanonicalFile.MANAGED, contents.decode()


def _opencode_version() -> tuple[int, int, int] | None:
    configured = os.environ.get("VARDE_AGENTS_OPENCODE_VERSION")
    if configured:
        return parse_version(configured)
    with tempfile.TemporaryDirectory(prefix="varde-opencode-probe-") as home:
        env = os.environ.copy()
        env.update(
            HOME=home,
            XDG_CONFIG_HOME=f"{home}/.config",
            XDG_CACHE_HOME=f"{home}/.cache",
            XDG_DATA_HOME=f"{home}/.local/share",
            XDG_STATE_HOME=f"{home}/.local/state",
        )
        try:
            result = subprocess.run(
                ["opencode", "--version"],  # noqa: S607 - Probes the harness executable available on the user's PATH.
                capture_output=True,
                text=True,
                env=env,
                timeout=OPENCODE_PROBE_TIMEOUT,
                check=False,
            )
        except OSError, subprocess.TimeoutExpired:
            return None
    return parse_version(result.stdout)


def _opencode_major() -> int:
    version = _opencode_version()
    return version[0] if version is not None else 1


def _variant_for(
    agent: Agent, harness: HarnessId, opencode_major: int
) -> AgentVariant | None:
    file_name = {
        HarnessId.CLAUDE: "claude.md",
        HarnessId.CODEX: "codex.toml",
        HarnessId.OPENCODE: "opencode-v2.md" if opencode_major >= 2 else "opencode.md",
        HarnessId.PI: "pi.md",
    }[harness]
    return next(
        (variant for variant in agent.variants if variant.file_name == file_name), None
    )


def _extension(file_name: str) -> str:
    return file_name.rsplit(".", 1)[1] if "." in file_name else "md"


def _marker(file_name: str) -> bytes:
    return TOML_MARKER if file_name.endswith(".toml") else MARKDOWN_MARKER


def _old_names(agent: str) -> tuple[str, ...]:
    return {
        "varde-explorer": ("explore",),
        "varde-planner": ("plan",),
        "varde-reviewer": ("review",),
        "varde-builder": ("varde-executor", "executor", "build"),
    }.get(agent, ())


def _normalize(path: Path) -> Path:
    return Path(os.path.normpath(path))


def _within(path: Path, directory: Path) -> bool:
    try:
        _normalize(path).relative_to(_normalize(directory))
    except ValueError:
        return False
    else:
        return True


def _managed_source(path: Path, canonical_directory: Path) -> str | None:
    if path.is_symlink():
        target = path.readlink()
        if not target.is_absolute():
            target = path.parent / target
        return _managed_file(target) if _within(target, canonical_directory) else None
    return _managed_file(path)


def _migration_source(
    context, harness: Harness, agent: Agent, file_name: str
) -> str | None:
    extension = _extension(file_name)
    destination = harness.agents_dir / f"{agent.name}.{extension}"
    canonical = context.agents_dir / harness.id.value
    source = _managed_source(destination, canonical)
    if source is not None:
        return source
    if os.path.lexists(destination):
        return None
    candidates = []
    for old in _old_names(agent.name):
        candidates.extend(
            (
                harness.agents_dir / f"{old}.{extension}",
                canonical / f"{old}.{extension}",
            )
        )
    if harness.id is HarnessId.OPENCODE:
        legacy = config_home(context.home) / "opencode/agent"
        if _directory_state(legacy) is DirectoryState.REAL:
            candidates.append(legacy / f"{agent.name}.md")
            candidates.extend(legacy / f"{old}.md" for old in _old_names(agent.name))
    return next(
        (
            source
            for candidate in candidates
            if (source := _managed_source(candidate, canonical)) is not None
        ),
        None,
    )


def _add_unowned(report: dict, path: Path) -> None:
    if path not in report["unowned"]:
        report["unowned"].append(path)


def _install_harness(
    context, harness_id: HarnessId, opencode_major: int, report: dict
) -> None:
    directory = context.agents_dir / harness_id.value
    state = _directory_state(directory)
    if state is DirectoryState.FOREIGN:
        _add_unowned(report, directory)
        return
    if state is DirectoryState.MISSING and not context.dry_run:
        directory.mkdir(parents=True, exist_ok=True)
        if _directory_state(directory) is not DirectoryState.REAL:
            _add_unowned(report, directory)
            return
    selected = next((item for item in context.harnesses if item.id is harness_id), None)
    for agent in catalog_agents():
        variant = _variant_for(agent, harness_id, opencode_major)
        if variant is None:
            raise ValueError(f"agent {agent.name} has no {harness_id.value} variant")
        destination = directory / f"{agent.name}.{_extension(variant.file_name)}"
        existing, installed = _canonical_file(destination)
        if existing is CanonicalFile.FOREIGN:
            _add_unowned(report, destination)
            continue
        migrated = (
            _migration_source(context, selected, agent, variant.file_name)
            if selected
            else None
        )
        previous = migrated if migrated is not None else installed
        staged = variant.bytes.decode()
        if context.dry_run:
            _, preserved = _preserve_models(harness_id, agent.name, staged, previous)
            action = "replace" if existing is CanonicalFile.MANAGED else "install"
            print(f"would {action} agent {agent.name} -> {destination}")
            report["preserved"].extend((key, destination) for key in preserved)
            continue
        contents, preserved = _preserve_models(harness_id, agent.name, staged, previous)
        fsops.replace_file(destination, contents.encode() + _marker(variant.file_name))
        action = "Replaced" if existing is CanonicalFile.MANAGED else "Installed"
        print(f"{action} agent {agent.name} -> {destination}")
        report["preserved"].extend((key, destination) for key in preserved)


def _harness_entry(path: Path, canonical: Path) -> HarnessEntry:
    if not os.path.lexists(path):
        return HarnessEntry.MISSING
    if path.is_symlink():
        return (
            HarnessEntry.CANONICAL_LINK
            if path.readlink() == canonical
            else HarnessEntry.FOREIGN
        )
    if not path.is_file():
        return HarnessEntry.FOREIGN
    return (
        HarnessEntry.MANAGED if _has_marker(path.read_bytes()) else HarnessEntry.FOREIGN
    )


def _sync_entry(
    context,
    harness: Harness,
    agent: Agent,
    variant: AgentVariant,
    canonical: Path,
    contents: str | None,
    report: dict,
) -> bool:
    destination = harness.agents_dir / f"{agent.name}.{_extension(variant.file_name)}"
    state = _harness_entry(destination, canonical)
    if state is HarnessEntry.FOREIGN:
        _add_unowned(report, destination)
        return False
    link_mode = getattr(context.link_mode, "value", context.link_mode)
    if link_mode == "symlink":
        if state is HarnessEntry.CANONICAL_LINK:
            print(
                f"would keep already linked {destination} -> {canonical}"
                if context.dry_run
                else f"Already linked harness agent {destination} -> {canonical}"
            )
        elif context.dry_run:
            print(f"would link {destination} -> {canonical}")
        else:
            fsops.replace_with_file_symlink(destination, canonical)
            print(f"Linked harness agent {destination} -> {canonical}")
    elif context.dry_run:
        print(f"would install copy agent {agent.name} -> {destination}")
    else:
        if contents is None:
            raise ValueError(f"canonical agent file is missing for {destination}")
        fsops.replace_file(destination, contents.encode())
        print(f"Installed harness agent copy {destination} -> {canonical}")
    return True


def _sync_harness_entries(
    context, harness: Harness, opencode_major: int, report: dict
) -> None:
    state = _directory_state(harness.agents_dir)
    if state is DirectoryState.FOREIGN:
        _add_unowned(report, harness.agents_dir)
        return
    if state is DirectoryState.MISSING and not context.dry_run:
        harness.agents_dir.mkdir(parents=True, exist_ok=True)
        if _directory_state(harness.agents_dir) is not DirectoryState.REAL:
            _add_unowned(report, harness.agents_dir)
            return
    canonical_directory = context.agents_dir / harness.id.value
    canonical_state = _directory_state(canonical_directory)
    if canonical_state is DirectoryState.FOREIGN:
        return
    if canonical_state is DirectoryState.MISSING and not context.dry_run:
        raise ValueError(f"canonical agent directory {canonical_directory} is missing")
    for agent in catalog_agents():
        variant = _variant_for(agent, harness.id, opencode_major)
        if variant is None:
            raise ValueError(f"agent {agent.name} has no {harness.id.value} variant")
        canonical = (
            canonical_directory / f"{agent.name}.{_extension(variant.file_name)}"
        )
        state, contents = _canonical_file(canonical)
        if state is CanonicalFile.MISSING and not context.dry_run:
            raise ValueError(f"canonical agent file {canonical} is missing")
        if state is CanonicalFile.FOREIGN:
            _add_unowned(report, canonical)
            continue
        _sync_entry(context, harness, agent, variant, canonical, contents, report)


def _remove_managed(path: Path, dry_run: bool) -> None:
    if _managed_file(path) is None:
        return
    if dry_run:
        print(f"would remove {path}")
    else:
        path.unlink()
        print(f"Removed {path}")


def _remove_retired(path: Path, canonical_directory: Path, dry_run: bool) -> None:
    if not os.path.lexists(path):
        return
    if path.is_symlink():
        target = path.readlink()
        if not target.is_absolute():
            target = path.parent / target
        if not _within(target, canonical_directory):
            return
        if dry_run:
            print(f"would remove {path}")
        else:
            path.unlink()
            print(f"Removed {path}")
        return
    _remove_managed(path, dry_run)


def _cleanup_harness(context, harness: Harness, opencode_major: int) -> None:
    if _directory_state(harness.agents_dir) is not DirectoryState.REAL:
        return
    canonical_directory = context.agents_dir / harness.id.value
    if _directory_state(canonical_directory) is DirectoryState.FOREIGN:
        return
    for agent in catalog_agents():
        variant = _variant_for(agent, harness.id, opencode_major)
        if variant is None:
            raise ValueError(f"agent {agent.name} has no {harness.id.value} variant")
        extension = _extension(variant.file_name)
        canonical = canonical_directory / f"{agent.name}.{extension}"
        state, _ = _canonical_file(canonical)
        if (
            state is CanonicalFile.MISSING
            and not context.dry_run
            or state is CanonicalFile.FOREIGN
        ):
            continue
        destination = harness.agents_dir / f"{agent.name}.{extension}"
        if _harness_entry(destination, canonical) is HarnessEntry.FOREIGN:
            continue
        for old in _old_names(agent.name):
            _remove_retired(
                harness.agents_dir / f"{old}.{extension}",
                canonical_directory,
                context.dry_run,
            )
        if harness.id is HarnessId.OPENCODE:
            legacy = config_home(context.home) / "opencode/agent"
            if _directory_state(legacy) is DirectoryState.REAL:
                _remove_managed(legacy / f"{agent.name}.md", context.dry_run)
                for old in _old_names(agent.name):
                    _remove_retired(
                        legacy / f"{old}.md", canonical_directory, context.dry_run
                    )


def _cleanup_retired_agents(context, harness: Harness) -> None:
    if _directory_state(harness.agents_dir) is not DirectoryState.REAL:
        return
    canonical_directory = context.agents_dir / harness.id.value
    if _directory_state(canonical_directory) is DirectoryState.FOREIGN:
        return
    extension = HARNESS_EXTENSIONS[harness.id]
    legacy = config_home(context.home) / "opencode/agent"
    legacy_real = _directory_state(legacy) is DirectoryState.REAL
    for name in RETIRED_AGENTS:
        file_name = f"{name}.{extension}"
        _remove_retired(
            harness.agents_dir / file_name, canonical_directory, context.dry_run
        )
        _remove_managed(canonical_directory / file_name, context.dry_run)
        if harness.id is HarnessId.OPENCODE and legacy_real:
            _remove_managed(legacy / file_name, context.dry_run)


def run(context) -> None:
    """Install canonical agent files, link selected harnesses, and clean retired
    names."""
    opencode_version = _opencode_version()
    opencode_major = opencode_version[0] if opencode_version is not None else 1
    if opencode_version is not None and is_below_floor(opencode_version):
        print(
            f"OpenCode {'.'.join(map(str, opencode_version))} is below the "
            "supported 2.x baseline 2.0.18; syncing best effort"
        )
    report = {"unowned": [], "preserved": []}
    for harness in (
        HarnessId.CLAUDE,
        HarnessId.CODEX,
        HarnessId.OPENCODE,
        HarnessId.PI,
    ):
        _install_harness(context, harness, opencode_major, report)
    for harness in context.harnesses:
        _sync_harness_entries(context, harness, opencode_major, report)
    for key, path in report["preserved"]:
        print(
            f"would preserve user model setting {key} in {path}"
            if context.dry_run
            else f"Preserved user model setting {key} in {path}"
        )
    for path in report["unowned"]:
        print(
            f"would preserve unowned {path}"
            if context.dry_run
            else f"Preserved unowned {path}"
        )
    for harness in context.harnesses:
        _cleanup_harness(context, harness, opencode_major)
        _cleanup_retired_agents(context, harness)
    for harness in context.harnesses:
        directory = context.agents_dir / harness.id.value
        if _directory_state(directory) is DirectoryState.FOREIGN:
            continue
        try:
            entries = list(directory.iterdir())
        except FileNotFoundError:
            if context.dry_run:
                continue
            raise
        prefix = f"{_old_names('varde-builder')[0]}."
        for entry in entries:
            if entry.name.startswith(prefix):
                _remove_managed(entry, context.dry_run)
