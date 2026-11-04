"""Collect skill and agent data from installed providers."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import cache
from importlib.metadata import entry_points
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

from varde_core import skill_props

from varde.manifest import Manifest, install_closure, parse_manifest

_IGNORED_DIRS = {"evals", "__pycache__"}
_AGENT_VARIANTS = ("claude.md", "codex.toml", "opencode.md", "opencode-v2.md", "pi.md")


@dataclass(frozen=True)
class SkillFile:
    relative_path: str
    bytes: bytes
    executable: bool


@dataclass(frozen=True)
class Skill:
    name: str
    files: tuple[SkillFile, ...]


@dataclass(frozen=True)
class AgentVariant:
    file_name: str
    bytes: bytes


@dataclass(frozen=True)
class Agent:
    name: str
    variants: tuple[AgentVariant, ...]


def _visible_files(root: Traversable):
    def walk(directory: Traversable, prefix: str = ""):
        for item in sorted(directory.iterdir(), key=lambda path: path.name):
            relative = f"{prefix}/{item.name}" if prefix else item.name
            if (
                item.name.startswith(".")
                or item.name in _IGNORED_DIRS
                or item.name.endswith("-workspace")
            ):
                continue
            if item.is_dir():
                yield from walk(item, relative)
            elif item.is_file() and not item.name.endswith(".pyc"):
                yield item, relative

    yield from walk(root)


def _read_file(path: Traversable) -> tuple[bytes, bool]:
    content = path.read_bytes()
    executable = (
        bool(path.stat().st_mode & 0o111)
        if isinstance(path, Path)
        else content.startswith(b"#!")
    )
    return content, executable


def _manifest_rows(root: Traversable):
    manifest = root / "shared" / "MANIFEST"
    if not manifest.is_file():
        return
    for number, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
        fields = line.split()
        if not fields or fields[0].startswith("#"):
            continue
        if len(fields) < 2:
            raise ValueError(f"{manifest}:{number}: malformed shared manifest row")
        relative = Path(fields[0])
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError(f"{manifest}:{number}: invalid shared path: {fields[0]}")
        yield relative.as_posix(), tuple(fields[1:])


def collect_skills(
    roots: list[Traversable],
) -> tuple[Skill, ...]:
    found: dict[str, tuple[Traversable, dict[str, SkillFile]]] = {}
    shared: dict[str, tuple[Traversable, bytes, bool]] = {}
    for root in roots:
        for relative, _consumers in _manifest_rows(root) or ():
            path = root / "shared" / relative
            if relative in shared:
                raise ValueError(
                    f"shared path {relative} defined by both "
                    f"{shared[relative][0]} and {root}"
                )
            if not path.is_file():
                raise FileNotFoundError(
                    f"{root / 'shared/MANIFEST'}:{relative}: shared file is missing"
                )
            content, executable = _read_file(path)
            shared[relative] = (root, content, executable)
    for root in roots:
        for directory in sorted(root.iterdir(), key=lambda item: item.name):
            if (
                not directory.is_dir()
                or not directory.name.startswith("varde-")
                or not (directory / "SKILL.md").is_file()
            ):
                continue
            if directory.name in found:
                raise ValueError(
                    f"duplicate skill {directory.name} from "
                    f"{found[directory.name][0]} and {root}"
                )
            files = {}
            for path, relative in _visible_files(directory):
                content, executable = _read_file(path)
                files[relative] = SkillFile(relative, content, executable)
            found[directory.name] = (root, files)
    # A manifest from one provider may target a skill in another provider.
    for root in roots:
        for relative, consumers in _manifest_rows(root) or ():
            shared_item = shared.get(relative)
            if shared_item is None:
                raise FileNotFoundError(
                    f"{root / 'shared/MANIFEST'}: shared file {relative} is missing"
                )
            for consumer in consumers:
                if consumer in found:
                    found[consumer][1].setdefault(
                        relative, SkillFile(relative, shared_item[1], shared_item[2])
                    )
    return tuple(
        Skill(name, tuple(files[key] for key in sorted(files)))
        for name, (_, files) in sorted(found.items())
    )


def collect_agents(roots: list[Traversable]) -> tuple[Agent, ...]:
    found: dict[str, tuple[Traversable, tuple[AgentVariant, ...]]] = {}
    for root in roots:
        for directory in sorted(root.iterdir(), key=lambda item: item.name):
            if not directory.is_dir():
                continue
            names = _AGENT_VARIANTS
            variants = tuple(
                AgentVariant(name, (directory / name).read_bytes())
                for name in names
                if (directory / name).is_file()
            )
            if not variants:
                continue
            if directory.name in found:
                raise ValueError(
                    f"duplicate agent {directory.name} from "
                    f"{found[directory.name][0]} and {root}"
                )
            found[directory.name] = (root, variants)
    return tuple(Agent(name, variants) for name, (_, variants) in sorted(found.items()))


def _provider_roots(group: str, child: str) -> list[Traversable]:
    return [files(point.value) / child for point in entry_points(group=group)]


def _read_module_manifests(
    providers: list[tuple[str, Traversable]],
) -> dict[str, Manifest]:
    manifests = {}
    manifest_providers = {}
    for package, root in providers:
        path = root / "module.toml"
        if not path.is_file():
            raise FileNotFoundError(f"{package} provider is missing {path}")
        try:
            manifest = parse_manifest(path.read_text(encoding="utf-8"))
        except ValueError as error:
            raise ValueError(
                f"invalid manifest for provider {package}: {error}"
            ) from error
        if manifest.name in manifests:
            raise ValueError(
                f"module {manifest.name} is declared by both "
                f"{manifest_providers[manifest.name]} and {package}"
            )
        manifests[manifest.name] = manifest
        manifest_providers[manifest.name] = package
    return manifests


def module_manifests() -> dict[str, Manifest]:
    providers = [
        (point.value, files(point.value))
        for point in entry_points(group="varde.skills")
    ]
    return _read_module_manifests(providers)


def _module_preset_skills(
    module: str, manifests: dict[str, Manifest], names_by_module: dict[str, list[str]]
) -> list[str] | None:
    pending = [module]
    checked = set()
    while pending:
        current = pending.pop()
        if current in checked:
            continue
        manifest = manifests[current]
        if any(required not in manifests for required in manifest.requires):
            return None
        checked.add(current)
        pending.extend(manifest.requires)
    modules = install_closure(module, manifests)
    return sorted(
        name
        for required_module in modules
        for name in names_by_module.get(required_module, [])
    )


@cache
def preset_table() -> dict[str, list[str]]:
    """Build module presets from installed skill providers and manifests."""
    providers = [
        (point.value, files(point.value) / "skills")
        for point in entry_points(group="varde.skills")
    ]
    manifests = _read_module_manifests(
        [(package, files(package)) for package, _root in providers]
    )
    modules_by_package = {
        package: parse_manifest(
            (files(package) / "module.toml").read_text(encoding="utf-8")
        ).name
        for package, _root in providers
    }
    names_by_module: dict[str, list[str]] = {}
    all_names = {skill.name for skill in skills()}
    for package, root in providers:
        names = sorted(
            directory.name
            for directory in root.iterdir()
            if directory.is_dir()
            and (directory / "SKILL.md").is_file()
            and directory.name in all_names
        )
        module = modules_by_package.get(package)
        if module is not None:
            names_by_module[module] = names

    presets = {}
    for module, iter_names in names_by_module.items():
        if not iter_names or module in {"core", "app"}:
            continue
        names = _module_preset_skills(module, manifests, names_by_module)
        if names is None:
            continue
        presets[module] = names
    presets["full"] = sorted(all_names)
    return presets


def _registry_rows(package: Traversable, skill: str) -> list[dict[str, str]]:
    registry = package / "step_tools" / "registry.toml"
    if not registry.is_file():
        return []
    rows = tomllib.loads(registry.read_text(encoding="utf-8")).get("tool", [])
    return [row for row in rows if row.get("skill") == skill]


def _render_rows(rows: list[dict[str, str]]) -> bytes:
    triples = [(row["skill"], row["step"], row["entry"]) for row in rows]
    return skill_props.render_registry(triples).encode()


def _tree_files(root: Traversable, prefix: str) -> dict[str, SkillFile]:
    found = {}
    if not root.is_dir():
        return found
    for path, relative in _visible_files(root):
        content, executable = _read_file(path)
        name = f"{prefix}/{relative}"
        found[name] = SkillFile(name, content, executable)
    return found


def skill_extras(package: Traversable, skill: str) -> dict[str, SkillFile]:
    """How topics and step tools the package holds for one skill."""
    extras = _tree_files(package / "how" / skill, "how")
    extras.update(_tree_files(package / "step_tools" / skill, f"step_tools/{skill}"))
    rows = _registry_rows(package, skill)
    if rows:
        name = "step_tools/registry.toml"
        extras[name] = SkillFile(name, _render_rows(rows), False)
    return extras


def _with_extras(skill: Skill, packages: list[Traversable]) -> Skill:
    files = {file.relative_path: file for file in skill.files}
    for package in packages:
        for name, file in skill_extras(package, skill.name).items():
            files.setdefault(name, file)
    return Skill(skill.name, tuple(files[key] for key in sorted(files)))


def skills() -> tuple[Skill, ...]:
    providers = _provider_roots("varde.skills", "skills")
    if not providers:
        raise RuntimeError("no skill providers are installed")
    packages = [files(point.value) for point in entry_points(group="varde.skills")]
    return tuple(_with_extras(skill, packages) for skill in collect_skills(providers))


def agents() -> tuple[Agent, ...]:
    return collect_agents(_provider_roots("varde.agents", "agents"))
