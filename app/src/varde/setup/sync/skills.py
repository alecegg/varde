"""Skill selection, dependency closure, and safe installation."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

from varde_core import skill_props
from varde_core.skill_relations import IMPLICIT_SKILL, Relations, closure, parse

from varde.setup.catalog import Skill, preset_table
from varde.setup.catalog import skills as catalog_skills
from varde.setup.sync import fsops

OWNERSHIP_MARKER = ".varde-managed-skill"
OWNERSHIP_VALUE = b"varde-managed-skill\n"
RETIRED_SKILLS = ("varde-mailman", "varde-agent-doc-authoring")


def preset_names() -> list[str]:
    return sorted(preset_table())


def preset_skills(name: str) -> list[str]:
    presets = preset_table()
    if name in ("doc", "knowledge"):
        raise ValueError(
            f"preset {name} was merged into preset learn; use --preset learn"
        )
    if name not in presets:
        raise ValueError(
            f"unknown preset {name}; valid presets: {', '.join(sorted(presets))}"
        )
    return list(presets[name])


def _frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return ""
    return text[4:].split("\n---", 1)[0] if "\n---" in text[4:] else ""


def skill_relations() -> dict[str, Relations]:
    result = {}
    for skill in catalog_skills():
        file = next(
            (item for item in skill.files if item.relative_path == "SKILL.md"), None
        )
        if file is None:
            raise ValueError(f"skill {skill.name} has no SKILL.md")
        try:
            text = file.bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(
                f"skill {skill.name} SKILL.md is not UTF-8: {exc}"
            ) from exc
        try:
            result[skill.name] = parse(_frontmatter(text))
        except ValueError as exc:
            raise ValueError(f"skill {skill.name}: {exc}") from exc
    return result


def resolve_names(names: list[str], relations: dict[str, Relations]) -> list[str]:
    return closure(
        names, lambda name: relations[name].requires if name in relations else None
    )


def features_for(names: list[str]) -> set[str]:
    feature_names = {
        "varde-plan": "change",
        "varde-build": "change",
        "varde-orchestrate": "change",
        "varde-swarm": "change",
        "varde-toz": "toz",
        "varde-learn": "learn",
        "varde-diagnose": "learn",
        "varde-improve": "learn",
        "varde-code": "code",
        "varde-knowledge": "knowledge",
        "varde-session-notes": "knowledge",
    }
    return {feature_names[name] for name in names if name in feature_names}


@dataclass(frozen=True)
class ResolvedSelection:
    skills: tuple[Skill, ...]
    features: frozenset[str]
    relations: dict[str, Relations]


def resolve_selection(
    selected: list[str] | None, relations: dict[str, Relations] | None = None
) -> ResolvedSelection:
    all_skills = catalog_skills()
    relations = relations if relations is not None else skill_relations()
    resolved = (
        resolve_names(selected, relations)
        if selected
        else [item.name for item in all_skills]
    )
    chosen = tuple(
        item
        for item in all_skills
        if item.name == IMPLICIT_SKILL or item.name in resolved
    )
    return ResolvedSelection(chosen, frozenset(features_for(resolved)), relations)


def _marker_matches(directory: Path) -> bool:
    marker = directory / OWNERSHIP_MARKER
    try:
        if not marker.is_file() or marker.is_symlink():
            return False
        return "varde-managed-skill" in marker.read_text().splitlines()
    except FileNotFoundError:
        return False


def _managed_directory(path: Path) -> str:
    try:
        path.lstat()
    except FileNotFoundError:
        return "missing"
    if not path.is_dir() or path.is_symlink() or not _marker_matches(path):
        return "foreign"
    return "owned"


def _packaged_version() -> str:
    try:
        return metadata.version("varde")
    except metadata.PackageNotFoundError:
        return "unknown"


def _read_props(directory: Path) -> skill_props.Props:
    return skill_props.parse((directory / OWNERSHIP_MARKER).read_text())


def _is_modified(
    destination: Path, props: skill_props.Props, packaged_hash: str
) -> bool:
    # An install from before properties existed has no recorded base: treat it
    # as unmodified so the first sync replaces it and writes the properties.
    if not props.packaged_hash:
        return False
    return skill_props.is_modified(
        props, skill_props.tree_hash(skill_props.disk_tree(destination))
    )


def _keep_modified(
    destination: Path, props: skill_props.Props, packaged_hash: str, version: str
) -> None:
    """Leave the tree alone; record the packaged update as pending."""
    if packaged_hash == props.packaged_hash:
        return
    pending = skill_props.with_pending(props, version, packaged_hash)
    if pending != props:
        (destination / OWNERSHIP_MARKER).write_text(skill_props.render(pending))


def install_canonical(
    skills_dir: Path, selected: tuple[Skill, ...], *, dry_run: bool = False
) -> list[str]:
    messages = []
    version = _packaged_version()
    for skill in selected:
        destination = skills_dir / skill.name
        state = _managed_directory(destination)
        if state == "foreign":
            messages.append(f"Preserved unowned {destination}")
            continue
        packaged_hash = skill_props.tree_hash(
            {file.relative_path: file.bytes for file in skill.files}
        )
        props = _read_props(destination) if state == "owned" else skill_props.Props()
        modified = state == "owned" and _is_modified(destination, props, packaged_hash)
        if modified and dry_run:
            messages.append(f"would keep locally modified skill {skill.name}")
            continue
        if modified:
            _keep_modified(destination, props, packaged_hash, version)
            messages.append(
                f"Kept locally modified skill {skill.name}; "
                "packaged update pending (varde learn skills updates)"
            )
            continue
        if dry_run:
            messages.append(f"would install skill {skill.name} -> {destination}")
            continue
        sidecar = skill_props.render(
            skill_props.Props(packaged_version=version, packaged_hash=packaged_hash)
        )

        def populate(staged: Path, skill=skill, sidecar=sidecar) -> None:
            for file in skill.files:
                fsops.write_file(
                    staged / file.relative_path, file.bytes, file.executable
                )
            fsops.write_file(staged / OWNERSHIP_MARKER, sidecar.encode())

        fsops.replace_directory(destination, populate)
        messages.append(f"Installed skill {skill.name} -> {destination}")
    return messages


def _same_existing_path(first: Path, second: Path) -> bool:
    try:
        return first.resolve(strict=True) == second.resolve(strict=True)
    except FileNotFoundError:
        return False


def sync_entry(
    directory: Path,
    skills_dir: Path,
    skill: Skill,
    *,
    link_mode: str = "symlink",
    dry_run: bool = False,
) -> str:
    canonical = skills_dir / skill.name
    destination = directory / skill.name
    try:
        mode = destination.lstat().st_mode
    except FileNotFoundError:
        mode = None
    if (
        mode is not None
        and destination.is_symlink()
        and destination.readlink() == canonical
    ):
        if link_mode == "symlink":
            return f"already linked {destination} -> {canonical}"
    elif mode is not None and not _marker_matches(destination):
        return f"Preserved unowned {destination}"
    if _same_existing_path(destination, canonical):
        return f"Skipped {destination}: it resolves to the canonical skill {canonical}"
    if dry_run:
        return (
            f"would {'link' if link_mode == 'symlink' else 'install copy'} "
            f"{destination}"
        )
    if link_mode == "symlink":
        fsops.replace_with_symlink(destination, canonical)
        return f"Linked harness skill {destination} -> {canonical}"
    if link_mode != "copy":
        raise ValueError(f"unknown link mode: {link_mode}")
    fsops.replace_directory(
        destination,
        lambda staged: (
            fsops.copy_directory(canonical, staged),
            fsops.write_file(staged / OWNERSHIP_MARKER, OWNERSHIP_VALUE),
        ),
    )
    return f"Installed harness skill copy {destination}"


def _remove_path(path: Path, dry_run: bool, remove) -> str:
    if dry_run:
        return f"would remove {path}"
    remove(path)
    return f"Removed {path}"


def _retired_harness_entry(entry: Path, canonical: Path, dry_run: bool) -> str | None:
    try:
        entry.lstat()
    except FileNotFoundError:
        return None
    if entry.is_symlink():
        if entry.readlink() != canonical:
            return f"Preserved unowned {entry}"
        return _remove_path(entry, dry_run, Path.unlink)
    if entry.is_dir() and _marker_matches(entry):
        return _remove_path(entry, dry_run, shutil.rmtree)
    return f"Preserved unowned {entry}"


def remove_retired(
    skills_dir: Path, harness_dirs: list[Path | None], dry_run: bool = False
) -> list[str]:
    """Remove retired skill installs that varde owns; keep foreign entries."""
    messages = []
    for name in RETIRED_SKILLS:
        canonical = skills_dir / name
        for directory in harness_dirs:
            if directory is None:
                continue
            message = _retired_harness_entry(directory / name, canonical, dry_run)
            if message is not None:
                messages.append(message)
        try:
            canonical.lstat()
        except FileNotFoundError:
            continue
        if _managed_directory(canonical) == "owned":
            messages.append(_remove_path(canonical, dry_run, shutil.rmtree))
        else:
            messages.append(f"Preserved unowned {canonical}")
    return messages
